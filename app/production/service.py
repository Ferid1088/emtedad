"""Production stage derivation and publication-target management.

Stage state is derived from persisted artifacts — never stored as a
free-floating flag — so the UI's allowed actions always reflect the DB.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.briefs.domain import BriefStatus
from app.briefs.models import ContentBrief
from app.content_engine.domain import (
    DraftStatus,
    FindingSeverity,
    FindingStatus,
    PlanStatus,
    ProductionStage,
    ReviewRunStatus,
    StageHealth,
)
from app.content_engine.models import (
    ArgumentPlan,
    NarrativePlan,
    ReviewCycle,
    ReviewFinding,
    ReviewRun,
    ScriptDraft,
)
from app.db.session import Database
from app.lecture.domain import MasterOriginType, MasterStatus
from app.lecture.models import LectureMasterVersion
from app.localization.domain import LocalizationStatus
from app.localization.models import LocalizationProject
from app.ops.settings.service import StudioSettingsService, speech_wpm
from app.production.models import PublicationTarget
from app.research.domain import (
    EvidenceMatrixStatus,
    PackageStatus,
    ResearchPlanStatus,
)
from app.research.models import (
    EvidenceMatrix,
    ResearchPackage,
    ResearchPlan,
)


@dataclass(frozen=True)
class ProductionState:
    """Derived stage + allowed actions for one brief's production."""

    brief: ContentBrief
    stage: ProductionStage
    stage_states: dict[ProductionStage, StageHealth]
    latest_matrix_id: UUID | None
    latest_argument_id: UUID | None
    latest_narrative_id: UUID | None
    latest_master_id: UUID | None
    latest_draft_id: UUID | None
    open_blockers: int
    open_warnings: int
    # Pre-review generation contract of the latest draft: PASSED, FAILED
    # (bounded corrections exhausted → GENERATION_REVIEW_REQUIRED), or ""
    # for drafts that predate the check. Review actions only unlock on
    # PASSED/legacy drafts — a failed generation is a generation defect,
    # not a review issue.
    generation_status: str = ""
    generation_failed_checks: tuple[str, ...] = ()
    # Review-cycle truth: the automatic revision budget applies per
    # owner-authorized cycle, not per brief lifetime. ``exhausted`` means
    # the current cycle reached max_revision_rounds → OWNER_REVIEW_REQUIRED
    # until the owner explicitly starts the next cycle.
    current_review_cycle: int = 1
    cycle_revisions_used: int = 0
    revision_budget_exhausted: bool = False
    # Final approval duration band (settings 25–30 min by default) —
    # distinct from the wider generation band that only admits a draft
    # into review. None when no draft exists yet.
    final_duration_minutes: float | None = None
    final_duration_in_band: bool | None = None
    allowed_actions: tuple[str, ...] = ()


async def _latest_id(
    session: AsyncSession,
    model: type,
    brief_id: UUID,
    status_values: list | None = None,  # type: ignore[type-arg]
) -> UUID | None:
    statement = select(model.id).where(model.content_brief_id == brief_id)  # type: ignore[attr-defined]
    if status_values is not None:
        statement = statement.where(model.status.in_(status_values))  # type: ignore[attr-defined]
    statement = statement.order_by(model.version_number.desc()).limit(1)  # type: ignore[attr-defined]
    result: UUID | None = await session.scalar(statement)
    return result


class ProductionService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def state_for_brief(self, brief_id: UUID) -> ProductionState:
        """Derive the production stage and allowed actions from the DB."""

        async with self.database.transaction() as session:
            brief = await session.get(ContentBrief, brief_id)
            if brief is None:
                raise LookupError(f"Unknown content brief {brief_id}")
            matrix_id = await _latest_id(
                session,
                EvidenceMatrix,
                brief_id,
                [EvidenceMatrixStatus.READY, EvidenceMatrixStatus.FROZEN],
            )
            argument_id = await _latest_id(
                session, ArgumentPlan, brief_id, [PlanStatus.READY]
            )
            narrative_id = await _latest_id(
                session, NarrativePlan, brief_id, [PlanStatus.READY]
            )
            master_id = await self._latest_ready_master(session, brief_id)
            draft_id = await _latest_id(session, ScriptDraft, brief_id)
            package_exists = bool(
                await session.scalar(
                    select(func.count(ResearchPackage.id)).where(
                        ResearchPackage.content_brief_id == brief_id,
                        ResearchPackage.status == PackageStatus.FROZEN,
                    )
                )
            )
            plan_exists = bool(
                await session.scalar(
                    select(func.count(ResearchPlan.id)).where(
                        ResearchPlan.content_brief_id == brief_id,
                        ResearchPlan.status == ResearchPlanStatus.READY,
                    )
                )
            )
            draft_matrix_exists = bool(
                await session.scalar(
                    select(func.count(EvidenceMatrix.id)).where(
                        EvidenceMatrix.content_brief_id == brief_id,
                        EvidenceMatrix.status == EvidenceMatrixStatus.DRAFT,
                    )
                )
            )
            open_blockers = 0
            open_warnings = 0
            latest_run: ReviewRun | None = None
            current_run: ReviewRun | None = None
            draft: ScriptDraft | None = None
            draft_status: DraftStatus | None = None
            generation_status = ""
            generation_failed_checks: tuple[str, ...] = ()
            if draft_id is not None:
                draft = await session.get(ScriptDraft, draft_id)
                if draft is not None:
                    draft_status = draft.status
                    validation = draft.provenance_json.get("generation_validation")
                    if isinstance(validation, dict):
                        generation_status = str(validation.get("status", ""))
                        raw_checks = validation.get("failed_checks", [])
                        if isinstance(raw_checks, list):
                            generation_failed_checks = tuple(
                                str(code) for code in raw_checks
                            )
                    latest_run = await session.scalar(
                        select(ReviewRun)
                        .where(ReviewRun.script_draft_id == draft_id)
                        .order_by(ReviewRun.round_number.desc())
                        .limit(1)
                    )
                    # The *current valid* review is the latest COMPLETED run
                    # matching this exact draft id + version + content hash.
                    # An older-hash run is historical; a newer RUNNING/FAILED
                    # run takes precedence for display but cannot certify.
                    current_run = await session.scalar(
                        select(ReviewRun)
                        .where(
                            ReviewRun.script_draft_id == draft_id,
                            ReviewRun.draft_version == draft.version_number,
                            ReviewRun.draft_hash == draft.content_hash,
                            ReviewRun.status == ReviewRunStatus.COMPLETED,
                        )
                        .order_by(ReviewRun.round_number.desc())
                        .limit(1)
                    )
                    if current_run is not None:
                        severity_rows = (
                            await session.execute(
                                select(ReviewFinding.severity, func.count())
                                .where(
                                    ReviewFinding.review_run_id == current_run.id,
                                    ReviewFinding.status == FindingStatus.OPEN,
                                )
                                .group_by(ReviewFinding.severity)
                            )
                        ).all()
                        counts = {row[0]: int(row[1]) for row in severity_rows}
                        open_blockers = int(counts.get(FindingSeverity.BLOCKER, 0))
                        open_warnings = int(counts.get(FindingSeverity.WARNING, 0))
            localization_total = 0
            localization_finished = 0
            if master_id is not None:
                loc_rows = (
                    await session.execute(
                        select(LocalizationProject.status, func.count())
                        .where(
                            LocalizationProject.lecture_master_version_id == master_id
                        )
                        .group_by(LocalizationProject.status)
                    )
                ).all()
                localization_total = sum(int(row[1]) for row in loc_rows)
                localization_finished = sum(
                    int(row[1])
                    for row in loc_rows
                    if row[0]
                    in {
                        LocalizationStatus.READY_FOR_VOICE,
                        LocalizationStatus.APPROVED,
                    }
                )

        current_cycle = int(
            (
                await session.scalar(
                    select(func.coalesce(func.max(ReviewCycle.cycle_number), 1)).where(
                        ReviewCycle.content_brief_id == brief_id
                    )
                )
            )
            or 1
        )
        # Revision budget counts persisted revisions in this cycle —
        # ReviewRuns (initial, duplicate, failed, retried) never consume it.
        cycle_rounds = int(
            (
                await session.scalar(
                    select(func.count(ScriptDraft.id)).where(
                        ScriptDraft.content_brief_id == brief_id,
                        ScriptDraft.revision_cycle == current_cycle,
                    )
                )
            )
            or 0
        )
        effective = await StudioSettingsService(self.database).effective()
        max_rounds = int(str(effective.get("max_revision_rounds", 3)))
        budget_exhausted = cycle_rounds >= max_rounds
        final_minutes: float | None = None
        final_in_band: bool | None = None
        if draft is not None:
            final_min = float(str(effective.get("target_duration_min_minutes", 25)))
            final_max = float(str(effective.get("target_duration_max_minutes", 30)))
            final_minutes = round(
                draft.actual_word_count / speech_wpm(effective, draft.language), 1
            )
            final_in_band = final_min <= final_minutes <= final_max

        stage = self._derive_stage(
            brief,
            matrix_id,
            argument_id,
            narrative_id,
            master_id,
            draft_status,
            package_exists,
        )
        return ProductionState(
            brief=brief,
            stage=stage,
            stage_states=self._stage_states(
                brief,
                plan_exists,
                draft_matrix_exists,
                matrix_id,
                argument_id,
                narrative_id,
                master_id,
                draft_id,
                draft_status,
                generation_status,
                latest_run,
                current_run,
                open_blockers,
                open_warnings,
                localization_total,
                localization_finished,
            ),
            latest_matrix_id=matrix_id,
            latest_argument_id=argument_id,
            latest_narrative_id=narrative_id,
            latest_master_id=master_id,
            latest_draft_id=draft_id,
            open_blockers=open_blockers,
            open_warnings=open_warnings,
            generation_status=generation_status,
            generation_failed_checks=generation_failed_checks,
            current_review_cycle=current_cycle,
            cycle_revisions_used=cycle_rounds,
            revision_budget_exhausted=budget_exhausted,
            final_duration_minutes=final_minutes,
            final_duration_in_band=final_in_band,
            allowed_actions=self._allowed(
                brief,
                matrix_id,
                argument_id,
                narrative_id,
                master_id,
                draft_id,
                draft_status,
                open_blockers,
                open_warnings,
                package_exists,
                plan_exists,
                latest_run,
                current_run,
                generation_status,
                budget_exhausted,
                final_in_band,
            ),
        )

    @staticmethod
    async def _latest_ready_master(
        session: AsyncSession, brief_id: UUID
    ) -> UUID | None:
        result: UUID | None = await session.scalar(
            select(LectureMasterVersion.id)
            .where(
                LectureMasterVersion.content_brief_id == brief_id,
                LectureMasterVersion.origin_type == MasterOriginType.CONTENT_BRIEF,
                LectureMasterVersion.status == MasterStatus.READY,
            )
            .order_by(LectureMasterVersion.version_number.desc())
            .limit(1)
        )
        return result

    @staticmethod
    def _derive_stage(
        brief: ContentBrief,
        matrix_id: UUID | None,
        argument_id: UUID | None,
        narrative_id: UUID | None,
        master_id: UUID | None,
        draft_status: DraftStatus | None,
        package_exists: bool,
    ) -> ProductionStage:
        if draft_status is DraftStatus.APPROVED:
            return ProductionStage.APPROVED
        if draft_status in {DraftStatus.IN_REVIEW, DraftStatus.REVISED}:
            return ProductionStage.REVIEW
        if draft_status is not None:
            return ProductionStage.SCRIPT
        if master_id is not None:
            return ProductionStage.MASTER
        if narrative_id is not None:
            return ProductionStage.NARRATIVE
        if argument_id is not None:
            return ProductionStage.ARGUMENT
        if matrix_id is not None:
            return ProductionStage.EVIDENCE
        if package_exists:
            return ProductionStage.RESEARCH
        if brief.status in {BriefStatus.READY, BriefStatus.LOCKED}:
            return ProductionStage.THESIS
        return ProductionStage.BRIEF

    @staticmethod
    def _stage_states(
        brief: ContentBrief,
        plan_exists: bool,
        draft_matrix_exists: bool,
        matrix_id: UUID | None,
        argument_id: UUID | None,
        narrative_id: UUID | None,
        master_id: UUID | None,
        draft_id: UUID | None,
        draft_status: DraftStatus | None,
        generation_status: str,
        latest_run: ReviewRun | None,
        current_run: ReviewRun | None,
        open_blockers: int,
        open_warnings: int,
        localization_total: int = 0,
        localization_finished: int = 0,
    ) -> dict[ProductionStage, StageHealth]:
        """Per-stage truth: a stage is complete only when its own persisted
        artifact is in a valid state — positional inference is forbidden."""

        brief_ready = brief.status in {BriefStatus.READY, BriefStatus.LOCKED}
        states: dict[ProductionStage, StageHealth] = {
            ProductionStage.BRIEF: (
                StageHealth.READY if brief_ready else StageHealth.IN_PROGRESS
            ),
            ProductionStage.THESIS: (
                StageHealth.READY if brief_ready else StageHealth.NOT_STARTED
            ),
            ProductionStage.RESEARCH: (
                StageHealth.READY if plan_exists else StageHealth.NOT_STARTED
            ),
            ProductionStage.EVIDENCE: (
                StageHealth.READY
                if matrix_id is not None
                else (
                    StageHealth.IN_PROGRESS
                    if draft_matrix_exists
                    else StageHealth.NOT_STARTED
                )
            ),
            ProductionStage.ARGUMENT: (
                StageHealth.READY if argument_id else StageHealth.NOT_STARTED
            ),
            ProductionStage.NARRATIVE: (
                StageHealth.READY if narrative_id else StageHealth.NOT_STARTED
            ),
            ProductionStage.MASTER: (
                StageHealth.READY if master_id else StageHealth.NOT_STARTED
            ),
            ProductionStage.SCRIPT: (
                StageHealth.NOT_STARTED
                if draft_id is None
                # The draft exists but violated the generation
                # contract and bounded correction could not fix it —
                # the owner must regenerate or inspect it manually
                # before any formal review runs.
                else (
                    StageHealth.REVIEW_REQUIRED
                    if generation_status == "FAILED"
                    else StageHealth.READY
                )
            ),
            ProductionStage.REVIEW: ProductionService._review_health(
                latest_run,
                current_run,
                open_blockers,
                open_warnings,
            ),
            ProductionStage.APPROVED: (
                StageHealth.APPROVED
                if draft_status is DraftStatus.APPROVED
                else StageHealth.NOT_STARTED
            ),
        }
        states[ProductionStage.LOCALIZATION] = (
            StageHealth.NOT_STARTED
            if localization_total == 0
            else (
                StageHealth.READY
                if localization_finished == localization_total
                else StageHealth.IN_PROGRESS
            )
        )
        # Voice rendering and publication are not wired into this state
        # map; they are reported as not started rather than faked.
        states[ProductionStage.VOICE] = StageHealth.NOT_STARTED
        states[ProductionStage.PUBLISHED] = StageHealth.NOT_STARTED
        return states

    @staticmethod
    def _review_health(
        latest_run: ReviewRun | None,
        current_run: ReviewRun | None,
        open_blockers: int,
        open_warnings: int,
    ) -> StageHealth:
        """REVIEW truth comes from ReviewRun lifecycle, not finding counts.

        A COMPLETED run with finding_count=0 is a clean review (READY);
        zero runs means review never ran (NOT_STARTED). A COMPLETED run
        whose hash no longer matches the current draft text is stale and
        demands re-review.
        """

        if latest_run is None:
            return StageHealth.NOT_STARTED
        if latest_run.status in {
            ReviewRunStatus.PENDING,
            ReviewRunStatus.RUNNING,
        }:
            return StageHealth.IN_PROGRESS
        if latest_run.status is ReviewRunStatus.FAILED:
            return StageHealth.FAILED
        if latest_run.id != (current_run.id if current_run is not None else None):
            # The latest run completed against an older draft hash —
            # manual edits invalidated it.
            return StageHealth.REVIEW_REQUIRED
        if open_blockers or open_warnings:
            return StageHealth.REVIEW_REQUIRED
        return StageHealth.READY

    @staticmethod
    def _allowed(
        brief: ContentBrief,
        matrix_id: UUID | None,
        argument_id: UUID | None,
        narrative_id: UUID | None,
        master_id: UUID | None,
        draft_id: UUID | None,
        draft_status: DraftStatus | None,
        open_blockers: int,
        open_warnings: int,
        package_exists: bool,
        plan_exists: bool,
        latest_run: ReviewRun | None,
        current_run: ReviewRun | None,
        generation_status: str = "",
        revision_budget_exhausted: bool = False,
        final_duration_in_band: bool | None = None,
    ) -> tuple[str, ...]:
        """§17.3: actions follow persisted state, never frontend guesses."""

        actions: list[str] = []
        if brief.status in {BriefStatus.READY, BriefStatus.LOCKED}:
            actions.append("plan_research")
            actions.append("build_evidence")
        if matrix_id is not None and plan_exists and not package_exists:
            # Freezing is the owner's explicit commitment that the research
            # base is final; the Semantic Master requires a FROZEN package.
            actions.append("freeze_research")
        if matrix_id is not None:
            actions.append("build_argument")
        if argument_id is not None:
            actions.append("build_narrative")
        if narrative_id is not None and package_exists:
            actions.append("build_master")
        if master_id is not None:
            actions.append("build_script")
        if (
            draft_id is not None
            and draft_status is not DraftStatus.APPROVED
            and generation_status != "FAILED"
        ):
            actions.append("run_review")
            actions.append("revise")
            # Approval requires a completed review of THIS exact draft text:
            # the latest run must be COMPLETED and match the current hash —
            # a clean run (0 findings) counts; missing/stale runs do not.
            review_current = (
                latest_run is not None
                and current_run is not None
                and latest_run.id == current_run.id
            )
            if revision_budget_exhausted:
                # Owner checkpoint: the current cycle's automatic budget is
                # spent — re-authorization is an explicit owner action.
                actions.append("start_review_cycle")
            if (
                review_current
                and open_blockers == 0
                and open_warnings == 0
                and final_duration_in_band is not False
            ):
                actions.append("approve")
        if draft_status is DraftStatus.APPROVED:
            actions.append("localize")
        return tuple(actions)

    async def create_target(
        self,
        channel_id: UUID,
        *,
        name: str,
        platform: str = "youtube",
        language: str = "fa",
    ) -> PublicationTarget:
        async with self.database.transaction() as session:
            target = PublicationTarget(
                editorial_channel_id=channel_id,
                platform=platform,
                language=language,
                name=name,
            )
            session.add(target)
            return target

    async def list_targets(self, channel_id: UUID) -> list[PublicationTarget]:
        async with self.database.transaction() as session:
            return list(
                (
                    await session.scalars(
                        select(PublicationTarget).where(
                            PublicationTarget.editorial_channel_id == channel_id
                        )
                    )
                ).all()
            )
