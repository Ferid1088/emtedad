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
)
from app.content_engine.models import (
    ArgumentPlan,
    NarrativePlan,
    ReviewFinding,
    ScriptDraft,
)
from app.db.session import Database
from app.lecture.domain import MasterOriginType, MasterStatus
from app.lecture.models import LectureMasterVersion
from app.production.models import PublicationTarget
from app.research.domain import EvidenceMatrixStatus, PackageStatus
from app.research.models import (
    EvidenceMatrix,
    ResearchPackage,
)


@dataclass(frozen=True)
class ProductionState:
    """Derived stage + allowed actions for one brief's production."""

    brief: ContentBrief
    stage: ProductionStage
    latest_matrix_id: UUID | None
    latest_argument_id: UUID | None
    latest_narrative_id: UUID | None
    latest_master_id: UUID | None
    latest_draft_id: UUID | None
    open_blockers: int
    allowed_actions: tuple[str, ...]


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
            open_blockers = 0
            if draft_id is not None:
                open_blockers = int(
                    await session.scalar(
                        select(func.count(ReviewFinding.id)).where(
                            ReviewFinding.script_draft_id == draft_id,
                            ReviewFinding.severity == FindingSeverity.BLOCKER,
                            ReviewFinding.status == FindingStatus.OPEN,
                        )
                    )
                    or 0
                )
            draft_status: DraftStatus | None = None
            if draft_id is not None:
                draft_status = await session.scalar(
                    select(ScriptDraft.status).where(ScriptDraft.id == draft_id)
                )

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
            latest_matrix_id=matrix_id,
            latest_argument_id=argument_id,
            latest_narrative_id=narrative_id,
            latest_master_id=master_id,
            latest_draft_id=draft_id,
            open_blockers=open_blockers,
            allowed_actions=self._allowed(
                brief,
                matrix_id,
                argument_id,
                narrative_id,
                master_id,
                draft_id,
                draft_status,
                open_blockers,
                package_exists,
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
    def _allowed(
        brief: ContentBrief,
        matrix_id: UUID | None,
        argument_id: UUID | None,
        narrative_id: UUID | None,
        master_id: UUID | None,
        draft_id: UUID | None,
        draft_status: DraftStatus | None,
        open_blockers: int,
        package_exists: bool,
    ) -> tuple[str, ...]:
        """§17.3: actions follow persisted state, never frontend guesses."""

        actions: list[str] = []
        if brief.status in {BriefStatus.READY, BriefStatus.LOCKED}:
            actions.append("plan_research")
            actions.append("build_evidence")
        if matrix_id is not None:
            actions.append("build_argument")
        if argument_id is not None:
            actions.append("build_narrative")
        if narrative_id is not None:
            actions.append("build_master")
        if master_id is not None:
            actions.append("build_script")
        if draft_id is not None and draft_status is not DraftStatus.APPROVED:
            actions.append("run_review")
            actions.append("revise")
            if open_blockers == 0:
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
