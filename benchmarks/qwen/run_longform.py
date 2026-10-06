"""Long-form benchmark: real build_script payload through Qwen.

Usage: uv run python -m benchmarks.qwen.run_longform <brief_uuid> <tag>

Calls the *production* ``ScriptService.build_script`` with a benchmark
Qwen provider — the payload assembly, voice contract, book-reference
selection, generation band, and correction loop are identical to what
the current writer receives. The resulting draft row is captured to
artifacts and then deleted, so no Qwen output becomes the production's
active draft and no owner state changes.

Critic pass: the normal Emtedad critic roles run against the captured
draft via the *current* production provider (Devin) — Qwen never grades
its own draft — plus the deterministic Persian/duration/book gates.
Findings are benchmark artifacts, not persisted ReviewFindings.
"""

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.briefs.models import ContentBrief
from app.content_engine.domain import (
    CRITIC_PROMPT_VERSION,
    CriticRole,
)
from app.content_engine.models import ArgumentPlan, NarrativePlan, ScriptDraft
from app.content_engine.review import (
    BOOK_REFERENCE_CHECKS,
    CRITIC_INSTRUCTIONS,
    ReviewFindingsOutput,
    ScriptService,
    _channel_checks,
    _critic_context,
    _persian_findings,
    _source_excerpts,
)
from app.content_engine.writing.books import (
    BookReference,
    book_reference_findings,
)
from app.content_engine.writing.quality import duration_findings, word_count
from app.core.config import get_settings
from app.db.session import Database
from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.knowledge.llm.factory import resolve_llm_provider
from app.ops.settings.service import StudioSettingsService, speech_wpm
from benchmarks.qwen.client import (
    MODEL,
    OpenRouterBenchmarkClient,
    QwenBenchmarkProvider,
)

ARTIFACT_DIR = Path("docs/audits/qwen_benchmark")


async def _run_llm_critics(
    session,
    draft: ScriptDraft,
    brief: ContentBrief,
    critic_provider: LLMProvider,
    tag: str,
) -> list[dict]:
    """Replicates ``_critique_draft``'s LLM loop without persisting."""

    checks = await _channel_checks(session, brief)
    context = await _critic_context(session, draft, brief)
    findings: list[dict] = []
    for role in CriticRole:
        if role is CriticRole.PERSIAN_QUALITY:
            continue  # deterministic — run separately
        role_checks = (
            checks + BOOK_REFERENCE_CHECKS
            if role is CriticRole.CHANNEL_SPECIFIC
            else checks
        )
        started = time.monotonic()
        try:
            result = await critic_provider.extract(
                StructuredExtractionRequest(
                    task="script_review",
                    prompt_version=CRITIC_PROMPT_VERSION,
                    model=MODEL,
                    instructions=CRITIC_INSTRUCTIONS.format(
                        role=role.value, checks=", ".join(role_checks)
                    ),
                    input_text=json.dumps(
                        {"draft": draft.text, "context": context},
                        ensure_ascii=False,
                    ),
                    output_model=ReviewFindingsOutput,
                )
            )
            output = ReviewFindingsOutput.model_validate(result.model_dump())
            for proposal in output.findings:
                findings.append(
                    {
                        "critic_role": role.value,
                        "critic_provider": tag,
                        "severity": proposal.severity.value,
                        "code": proposal.code,
                        "location": proposal.location[:200],
                        "explanation": proposal.explanation[:500],
                    }
                )
        except Exception as exc:
            findings.append(
                {
                    "critic_role": role.value,
                    "critic_provider": tag,
                    "severity": "CRITIC_ERROR",
                    "code": "CRITIC_PROVIDER_FAILED",
                    "location": "",
                    "explanation": str(exc)[:300],
                }
            )
        print(
            f"  critic {role.value} [{tag}] done in {time.monotonic() - started:.0f}s",
            flush=True,
        )
    return findings


async def _collect_findings(
    db: Database,
    draft: ScriptDraft,
    brief_id: UUID,
    qwen_provider: LLMProvider,
) -> tuple[list[dict], int]:
    findings: list[dict] = []
    async with db.transaction() as session:
        brief = await session.get(ContentBrief, brief_id)
        effective = await StudioSettingsService(db).effective()
        wpm = speech_wpm(effective, "fa")
        # Deterministic gates: duration, Persian quality/native/memory,
        # book-reference verification — the same checks review_draft runs.
        duration_checks, _count = duration_findings(
            draft.text, brief.target_duration_minutes, wpm=wpm
        )
        for check in duration_checks:
            findings.append(
                {
                    "critic_role": "DURATION",
                    "severity": "WARNING",
                    "code": check.code,
                    "location": check.category,
                    "explanation": check.message,
                }
            )
        for check in await _persian_findings(session, draft, brief):
            findings.append(
                {
                    "critic_role": "PERSIAN_QUALITY",
                    "severity": (
                        "BLOCKER"
                        if check.blocking
                        else ("WARNING" if check.severity != "INFO" else "INFO")
                    ),
                    "code": check.code,
                    "location": check.category,
                    "explanation": check.message,
                }
            )
        raw_refs = draft.provenance_json.get("book_references", [])
        book_refs = [
            BookReference.model_validate(item)
            for item in raw_refs
            if isinstance(item, dict)
        ]
        if book_refs:
            matrix_id = await session.scalar(
                select(ArgumentPlan.evidence_matrix_id)
                .join(
                    NarrativePlan,
                    NarrativePlan.argument_plan_id == ArgumentPlan.id,
                )
                .where(NarrativePlan.id == draft.narrative_plan_id)
            )
            source_texts = (
                await _source_excerpts(session, matrix_id)
                if matrix_id is not None
                else []
            )
            for check in book_reference_findings(draft.text, book_refs, source_texts):
                findings.append(
                    {
                        "critic_role": "BOOK_POLICY",
                        "severity": "BLOCKER" if check.blocking else "WARNING",
                        "code": check.code,
                        "location": check.location,
                        "explanation": check.message,
                    }
                )
        # LLM critics — current production provider (independent of Qwen).
        devin_provider = resolve_llm_provider()
        findings += await _run_llm_critics(
            session, draft, brief, devin_provider, "devin"
        )
        # Same roles through Qwen — measures Qwen-as-critic suitability.
        findings += await _run_llm_critics(session, draft, brief, qwen_provider, "qwen")
    return findings, wpm


async def main(brief_id: str, tag: str) -> None:
    db = Database(get_settings().database_url.get_secret_value())
    qwen_client = OpenRouterBenchmarkClient(timeout_seconds=1800)
    if not qwen_client.has_key:
        raise SystemExit("OpenRouter API key missing")
    qwen_provider = QwenBenchmarkProvider(qwen_client)
    service = ScriptService(db, provider=qwen_provider, model=MODEL)

    # --- generation through the real production path ---
    started = time.monotonic()
    draft = await service.build_script(UUID(brief_id), language="fa")
    gen_seconds = round(time.monotonic() - started, 1)
    draft_id = draft.id
    text = draft.text
    provenance = dict(draft.provenance_json)
    narrative_plan_id = draft.narrative_plan_id
    print(f"draft generated: {word_count(text)} words in {gen_seconds}s")

    wpm = 110
    findings: list[dict] = []
    try:
        findings, wpm = await _collect_findings(
            db, draft, UUID(brief_id), qwen_provider
        )
    finally:
        # Remove the benchmark draft no matter what — no Qwen artifact
        # becomes the production's active draft.
        async with db.transaction() as session:
            row = await session.get(ScriptDraft, draft_id)
            if row is not None:
                await session.delete(row)

    artifact = {
        "brief_id": brief_id,
        "tag": tag,
        "model": MODEL,
        "narrative_plan_id": str(narrative_plan_id),
        "word_count": word_count(text),
        "duration_minutes": round(word_count(text) / wpm, 2),
        "wpm": wpm,
        "generation_seconds": gen_seconds,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "text": text,
        "provenance": provenance,
        "findings": findings,
    }
    out = ARTIFACT_DIR / f"longform_{tag}.json"
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=1), "utf-8")
    Path(ARTIFACT_DIR / "raw" / f"longform_{tag}_text.fa.txt").write_text(text, "utf-8")
    print("wrote", out)
    await db.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
