"""ScriptSignature derivation from approved production artifacts.

A signature is created exactly once — at the owner-approval transition of a
ScriptDraft — and is derived from canonical upstream artifacts (ContentBrief,
ArgumentPlan, NarrativePlan), never re-inferred from prose.
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.briefs.models import ContentBrief
from app.content_engine.models import (
    ArgumentPlan,
    NarrativePlan,
    ScriptDraft,
)
from app.knowledge.units.domain import KnowledgeUnitType
from app.knowledge.units.models import KnowledgeUnit
from app.topics.models import (
    ScriptSignature,
    TopicCandidateConcept,
    TopicCandidateUnit,
)

logger = logging.getLogger(__name__)


async def ensure_signature_for_draft(
    session: AsyncSession, draft: ScriptDraft
) -> ScriptSignature | None:
    """Create (or return the existing) signature for an approved draft.

    Idempotent on ``script_draft_id``: retries and duplicate approve calls
    return the same row. Returns ``None`` when the draft has no brief —
    a signature without canonical question/thesis would be meaningless.
    """

    existing = await session.scalar(
        select(ScriptSignature).where(ScriptSignature.script_draft_id == draft.id)
    )
    if existing is not None:
        return existing
    brief = await session.get(ContentBrief, draft.content_brief_id)
    if brief is None or brief.editorial_channel_id is None:
        logger.warning(
            "script_signature.skipped",
            extra={"draft_id": str(draft.id), "reason": "no_brief"},
        )
        return None
    argument = await session.scalar(
        select(ArgumentPlan)
        .where(ArgumentPlan.content_brief_id == brief.id)
        .options(selectinload(ArgumentPlan.sections))
        .order_by(ArgumentPlan.version_number.desc())
        .limit(1)
    )
    narrative = await session.scalar(
        select(NarrativePlan)
        .where(NarrativePlan.id == draft.narrative_plan_id)
        .options(selectinload(NarrativePlan.sections))
    )
    signature = ScriptSignature(
        editorial_channel_id=brief.editorial_channel_id,
        topic_candidate_id=brief.topic_candidate_id,
        script_draft_id=draft.id,
        editorial_project_id=draft.editorial_project_id,
        content_hash=draft.content_hash,
        question=brief.question,
        thesis=brief.thesis,
        angle=brief.angle,
        concept_ids=await _concept_ids(session, brief.topic_candidate_id),
        story_unit_ids=await _story_unit_ids(
            session, argument, narrative, brief.topic_candidate_id
        ),
        argument_signature=_argument_signature(argument),
        hook_type=_narrative_method(narrative, opening=True),
        ending_type=_narrative_method(narrative, opening=False),
    )
    session.add(signature)
    await session.flush()
    logger.info(
        "script_signature.created",
        extra={"draft_id": str(draft.id), "signature_id": str(signature.id)},
    )
    return signature


async def _concept_ids(session: AsyncSession, candidate_id: UUID | None) -> list[str]:
    if candidate_id is None:
        return []
    rows = await session.scalars(
        select(TopicCandidateConcept.concept_id).where(
            TopicCandidateConcept.topic_candidate_id == candidate_id
        )
    )
    return sorted(str(concept_id) for concept_id in rows)


async def _story_unit_ids(
    session: AsyncSession,
    argument: ArgumentPlan | None,
    narrative: NarrativePlan | None,
    candidate_id: UUID | None,
) -> list[str]:
    """Story/case-study unit refs from the bound plans (actual selected units)."""

    ids: set[str] = set()
    for plan in (argument, narrative):
        if plan is None:
            continue
        for section in plan.sections:
            for unit_id in section.story_unit_ids or []:
                ids.add(str(unit_id))
    if candidate_id is not None and not ids:
        # Fallback: candidate grounding units that are typed STORY/CASE_STUDY.
        rows = await session.scalars(
            select(TopicCandidateUnit.knowledge_unit_id)
            .join(
                KnowledgeUnit,
                KnowledgeUnit.id == TopicCandidateUnit.knowledge_unit_id,
            )
            .where(
                TopicCandidateUnit.topic_candidate_id == candidate_id,
                KnowledgeUnit.unit_type.in_(
                    (KnowledgeUnitType.STORY, KnowledgeUnitType.CASE_STUDY)
                ),
            )
        )
        ids = {str(unit_id) for unit_id in rows}
    return sorted(ids)


def _argument_signature(argument: ArgumentPlan | None) -> str:
    if argument is None or not argument.sections:
        return ""
    sections = sorted(argument.sections, key=lambda section: section.ordinal)
    return "→".join(str(section.role) for section in sections)


def _narrative_method(narrative: NarrativePlan | None, *, opening: bool) -> str:
    if narrative is None or not narrative.sections:
        return ""
    sections = sorted(narrative.sections, key=lambda section: section.ordinal)
    section = sections[0] if opening else sections[-1]
    method = section.opening_method if opening else section.ending_method
    return str(method or section.narrative_role or "")
