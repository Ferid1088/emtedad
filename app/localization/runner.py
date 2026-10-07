"""Owner-facing driver for the native localization pipeline.

Translates the owner-approved Persian script (never the earlier Semantic
Master) into one target language by running every stage of
:class:`NativeLocalizationPipeline` until the run reaches a terminal
stage: READY_FOR_VOICE, BLOCKED, STALE_SOURCE, or FAILED.

An interrupted run (app restart, provider error) resumes from its
persisted stage the next time the owner starts it.
"""

import asyncio
from uuid import UUID

from sqlalchemy import select

from app.content_engine.service import GateBlockedError
from app.db.session import Database
from app.lecture.domain import PublicationLanguage
from app.localization.domain import LocalizationPipelineStage
from app.localization.models import (
    LocalizationPipelineRun,
    LocalizationSemanticPackage,
)
from app.localization.native_pipeline import NativeLocalizationPipeline
from app.localization.semantic_package import SemanticPackageService

TERMINAL_STAGES = frozenset(
    {
        LocalizationPipelineStage.READY_FOR_VOICE,
        LocalizationPipelineStage.BLOCKED,
        LocalizationPipelineStage.STALE_SOURCE,
        LocalizationPipelineStage.FAILED,
    }
)

# Languages of one brief run in parallel; choosing/creating the semantic
# package must not race (one package version per draft is a constraint).
_PACKAGE_LOCKS: dict[UUID, asyncio.Lock] = {}

# Safety bound for the review ⇄ correct loop; the pipeline itself also
# enforces its configured budget and moves the run to BLOCKED.
_MAX_STAGE_STEPS = 40


class NativeLocalizationRunner:
    """Run (or resume) the certified pipeline for one brief + language."""

    def __init__(
        self,
        database: Database,
        *,
        pipeline: NativeLocalizationPipeline | None = None,
        package_service: SemanticPackageService | None = None,
    ) -> None:
        self.database = database
        self.pipeline = pipeline or NativeLocalizationPipeline(database)
        self.package_service = package_service or SemanticPackageService(database)

    async def run_language(
        self, brief_id: UUID, language: PublicationLanguage
    ) -> LocalizationPipelineRun:
        if language is PublicationLanguage.FA:
            raise GateBlockedError("Persisch ist die Ausgangssprache, kein Ziel.")
        draft = await self.package_service.require_gate(brief_id)
        lock = _PACKAGE_LOCKS.setdefault(brief_id, asyncio.Lock())
        async with lock:
            run = await self._resumable_run(brief_id, draft.content_hash, language)
            if run is None:
                package_id = await self._package_without_run(
                    brief_id, draft.id, draft.content_hash, language
                )
                run = await self.pipeline.start(package_id, language)
        return await self._advance(run)

    async def _resumable_run(
        self, brief_id: UUID, draft_hash: str, language: PublicationLanguage
    ) -> LocalizationPipelineRun | None:
        """An unfinished run on the current approved text, if any."""

        async with self.database.transaction() as session:
            run = await session.scalar(
                select(LocalizationPipelineRun)
                .join(
                    LocalizationSemanticPackage,
                    LocalizationSemanticPackage.id
                    == LocalizationPipelineRun.semantic_package_id,
                )
                .where(
                    LocalizationSemanticPackage.content_brief_id == brief_id,
                    LocalizationSemanticPackage.source_draft_hash == draft_hash,
                    LocalizationPipelineRun.language == language,
                    LocalizationPipelineRun.stage.not_in(TERMINAL_STAGES),
                )
                .order_by(LocalizationPipelineRun.updated_at.desc())
                .limit(1)
            )
            if run is not None:
                session.expunge(run)
            return run

    async def _package_without_run(
        self,
        brief_id: UUID,
        draft_id: UUID,
        draft_hash: str,
        language: PublicationLanguage,
    ) -> UUID:
        """Reuse the newest current package that has no run for this
        language yet; otherwise build a fresh one (one run per package and
        language is a database constraint)."""

        async with self.database.transaction() as session:
            packages = list(
                await session.scalars(
                    select(LocalizationSemanticPackage)
                    .where(
                        LocalizationSemanticPackage.content_brief_id == brief_id,
                        LocalizationSemanticPackage.script_draft_id == draft_id,
                        LocalizationSemanticPackage.source_draft_hash == draft_hash,
                    )
                    .order_by(LocalizationSemanticPackage.version_number.desc())
                )
            )
            for package in packages:
                taken = await session.scalar(
                    select(LocalizationPipelineRun.id).where(
                        LocalizationPipelineRun.semantic_package_id == package.id,
                        LocalizationPipelineRun.language == language,
                    )
                )
                if taken is None:
                    return package.id
        package = await self.package_service.create_for_draft(
            draft_id, created_by="owner"
        )
        return package.id

    async def _advance(self, run: LocalizationPipelineRun) -> LocalizationPipelineRun:
        """Walk the persisted stages exactly like the certification driver:
        coverage → native draft → (review ⇄ correct) → premium → finalize."""

        for _ in range(_MAX_STAGE_STEPS):
            stage = run.stage
            if stage in TERMINAL_STAGES:
                return run
            if stage in {
                LocalizationPipelineStage.PENDING,
                LocalizationPipelineStage.SEMANTIC_ALIGNED,
            }:
                run = await self.pipeline.coverage_translate(run.id)
            elif stage is LocalizationPipelineStage.COVERAGE_TRANSLATED:
                run = await self.pipeline.native_draft(run.id)
            elif stage is LocalizationPipelineStage.NATIVE_DRAFTED:
                await self.pipeline.review(run.id)
                run = await self.pipeline._load_run(run.id)
            elif stage is LocalizationPipelineStage.NATIVE_REVIEW:
                run = await self.pipeline.correct(run.id)
            elif stage is LocalizationPipelineStage.FIDELITY_REVIEW:
                run = await self.pipeline.premium_final(run.id)
            elif stage is LocalizationPipelineStage.FINAL_FIDELITY:
                run = await self.pipeline.finalize(run.id)
            else:
                raise GateBlockedError(
                    f"Übersetzung steht in Stufe {stage.value} und kann nicht "
                    "automatisch fortgesetzt werden."
                )
        raise GateBlockedError(
            "Übersetzung hat die maximale Schrittzahl erreicht — bitte prüfen."
        )
