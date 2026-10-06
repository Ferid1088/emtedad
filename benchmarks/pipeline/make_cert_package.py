"""Build a certification LocalizationSemanticPackage from an Astra script.

Reads an ``astra_fa_loop`` artifact, persists its script as a
``lineage='dry_run'`` Persian ScriptDraft (status DRAFT — never approved,
never owner state), then builds the semantic package with the same Sol
extraction task the production service uses. The owner-approval gate in
``SemanticPackageService.create_for_draft`` stays intact; this benchmark
path declares provenance via ``created_by='dry_run_astra'`` and a dry_run
lineage draft row.

    uv run python -m benchmarks.pipeline.make_cert_package \
        benchmarks/pipeline/artifacts/astra_fa_loop2_*.json
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select

from app.briefs import models as _brief_models  # noqa: F401
from app.content_engine import models as _ce_models  # noqa: F401
from app.content_engine.domain import DraftStatus
from app.content_engine.models import (
    ArgumentPlan,
    NarrativePlan,
    ScriptDraft,
)
from app.core.config import get_settings
from app.db.session import Database
from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.llm.factory import resolve_llm_provider
from app.knowledge.llm.roles import AgentRole
from app.knowledge.llm.telemetry import DatabaseLLMRecorder
from app.localization import models as _loc_models  # noqa: F401
from app.localization.models import LocalizationSemanticPackage
from app.localization.semantic_package import (
    _PACKAGE_INSTRUCTIONS,
    PACKAGE_PROMPT_VERSION,
    SemanticPackageOutput,
    _hash,
)
from app.ops.settings import models as _set_models  # noqa: F401
from app.research import models as _r_models  # noqa: F401
from app.topics import models as _topic_models  # noqa: F401

OVERRIDES: dict[str, object] = {"llm_routing_enabled": True}


def _best_text(artifact: dict[str, object]) -> str:
    """The highest-scoring text: raw script or its best revision."""

    candidates: dict[str, str] = {
        "script": str(artifact["script"]["text"])  # type: ignore[index]
    }

    def _score(crit: object) -> float:
        if not isinstance(crit, dict):
            return 0.0
        n = (crit.get("native_critic") or {}).get("score") or 0  # type: ignore[union-attr]
        e = (crit.get("evidence_critic") or {}).get("score") or 0  # type: ignore[union-attr]
        return float(n) + float(e)

    scores: dict[str, float] = {"script": _score(artifact)}
    for key, value in artifact.items():
        if not str(key).startswith("revision") or not isinstance(value, dict):
            continue
        candidates[key] = str(value.get("text") or "")
        scores[key] = _score(artifact.get(f"critics_after_{key}"))
    best = max(candidates, key=lambda k: scores.get(k, 0.0))
    print(f"using {best} (score {scores.get(best, 0.0)})")
    return candidates[best]


async def main(artifact_path: Path) -> int:
    artifact = json.loads(artifact_path.read_text())
    brief_id = UUID(artifact["brief_id"])
    script_text = _best_text(artifact)
    book_refs = artifact["semantic_master"]["output"].get("allowed_book_references", [])
    db = Database(get_settings().database_url.get_secret_value())
    try:
        content_hash = hashlib.sha256(script_text.encode()).hexdigest()
        async with db.transaction() as session:
            # The draft row needs the brief's narrative plan FK.
            narrative_plan_id = await session.scalar(
                select(NarrativePlan.id)
                .join(
                    ArgumentPlan,
                    NarrativePlan.argument_plan_id == ArgumentPlan.id,
                )
                .where(ArgumentPlan.content_brief_id == brief_id)
                .order_by(NarrativePlan.created_at.desc())
                .limit(1)
            )
            if narrative_plan_id is None:
                raise SystemExit(f"no narrative plan found for brief {brief_id}")
            existing = await session.scalar(
                select(ScriptDraft).where(
                    ScriptDraft.content_hash == content_hash,
                    ScriptDraft.lineage == "dry_run",
                )
            )
            if existing is not None:
                draft = existing
            else:
                draft = ScriptDraft(
                    id=uuid4(),
                    content_brief_id=brief_id,
                    narrative_plan_id=narrative_plan_id,
                    language="fa",
                    lineage="dry_run",
                    # 101 keeps the (brief, language, version) unique
                    # constraint clear of real primary drafts (v1..).
                    version_number=101,
                    status=DraftStatus.DRAFT,
                    text=script_text,
                    content_hash=content_hash,
                    target_duration_minutes=27.5,
                    actual_word_count=len(script_text.split()),
                    # FA spoken pace is ~110 wpm (studio speech_wpm).
                    estimated_duration_seconds=int(
                        len(script_text.split()) / 110 * 60
                    ),
                    provenance_json={
                        "source": "astra_persian_writer benchmark",
                        "artifact": artifact_path.name,
                        "approved_by": "",
                        "book_references": book_refs,
                        "created_by": "dry_run_astra",
                    },
                )
                session.add(draft)
                await session.flush()
            draft_id = draft.id
        print(f"draft={draft_id} (lineage=dry_run, status=DRAFT)")

        provider = resolve_llm_provider(
            role=AgentRole.SEMANTIC_PACKAGE,
            effective=OVERRIDES,
            recorder=DatabaseLLMRecorder(
                db,
                run_scope="dry_run",
                content_brief_id=brief_id,
                language="fa",
            ),
        )
        input_text = json.dumps(
            {
                "source_script": script_text,
                "master_export": {},
                "book_references": book_refs,
                "language": "fa",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        result = await provider.extract(
            StructuredExtractionRequest(
                task="localization_semantic_package",
                prompt_version=PACKAGE_PROMPT_VERSION,
                model="configured-default",
                instructions=_PACKAGE_INSTRUCTIONS,
                input_text=input_text,
                output_model=SemanticPackageOutput,
                timeout_seconds=300,
            )
        )
        output = SemanticPackageOutput.model_validate(result.model_dump())
        payload: dict[str, object] = {
            "thesis": output.thesis,
            "conclusion": output.conclusion,
            "claim_ledger": [
                item.model_dump(mode="json") for item in output.claim_ledger
            ],
            "causal_constraints": output.causal_constraints,
            "counterarguments": output.counterarguments,
            "story_facts": output.story_facts,
            "emotional_beats": output.emotional_beats,
            "protected_terms": output.protected_terms,
            "localization_notes": output.localization_notes,
            "unresolved_ambiguities": output.unresolved_ambiguities,
            "book_references": book_refs,
            "terminology_references": [],
            "citations": [],
            "sections": [],
            "source": {
                "script_draft_id": str(draft_id),
                "source_draft_hash": content_hash,
                "lecture_master_version_id": None,
                "approved_by": "",
                "certification": "dry_run_astra",
            },
        }
        async with db.transaction() as session:
            version = (
                await session.scalar(
                    select(
                        __import__("sqlalchemy").func.coalesce(
                            __import__("sqlalchemy").func.max(
                                LocalizationSemanticPackage.version_number
                            ),
                            0,
                        )
                    ).where(LocalizationSemanticPackage.script_draft_id == draft_id)
                )
                or 0
            ) + 1
            package = LocalizationSemanticPackage(
                script_draft_id=draft_id,
                content_brief_id=brief_id,
                lecture_master_version_id=None,
                version_number=version,
                source_draft_hash=content_hash,
                payload=payload,
                content_hash=_hash(payload),
                provenance_json={
                    "prompt_version": PACKAGE_PROMPT_VERSION,
                    "agent_role": AgentRole.SEMANTIC_PACKAGE.value,
                    "certification": "dry_run_astra",
                },
                created_by="dry_run_astra",
            )
            session.add(package)
            await session.flush()
            print(f"package={package.id} v{version}")
        return 0
    finally:
        await db.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: make_cert_package <astra_artifact.json>")
    raise SystemExit(asyncio.run(main(Path(sys.argv[1]))))
