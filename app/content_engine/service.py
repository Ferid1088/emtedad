"""Content engine orchestration with strict stage gates.

Gates (§29.5): no argument without a ready EvidenceMatrix; no narrative
without a ready ArgumentPlan.
"""

import hashlib
import json
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.briefs.domain import BriefStatus
from app.briefs.models import ContentBrief
from app.content_engine.argument import ArgumentArchitectAgent
from app.content_engine.domain import PlanStatus
from app.content_engine.models import (
    ArgumentPlan,
    ArgumentPlanSection,
    NarrativePlan,
    NarrativePlanSection,
)
from app.content_engine.narrative import NarrativeArchitectAgent
from app.content_engine.schemas import (
    ArgumentPlanOutput,
    NarrativePlanOutput,
    NarrativeSectionProposal,
)
from app.db.session import Database
from app.editorial_channels.models import ChannelStrategyVersion
from app.knowledge.llm.base import LLMProvider
from app.knowledge.llm.factory import resolve_llm_provider
from app.knowledge.llm.roles import AgentRole
from app.knowledge.llm.telemetry import DatabaseLLMRecorder
from app.knowledge.units.domain import KnowledgeUnitType
from app.knowledge.units.models import KnowledgeUnit
from app.ops.settings.service import StudioSettingsService
from app.research.domain import EvidenceMatrixStatus
from app.research.models import (
    EvidenceMatrix,
    EvidenceMatrixItem,
)
from app.topics.models import TopicCandidateUnit


class GateBlockedError(ValueError):
    """Raised when an upstream artifact is missing or not ready."""


def _calibrate_target_seconds(
    sections: list[NarrativeSectionProposal], target_minutes: float
) -> list[int]:
    """Scale the architect's per-beat budgets to the brief's duration.

    The model decides the distribution across beats; the total is a
    contract — when the sum drifts more than 10% from the planning
    target, rescale proportionally so the narrative plan hands the
    master (and writer) a truthful budget.
    """

    target_seconds = int(target_minutes * 60)
    raw = [max(int(section.target_seconds), 1) for section in sections]
    total = sum(raw)
    if total <= 0 or abs(total - target_seconds) <= target_seconds * 0.1:
        return raw
    scaled = [max(15, round(seconds * target_seconds / total)) for seconds in raw]
    # Fold the rounding remainder into the largest beat so the sum is exact.
    diff = target_seconds - sum(scaled)
    if diff and scaled:
        largest = max(range(len(scaled)), key=lambda i: scaled[i])
        scaled[largest] = max(15, scaled[largest] + diff)
    return scaled


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


async def _latest_matrix(session: AsyncSession, brief_id: UUID) -> EvidenceMatrix:
    matrix = await session.scalar(
        select(EvidenceMatrix)
        .where(
            EvidenceMatrix.content_brief_id == brief_id,
            EvidenceMatrix.status.in_(
                [EvidenceMatrixStatus.READY, EvidenceMatrixStatus.FROZEN]
            ),
        )
        .order_by(EvidenceMatrix.version_number.desc())
        .limit(1)
    )
    if matrix is None:
        raise GateBlockedError(
            "Cannot build argument: no ready EvidenceMatrix for the brief"
        )
    return matrix


async def _latest_argument(session: AsyncSession, brief_id: UUID) -> ArgumentPlan:
    plan = await session.scalar(
        select(ArgumentPlan)
        .where(
            ArgumentPlan.content_brief_id == brief_id,
            ArgumentPlan.status == PlanStatus.READY,
        )
        .options(selectinload(ArgumentPlan.sections))
        .order_by(ArgumentPlan.version_number.desc())
        .limit(1)
    )
    if plan is None:
        raise GateBlockedError(
            "Cannot build narrative: no ready ArgumentPlan for the brief"
        )
    return plan


async def _story_units(
    session: AsyncSession, brief: ContentBrief
) -> list[tuple[str, str]]:
    """(unit_id, title) pairs for story-typed grounding units."""

    unit_ids = (
        await session.scalars(
            select(TopicCandidateUnit.knowledge_unit_id).where(
                TopicCandidateUnit.topic_candidate_id == brief.topic_candidate_id
            )
        )
    ).all()
    if not unit_ids:
        return []
    units = (
        await session.scalars(
            select(KnowledgeUnit).where(
                KnowledgeUnit.id.in_(list(unit_ids)),
                KnowledgeUnit.unit_type.in_(
                    [KnowledgeUnitType.STORY, KnowledgeUnitType.CASE_STUDY]
                ),
            )
        )
    ).all()
    return [(str(unit.id), unit.title) for unit in units]


async def _strategy_payload(
    session: AsyncSession, strategy_version_id: UUID
) -> dict[str, object]:
    strategy = await session.get(ChannelStrategyVersion, strategy_version_id)
    if strategy is None:
        return {}
    return {
        "narrative": strategy.narrative_policy_json,
        "style": strategy.style_policy_json,
        "hook": strategy.hook_policy_json,
        "ending": strategy.ending_policy_json,
        "preferred_angles": strategy.preferred_angles_json,
    }


class ContentEngineService:
    """Build versioned argument/narrative plans behind stage gates."""

    def __init__(
        self,
        database: Database,
        *,
        provider: LLMProvider | None = None,
        model: str = "configured-default",
    ) -> None:
        self.database = database
        self.provider = provider
        self.model = model

    async def build_argument(self, brief_id: UUID) -> ArgumentPlan:
        async with self.database.transaction() as session:
            brief = await session.get(ContentBrief, brief_id)
            if brief is None:
                raise LookupError(f"Unknown content brief {brief_id}")
            if brief.status not in {BriefStatus.READY, BriefStatus.LOCKED}:
                raise GateBlockedError("Cannot build argument: brief is not READY")
            matrix = await _latest_matrix(session, brief_id)
            items = list(
                (
                    await session.scalars(
                        select(EvidenceMatrixItem)
                        .where(EvidenceMatrixItem.evidence_matrix_id == matrix.id)
                        .order_by(EvidenceMatrixItem.ordinal)
                    )
                ).all()
            )
            stories = await _story_units(session, brief)
            provider = self.provider or resolve_llm_provider(
                role=AgentRole.ARGUMENT_DRAFT,
                effective=await StudioSettingsService(self.database).effective(),
                recorder=DatabaseLLMRecorder(
                    self.database,
                    run_scope="production",
                    content_brief_id=brief_id,
                ),
            )
            output, labels = await ArgumentArchitectAgent(
                provider, model=self.model
            ).plan(
                brief=brief,
                items=items,
                story_units=stories,
                strategy_payload=await _strategy_payload(
                    session, brief.strategy_version_id
                ),
            )
            return await self._persist_argument(session, brief, matrix, output, labels)

    async def build_narrative(self, brief_id: UUID) -> NarrativePlan:
        async with self.database.transaction() as session:
            brief = await session.get(ContentBrief, brief_id)
            if brief is None:
                raise LookupError(f"Unknown content brief {brief_id}")
            argument = await _latest_argument(session, brief_id)
            stories = await _story_units(session, brief)
            provider = self.provider or resolve_llm_provider(
                role=AgentRole.NARRATIVE_DRAFT,
                effective=await StudioSettingsService(self.database).effective(),
                recorder=DatabaseLLMRecorder(
                    self.database,
                    run_scope="production",
                    content_brief_id=brief_id,
                ),
            )
            output, labels = await NarrativeArchitectAgent(
                provider, model=self.model
            ).plan(
                brief=brief,
                argument_sections=argument.sections,
                story_units=stories,
                strategy_payload=await _strategy_payload(
                    session, brief.strategy_version_id
                ),
            )
            return await self._persist_narrative(
                session, brief, argument, output, labels
            )

    async def _persist_argument(
        self,
        session: AsyncSession,
        brief: ContentBrief,
        matrix: EvidenceMatrix,
        output: ArgumentPlanOutput,
        labels: dict[str, str],
    ) -> ArgumentPlan:
        version = (
            await session.scalar(
                select(func.coalesce(func.max(ArgumentPlan.version_number), 0)).where(
                    ArgumentPlan.content_brief_id == brief.id
                )
            )
            or 0
        ) + 1
        plan = ArgumentPlan(
            content_brief_id=brief.id,
            evidence_matrix_id=matrix.id,
            version_number=version,
            status=PlanStatus.READY,
            content_hash=_hash(
                {
                    "brief": str(brief.id),
                    "matrix": str(matrix.id),
                    "output": output.model_dump(mode="json"),
                }
            ),
            provenance_json={
                "model": self.model,
                "evidence_matrix_version": matrix.version_number,
            },
        )
        plan.sections = [
            ArgumentPlanSection(
                ordinal=section.ordinal,
                role=section.role,
                purpose=section.purpose,
                claim_ids=[],
                evidence_item_ids=[
                    labels[ref] for ref in section.evidence_item_refs if ref in labels
                ],
                story_unit_ids=[
                    labels[ref] for ref in section.story_unit_refs if ref in labels
                ],
                counterargument_ids=[
                    labels[ref] for ref in section.counterargument_refs if ref in labels
                ],
                transition_intent=section.transition_intent,
                must_include=section.must_include,
                must_not_claim=section.must_not_claim,
            )
            for section in output.sections
        ]
        session.add(plan)
        await session.flush()
        return plan

    async def _persist_narrative(
        self,
        session: AsyncSession,
        brief: ContentBrief,
        argument: ArgumentPlan,
        output: NarrativePlanOutput,
        labels: dict[str, str],
    ) -> NarrativePlan:
        version = (
            await session.scalar(
                select(func.coalesce(func.max(NarrativePlan.version_number), 0)).where(
                    NarrativePlan.content_brief_id == brief.id
                )
            )
            or 0
        ) + 1
        calibrated = _calibrate_target_seconds(
            output.sections, brief.target_duration_minutes
        )
        plan = NarrativePlan(
            content_brief_id=brief.id,
            argument_plan_id=argument.id,
            version_number=version,
            status=PlanStatus.READY,
            content_hash=_hash(
                {
                    "brief": str(brief.id),
                    "argument": str(argument.id),
                    "output": output.model_dump(mode="json"),
                    "calibrated_seconds": calibrated,
                }
            ),
            provenance_json={
                "model": self.model,
                "argument_plan_version": argument.version_number,
                "target_seconds_raw": [
                    section.target_seconds for section in output.sections
                ],
                "target_seconds_total": sum(calibrated),
            },
        )
        plan.sections = [
            NarrativePlanSection(
                ordinal=section.ordinal,
                narrative_role=section.narrative_role,
                purpose=section.purpose,
                target_seconds=calibrated[index],
                argument_section_ids=[
                    labels[ref]
                    for ref in section.argument_section_refs
                    if ref in labels
                ],
                story_unit_ids=[
                    labels[ref] for ref in section.story_unit_refs if ref in labels
                ],
                emotional_function=section.emotional_function,
                transition_in=section.transition_in,
                transition_out=section.transition_out,
                opening_method=section.opening_method,
                ending_method=section.ending_method,
            )
            for index, section in enumerate(output.sections)
        ]
        session.add(plan)
        await session.flush()
        return plan
