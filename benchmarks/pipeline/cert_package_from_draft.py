"""Certification package from an existing Persian draft (loop-2 topics).

``make_cert_package.py`` ingests an Astra artifact; this variant pins an
already-persisted Persian draft's text as a ``lineage='dry_run'``
certification source and builds the semantic package through the same
Sol extraction task as production. The owner-approval gate is untouched —
the package is current only while the pinned text is unchanged, and it
is truthfully marked ``certification='dry_run_pinned'``.

    uv run python -m benchmarks.pipeline.cert_package_from_draft <draft_id>
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.briefs import models as _brief_models  # noqa: F401
from app.content_engine import models as _ce_models  # noqa: F401
from app.content_engine.domain import DraftStatus
from app.content_engine.models import ScriptDraft
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


async def main(draft_id: UUID) -> int:
    db = Database(get_settings().database_url.get_secret_value())
    try:
        async with db.transaction() as session:
            source = await session.get(ScriptDraft, draft_id)
            if source is None or source.language != "fa":
                raise SystemExit(f"no Persian draft {draft_id}")
            content_hash = hashlib.sha256(source.text.encode()).hexdigest()
            existing = await session.scalar(
                select(ScriptDraft).where(
                    ScriptDraft.content_hash == content_hash,
                    ScriptDraft.lineage == "dry_run",
                )
            )
            if existing is not None:
                draft = existing
            else:
                # 101+ keeps the (brief, language, version) constraint
                # clear of real primary drafts (v1..).
                next_version = (
                    await session.scalar(
                        select(
                            func.coalesce(func.max(ScriptDraft.version_number), 100)
                        ).where(
                            ScriptDraft.content_brief_id == source.content_brief_id,
                            ScriptDraft.language == "fa",
                            ScriptDraft.lineage == "dry_run",
                        )
                    )
                    or 100
                ) + 1
                draft = ScriptDraft(
                    id=uuid4(),
                    content_brief_id=source.content_brief_id,
                    narrative_plan_id=source.narrative_plan_id,
                    language="fa",
                    lineage="dry_run",
                    version_number=next_version,
                    status=DraftStatus.DRAFT,
                    text=source.text,
                    content_hash=content_hash,
                    target_duration_minutes=source.target_duration_minutes,
                    actual_word_count=len(source.text.split()),
                    estimated_duration_seconds=int(len(source.text.split()) / 110 * 60),
                    provenance_json={
                        "source": "certification pin of existing draft",
                        "pinned_from_draft": str(source.id),
                        "pinned_from_lineage": source.lineage,
                        "approved_by": "",
                        "book_references": source.provenance_json.get(
                            "book_references", []
                        ),
                        "created_by": "dry_run_pinned",
                    },
                )
                session.add(draft)
                await session.flush()
            draft_id = draft.id
            brief_id = draft.content_brief_id
            script_text = draft.text
            book_refs = draft.provenance_json.get("book_references", [])
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
                "certification": "dry_run_pinned",
            },
        }
        async with db.transaction() as session:
            version = (
                await session.scalar(
                    select(
                        func.coalesce(
                            func.max(LocalizationSemanticPackage.version_number), 0
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
                    "certification": "dry_run_pinned",
                },
                created_by="dry_run_pinned",
            )
            session.add(package)
            await session.flush()
            print(f"package={package.id} v{version}")
        return 0
    finally:
        await db.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: cert_package_from_draft <draft_id>")
    raise SystemExit(asyncio.run(main(UUID(sys.argv[1]))))
