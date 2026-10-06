"""Topic candidate mining and lifecycle service."""

import logging
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import Database
from app.editorial_channels.domain import StrategyStatus
from app.editorial_channels.models import (
    ChannelStrategyVersion,
    EditorialChannel,
    EditorialChannelResource,
)
from app.knowledge.llm.base import LLMProvider
from app.knowledge.llm.factory import resolve_llm_provider
from app.knowledge.llm.roles import AgentRole
from app.knowledge.models import ExternalConcept, SourceVersion
from app.knowledge.units.concepts import normalize_concept_name
from app.knowledge.units.models import KnowledgeUnit
from app.ops.settings.service import StudioSettingsService
from app.topics import scorer
from app.topics.domain import DEFAULT_COVERAGE_THRESHOLD, TopicStatus
from app.topics.miner import TopicMiner
from app.topics.models import (
    TopicCandidate,
    TopicCandidateConcept,
    TopicCandidateUnit,
)
from app.topics.novelty import novelty_score
from app.topics.schemas import TopicCandidateProposal, TopicMiningBatch

logger = logging.getLogger(__name__)

_ARABIC_SCRIPT = re.compile(
    "[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]"
)  # Arabic block + supplements + presentation forms
_LATIN_SCRIPT = re.compile(r"[A-Za-zÀ-ÿ]")
_ARABIC_LANGUAGES = {"fa", "ar", "ps", "ur"}
_LATIN_LANGUAGES = {"en", "de", "fr", "es", "tr", "nl", "it", "pt"}


def _language_matches(text: str, language: str) -> bool:
    """Lightweight script check: does the text plausibly match the language?"""

    arabic = len(_ARABIC_SCRIPT.findall(text))
    latin = len(_LATIN_SCRIPT.findall(text))
    if language in _ARABIC_LANGUAGES:
        return arabic > latin
    if language in _LATIN_LANGUAGES:
        return latin > 0 and latin > arabic
    return True


def _batch_language_ok(batch: TopicMiningBatch, language: str) -> bool:
    """Every editorial-facing proposal field must use the editorial language.

    Checked: title, video_question, tentative_thesis, angle,
    channel_fit_reason, knowledge_gaps. Lightweight script heuristic only —
    it catches obvious wrong-language responses, not semantic drift.
    """

    for proposal in batch.topics:
        fields = [
            proposal.title,
            proposal.video_question,
            proposal.tentative_thesis,
            proposal.angle,
            proposal.channel_fit_reason,
            " ".join(proposal.knowledge_gaps),
        ]
        if not all(
            _language_matches(field, language) for field in fields if field.strip()
        ):
            return False
    return True


_ALLOWED_TRANSITIONS: dict[TopicStatus, set[TopicStatus]] = {
    TopicStatus.CANDIDATE: {
        TopicStatus.SHORTLISTED,
        TopicStatus.REJECTED,
        TopicStatus.ARCHIVED,
        TopicStatus.NEEDS_RESEARCH,
    },
    TopicStatus.NEEDS_RESEARCH: {
        TopicStatus.IN_RESEARCH,
        TopicStatus.CANDIDATE,
        TopicStatus.REJECTED,
        TopicStatus.ARCHIVED,
    },
    TopicStatus.SHORTLISTED: {
        TopicStatus.SELECTED,
        TopicStatus.REJECTED,
        TopicStatus.ARCHIVED,
    },
    TopicStatus.SELECTED: {TopicStatus.IN_RESEARCH, TopicStatus.ARCHIVED},
    TopicStatus.IN_RESEARCH: {
        TopicStatus.READY_FOR_PRODUCTION,
        TopicStatus.REJECTED,
        TopicStatus.ARCHIVED,
    },
    TopicStatus.READY_FOR_PRODUCTION: {
        TopicStatus.IN_PRODUCTION,
        TopicStatus.ARCHIVED,
    },
    TopicStatus.IN_PRODUCTION: {TopicStatus.PUBLISHED, TopicStatus.ARCHIVED},
    TopicStatus.PUBLISHED: {TopicStatus.ARCHIVED},
    TopicStatus.REJECTED: {TopicStatus.ARCHIVED},
    TopicStatus.ARCHIVED: set(),
}


class TopicService:
    """Mine and manage topic candidates for one editorial channel."""

    def __init__(
        self,
        database: Database,
        *,
        provider: LLMProvider | None = None,
        model: str = "configured-default",
        max_units: int = 120,
    ) -> None:
        self.database = database
        self.provider = provider
        self.model = model
        self.max_units = max_units

    async def mine(
        self, channel_slug: str, *, owner_instruction: str | None = None
    ) -> list[TopicCandidate]:
        """Mine topic candidates from the channel's assigned resources."""

        async with self.database.transaction() as session:
            channel, strategy = await _active_strategy(session, channel_slug)
            units = await _channel_units(session, channel.id, self.max_units)
            if not units:
                return []
            existing_concepts = await _channel_candidate_concepts(session, channel.id)
            signatures = await _published_signatures(session, channel.id)
            effective = await StudioSettingsService(self.database).effective()
            provider = self.provider or resolve_llm_provider(
                role=AgentRole.TOPIC_MINER, effective=effective
            )
            editorial_language = strategy.editorial_language or "fa"
            miner = TopicMiner(provider, model=self.model)
            batch, labels = await miner.propose(
                strategy_payload=_strategy_payload(strategy),
                units=units,
                published_signatures=signatures,
                owner_instruction=owner_instruction,
                editorial_language=editorial_language,
            )
            language_review = False
            if not _batch_language_ok(batch, editorial_language):
                # One explicit correction pass before flagging for review.
                batch, labels = await miner.propose(
                    strategy_payload=_strategy_payload(strategy),
                    units=units,
                    published_signatures=signatures,
                    owner_instruction=owner_instruction,
                    editorial_language=editorial_language,
                    language_correction=True,
                )
                language_review = not _batch_language_ok(batch, editorial_language)
            if language_review:
                logger.warning(
                    "topic_mining.language_review_required",
                    extra={
                        "channel": channel_slug,
                        "expected_language": editorial_language,
                    },
                )
            weights = _scoring_weights(strategy)
            concepts_by_name = await _concept_index(
                session,
                {
                    name
                    for proposal in batch.topics
                    for name in proposal.supporting_concepts
                },
            )
            return [
                await self._persist(
                    session,
                    channel,
                    strategy,
                    proposal,
                    labels,
                    concepts_by_name,
                    existing_concepts,
                    weights,
                    owner_instruction,
                    language_review,
                )
                for proposal in batch.topics
            ]

    async def list_candidates(
        self, channel_slug: str, *, status: TopicStatus | None = None
    ) -> list[TopicCandidate]:
        async with self.database.transaction() as session:
            channel = await session.scalar(
                select(EditorialChannel).where(EditorialChannel.slug == channel_slug)
            )
            if channel is None:
                return []
            statement = (
                select(TopicCandidate)
                .where(TopicCandidate.editorial_channel_id == channel.id)
                .order_by(TopicCandidate.total_score.desc())
                .options(
                    selectinload(TopicCandidate.units),
                    selectinload(TopicCandidate.concepts).selectinload(
                        TopicCandidateConcept.concept
                    ),
                )
            )
            if status is not None:
                statement = statement.where(TopicCandidate.status == status)
            return list((await session.scalars(statement)).all())

    async def create_manual(
        self,
        channel_id: UUID,
        strategy_version_id: UUID,
        *,
        question: str,
        title: str = "",
        thesis: str = "",
        angle: str = "",
    ) -> TopicCandidate:
        """Owner-entered candidate. Scores stay 0 until mining/evidence exists."""

        async with self.database.transaction() as session:
            candidate = TopicCandidate(
                editorial_channel_id=channel_id,
                strategy_version_id=strategy_version_id,
                title=(title or question)[:1024],
                video_question=question,
                tentative_thesis=thesis,
                angle=angle or "manual",
                knowledge_coverage_score=0.0,
                channel_fit_score=0.0,
                novelty_score=0.0,
                curiosity_score=0.0,
                emotional_score=0.0,
                practical_value_score=0.0,
                total_score=0.0,
                provenance_json={"origin": "manual"},
            )
            session.add(candidate)
            await session.flush()
            return candidate

    async def set_status(
        self, candidate_id: UUID, status: TopicStatus
    ) -> TopicCandidate:
        async with self.database.transaction() as session:
            candidate = await session.get(TopicCandidate, candidate_id)
            if candidate is None:
                raise LookupError(f"Unknown topic candidate {candidate_id}")
            allowed = _ALLOWED_TRANSITIONS.get(candidate.status, set())
            if status not in allowed:
                raise ValueError(f"Cannot move {candidate.status} to {status}")
            candidate.status = status
            return candidate

    async def _persist(
        self,
        session: AsyncSession,
        channel: EditorialChannel,
        strategy: ChannelStrategyVersion,
        proposal: TopicCandidateProposal,
        labels: dict[str, UUID],
        concepts_by_name: dict[str, UUID],
        existing_concepts: list[set[UUID]],
        weights: dict[str, object],
        owner_instruction: str | None,
        language_review: bool,
    ) -> TopicCandidate:
        claimed = list(proposal.supporting_unit_refs)
        resolved = {ref for ref in claimed if ref in labels}
        coverage = scorer.coverage_score(claimed, resolved)
        concept_ids = {
            concept_id
            for name in proposal.supporting_concepts
            if (concept_id := concepts_by_name.get(normalize_concept_name(name)))
            is not None
        }
        novelty = novelty_score(concept_ids, existing_concepts)
        scores = scorer.component_scores(proposal, coverage=coverage, novelty=novelty)
        candidate = TopicCandidate(
            editorial_channel_id=channel.id,
            strategy_version_id=strategy.id,
            title=proposal.title,
            video_question=proposal.video_question,
            tentative_thesis=proposal.tentative_thesis,
            angle=proposal.angle,
            knowledge_coverage_score=scores["knowledge_coverage"],
            channel_fit_score=scores["channel_fit"],
            novelty_score=scores["novelty"],
            curiosity_score=scores["curiosity"],
            emotional_score=scores["emotional_relevance"],
            practical_value_score=scores["practical_value"],
            total_score=scorer.total_score(scores, weights),
            status=(
                TopicStatus.CANDIDATE
                if scorer.is_ready(coverage, _coverage_threshold(strategy))
                else TopicStatus.NEEDS_RESEARCH
            ),
            provenance_json={
                "knowledge_gaps": proposal.knowledge_gaps,
                "channel_fit_reason": proposal.channel_fit_reason,
                "claimed_unit_refs": claimed,
                "owner_instruction": owner_instruction,
                "model": self.model,
                "editorial_language": strategy.editorial_language,
                "language_review_required": language_review,
            },
        )
        session.add(candidate)
        await session.flush()
        for ref in resolved:
            session.add(
                TopicCandidateUnit(
                    topic_candidate_id=candidate.id,
                    knowledge_unit_id=labels[ref],
                )
            )
        for concept_id in concept_ids:
            session.add(
                TopicCandidateConcept(
                    topic_candidate_id=candidate.id, concept_id=concept_id
                )
            )
        return candidate


async def _active_strategy(
    session: AsyncSession, slug: str
) -> tuple[EditorialChannel, ChannelStrategyVersion]:
    channel = await session.scalar(
        select(EditorialChannel).where(EditorialChannel.slug == slug)
    )
    if channel is None:
        raise LookupError(f"Unknown editorial channel {slug!r}")
    strategy = await session.scalar(
        select(ChannelStrategyVersion)
        .where(
            ChannelStrategyVersion.editorial_channel_id == channel.id,
            ChannelStrategyVersion.status == StrategyStatus.ACTIVE,
        )
        .order_by(ChannelStrategyVersion.version_number.desc())
    )
    if strategy is None:
        raise LookupError(f"Channel {slug!r} has no active strategy")
    return channel, strategy


async def _channel_units(
    session: AsyncSession, channel_id: UUID, limit: int
) -> list[KnowledgeUnit]:
    """Units from the latest version of each channel-assigned source."""

    source_ids = (
        await session.scalars(
            select(EditorialChannelResource.source_id).where(
                EditorialChannelResource.editorial_channel_id == channel_id
            )
        )
    ).all()
    units: list[KnowledgeUnit] = []
    for source_id in source_ids:
        version_id = await session.scalar(
            select(SourceVersion.id)
            .where(SourceVersion.source_id == source_id)
            .order_by(SourceVersion.created_at.desc())
            .limit(1)
        )
        if version_id is None:
            continue
        units.extend(
            (
                await session.scalars(
                    select(KnowledgeUnit)
                    .where(KnowledgeUnit.source_version_id == version_id)
                    .order_by(KnowledgeUnit.created_at, KnowledgeUnit.id)
                )
            ).all()
        )
        if len(units) >= limit:
            break
    return units[:limit]


async def _channel_candidate_concepts(
    session: AsyncSession, channel_id: UUID
) -> list[set[UUID]]:
    pairs = (
        await session.execute(
            select(
                TopicCandidateConcept.topic_candidate_id,
                TopicCandidateConcept.concept_id,
            )
            .join(
                TopicCandidate,
                TopicCandidateConcept.topic_candidate_id == TopicCandidate.id,
            )
            .where(TopicCandidate.editorial_channel_id == channel_id)
        )
    ).all()
    by_candidate: dict[UUID, set[UUID]] = {}
    for candidate_id, concept_id in pairs:
        by_candidate.setdefault(candidate_id, set()).add(concept_id)
    return list(by_candidate.values())


async def _published_signatures(session: AsyncSession, channel_id: UUID) -> list[str]:
    """Questions of every persisted candidate — the miner must not re-derive them.

    Restricting this to PUBLISHED let a second ``mine()`` run regenerate
    near-identical questions already sitting as open candidates.
    """

    rows = (
        await session.scalars(
            select(TopicCandidate.video_question).where(
                TopicCandidate.editorial_channel_id == channel_id
            )
        )
    ).all()
    return list(rows)


async def _concept_index(session: AsyncSession, names: set[str]) -> dict[str, UUID]:
    """normalized name -> concept id, for resolving proposal concept names.

    Only the concepts the batch actually cites are loaded — scanning the
    whole ``external_concepts`` table per mining call is wasteful.
    """

    normalized = {normalize_concept_name(name) for name in names if name.strip()}
    if not normalized:
        return {}
    rows = (
        await session.execute(
            select(ExternalConcept.normalized_name, ExternalConcept.id).where(
                ExternalConcept.normalized_name.in_(normalized)
            )
        )
    ).all()
    return {name: cid for name, cid in rows}


def _strategy_payload(strategy: ChannelStrategyVersion) -> dict[str, object]:
    return {
        "audience": strategy.audience_json,
        "domains": strategy.domains_json,
        "preferred_angles": strategy.preferred_angles_json,
        "forbidden_angles": strategy.forbidden_angles_json,
        "source_policy": strategy.source_policy_json,
    }


def _scoring_weights(strategy: ChannelStrategyVersion) -> dict[str, object]:
    policy = strategy.topic_scoring_policy_json or {}
    weights = policy.get("weights", {})
    return weights if isinstance(weights, dict) else {}


def _coverage_threshold(strategy: ChannelStrategyVersion) -> float:
    policy = strategy.topic_scoring_policy_json or {}
    value = policy.get("coverage_threshold")
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_COVERAGE_THRESHOLD
