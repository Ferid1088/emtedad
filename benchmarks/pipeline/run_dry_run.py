"""Real dry-run production on a real topic (dry-run namespace).

Picks the latest owner-approved Persian primary draft, builds the shared
LocalizationSemanticPackage via Sol, then runs the native pipeline for
German, English, and Arabic through real APIMaster calls:

    coverage (Gemini) → native reconstruction (Gemini) → narrative edit
    (Gemini) → native + audience critics (Gemini) → fidelity critic (Sol)
    → targeted corrections → premium final edit (Astra, synchronous —
    APIMaster exposes no batch API) → final fidelity gate (Sol)
    → deterministic gates → READY_FOR_VOICE

Every model call writes ``ops.llm_call_events`` with
``run_scope='dry_run'``. Localized drafts carry ``lineage='localized'``
and never touch the Persian production stage. Nothing is approved.

Run:  uv run python -m benchmarks.pipeline.run_dry_run
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.content_engine.domain import DraftStatus
from app.content_engine.models import ScriptDraft
from app.core.config import get_settings
from app.db.session import Database
from app.knowledge.llm.factory import resolve_llm_provider
from app.knowledge.llm.models import LLMCallEvent
from app.knowledge.llm.roles import AgentRole
from app.knowledge.llm.telemetry import DatabaseLLMRecorder
from app.lecture.domain import PublicationLanguage
from app.localization.domain import LocalizationPipelineStage
from app.localization.models import LocalizationSemanticPackage
from app.localization.native_pipeline import NativeLocalizationPipeline
from app.localization.semantic_package import SemanticPackageService

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
DRY_RUN_OVERRIDES: dict[str, object] = {"llm_routing_enabled": True}


async def _latest_approved_fa(database: Database) -> ScriptDraft:
    async with database.transaction() as session:
        draft = await session.scalar(
            select(ScriptDraft)
            .where(
                ScriptDraft.language == "fa",
                ScriptDraft.lineage == "primary",
                ScriptDraft.status == DraftStatus.APPROVED,
            )
            .order_by(ScriptDraft.version_number.desc())
            .limit(1)
        )
        if draft is None:
            raise SystemExit("No owner-approved Persian primary draft found")
        session.expunge(draft)
        return draft


async def _language_run(
    pipeline: NativeLocalizationPipeline,
    package_id: UUID,
    language: PublicationLanguage,
    log: list[dict[str, Any]],
) -> dict[str, Any]:
    run = await pipeline.start(package_id, language)
    entry: dict[str, Any] = {
        "language": language.value,
        "run_id": str(run.id),
        "stages": [],
    }

    def mark(stage: LocalizationPipelineStage) -> None:
        entry["stages"].append(stage.value)

    run = await pipeline.coverage_translate(run.id)
    mark(run.stage)
    run = await pipeline.native_draft(run.id)
    mark(run.stage)
    # Review/correction loop: at most MAX_REVIEW_LOOPS repairs; the last
    # allowed review must be able to verify the repaired draft. The
    # pipeline itself enforces the budget via correct() → BLOCKED.
    while run.stage is not LocalizationPipelineStage.FIDELITY_REVIEW:
        await pipeline.review(run.id)
        run = await pipeline._load_run(run.id)  # truthful fresh state
        entry.setdefault("loops", []).append(
            {
                "loop": run.review_loop,
                "stage": run.stage.value,
                "fidelity": run.fidelity_status,
                "native": run.native_status,
            }
        )
        if run.stage is LocalizationPipelineStage.FIDELITY_REVIEW:
            break
        run = await pipeline.correct(run.id)
        # NATIVE_DRAFTED → loop; BLOCKED/terminal → honest stop.
        if run.stage is not LocalizationPipelineStage.NATIVE_DRAFTED:
            break
    if run.stage is LocalizationPipelineStage.FIDELITY_REVIEW:
        run = await pipeline.premium_final(run.id)
        mark(run.stage)
        # finalize may bounce back to FINAL_FIDELITY once for a bounded
        # post-premium targeted repair — re-gate until terminal.
        while run.stage is LocalizationPipelineStage.FINAL_FIDELITY:
            run = await pipeline.finalize(run.id)
            mark(run.stage)
    entry["outcome"] = run.stage.value
    entry["error"] = run.error
    log.append(entry)
    return entry


async def main() -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    database = Database(settings.database_url.get_secret_value())
    started = time.monotonic()
    # --package-id runs the pipeline on an existing certification package
    # (e.g. one built from an Astra-written dry-run script) instead of
    # rebuilding one from the latest owner-approved draft.
    package_override = (
        UUID(sys.argv[sys.argv.index("--package-id") + 1])
        if "--package-id" in sys.argv
        else None
    )
    try:
        if package_override is not None:
            # Certification path: the pinned dry_run draft is the master
            # for this run — do not confuse it with the approved draft.
            async with database.transaction() as session:
                package_row = await session.get(
                    LocalizationSemanticPackage, package_override
                )
                if package_row is None:
                    raise SystemExit(f"package {package_override} not found")
                pinned = await session.get(
                    ScriptDraft, package_row.script_draft_id
                )
                if pinned is None:
                    raise SystemExit("pinned source draft missing")
                session.expunge(pinned)
            draft = pinned
        else:
            draft = await _latest_approved_fa(database)
        print(f"Persian master: draft={draft.id} brief={draft.content_brief_id}")

        # --- Package via Sol (routed role) -------------------------------
        package_provider = resolve_llm_provider(
            role=AgentRole.SEMANTIC_PACKAGE,
            effective=DRY_RUN_OVERRIDES,
            recorder=DatabaseLLMRecorder(
                database,
                run_scope="dry_run",
                content_brief_id=draft.content_brief_id,
                language="fa",
            ),
        )
        package_service = SemanticPackageService(database, provider=package_provider)
        # Reuse the current package for this draft when one already exists
        # AND has no pipeline runs attached — rerunning the canary must not
        # mint duplicate package versions, but a package with existing runs
        # cannot start fresh languages (uq_pipeline_run_language).
        from app.localization.models import LocalizationPipelineRun

        async with database.transaction() as session:
            package = await session.scalar(
                select(LocalizationSemanticPackage)
                .where(
                    LocalizationSemanticPackage.source_draft_hash == draft.content_hash,
                    LocalizationSemanticPackage.content_brief_id
                    == draft.content_brief_id,
                )
                .order_by(LocalizationSemanticPackage.version_number.desc())
                .limit(1)
            )
            if package is not None:
                has_runs = await session.scalar(
                    select(LocalizationPipelineRun.id)
                    .where(LocalizationPipelineRun.semantic_package_id == package.id)
                    .limit(1)
                )
                if has_runs is not None:
                    package = None
                else:
                    session.expunge(package)
        if package_override is not None:
            async with database.transaction() as session:
                package = await session.get(
                    LocalizationSemanticPackage, package_override
                )
                if package is None:
                    raise SystemExit(f"package {package_override} not found")
                session.expunge(package)
        elif package is None:
            package = await package_service.create_for_draft(
                draft.id, created_by="dry_run"
            )
        print(f"package={package.id} v{package.version_number}")

        # --- Per-language native pipelines --------------------------------
        pipeline = NativeLocalizationPipeline(
            database,
            effective_overrides=DRY_RUN_OVERRIDES,
            run_scope="dry_run",
        )
        log: list[dict[str, Any]] = []
        for language in (
            PublicationLanguage.DE,
            PublicationLanguage.EN,
            PublicationLanguage.AR,
        ):
            print(f"--- {language.value} ---")
            try:
                entry = await _language_run(pipeline, package.id, language, log)
                print(f"    → {entry['outcome']}")
            except Exception as exc:  # noqa: BLE001 — record honestly
                log.append(
                    {
                        "language": language.value,
                        "outcome": "EXCEPTION",
                        "error": f"{type(exc).__name__}: {exc}"[:500],
                    }
                )
                print(f"    → EXCEPTION {type(exc).__name__}: {exc}"[:200])

        # --- Cost truth ----------------------------------------------------
        # Scope to calls created after this run started — the events table
        # keeps historical dry runs, and mixing providers/runs would lie.
        from datetime import UTC, datetime

        run_started = datetime.fromtimestamp(
            time.time() - (time.monotonic() - started), UTC
        )
        async with database.transaction() as session:
            rows = (
                await session.execute(
                    select(
                        LLMCallEvent.provider,
                        LLMCallEvent.model,
                        LLMCallEvent.language,
                        LLMCallEvent.task,
                        LLMCallEvent.prompt_tokens,
                        LLMCallEvent.completion_tokens,
                        LLMCallEvent.cached_tokens,
                        LLMCallEvent.cost_usd,
                        LLMCallEvent.latency_ms,
                        LLMCallEvent.retries,
                    )
                    .where(LLMCallEvent.run_scope == "dry_run")
                    .where(LLMCallEvent.created_at >= run_started)
                )
            ).all()
        calls = [
            {
                "provider": r.provider,
                "model": r.model,
                "language": r.language,
                "task": r.task,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "cached_tokens": r.cached_tokens,
                "cost_usd": r.cost_usd,
                "latency_ms": r.latency_ms,
                "retries": r.retries,
            }
            for r in rows
        ]
        total_cost = sum(
            float(c["cost_usd"] or 0) for c in calls if c["provider"] == "apimaster"
        )
        missing_cost = sum(
            1 for c in calls if c["provider"] == "apimaster" and c["cost_usd"] is None
        )
        # CURRENT_MARKET_ESTIMATE — token usage × live marketplace snapshot.
        # Kept strictly separate from ACTUAL_PROVIDER_COST.
        estimate: dict[str, object] = {"status": "unavailable"}
        try:
            from app.knowledge.llm.pricing import (
                estimate_cost_usd,
                fetch_price_snapshot,
            )

            snapshot = fetch_price_snapshot({c["model"] for c in calls})
            low = high = 0.0
            per_model: dict[str, dict[str, float]] = {}
            for c in calls:
                if c["provider"] != "apimaster":
                    continue
                price = snapshot.models.get(str(c["model"]))
                if price is None:
                    continue
                est = estimate_cost_usd(
                    price,
                    prompt_tokens=int(c["prompt_tokens"] or 0),
                    completion_tokens=int(c["completion_tokens"] or 0),
                    cached_tokens=int(c["cached_tokens"] or 0),
                )
                low += float(est["low"] or 0)
                high += float(est["high"] or 0)
                slot = per_model.setdefault(str(c["model"]), {"low": 0.0, "high": 0.0})
                slot["low"] += float(est["low"] or 0)
                slot["high"] += float(est["high"] or 0)
            estimate = {
                "status": "ok",
                "snapshot_at": snapshot.retrieved_at,
                "pricing_version": snapshot.pricing_version,
                "group": snapshot.group,
                "source": snapshot.source,
                "low_usd": round(low, 6),
                "high_usd": round(high, 6),
                "per_model": {
                    name: {"low": round(v["low"], 6), "high": round(v["high"], 6)}
                    for name, v in sorted(per_model.items())
                },
            }
        except Exception as exc:  # noqa: BLE001 — honest artifact, not crash
            estimate = {"status": f"snapshot_failed: {type(exc).__name__}"}
        artifact = {
            "topic_brief_id": str(draft.content_brief_id),
            "source_draft_id": str(draft.id),
            "source_draft_hash": draft.content_hash,
            "package_id": str(package.id),
            "wall_clock_s": round(time.monotonic() - started, 1),
            "languages": log,
            "calls": calls,
            "actual_provider_cost_usd": round(total_cost, 6),
            "cost_missing_for_calls": missing_cost,
            "market_estimate": estimate,
            "call_count": len(calls),
        }
        out = ARTIFACT_DIR / f"dry_run_{int(time.time())}.json"
        out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
        print(
            f"\nactual provider cost: ${total_cost:.4f} "
            f"({missing_cost}/{len(calls)} calls without provider cost)"
        )
        if estimate.get("status") == "ok":
            print(
                f"market estimate: ${estimate['low_usd']}–"
                f"${estimate['high_usd']} ({estimate['source']})"
            )
        print(f"wrote {out}")
        return 0
    finally:
        await database.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
