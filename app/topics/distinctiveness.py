"""Distinctiveness planner: compare a candidate against published shapes."""

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select

from app.db.session import Database
from app.editorial_channels.models import ChannelStrategyVersion
from app.topics.models import (
    ScriptSignature,
    TopicCandidate,
    TopicCandidateUnit,
)


class DistinctivenessVerdict(StrEnum):
    ACCEPT = "ACCEPT"
    REPLAN = "REPLAN"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True)
class OverlapReport:
    """Per-dimension max overlap scores against published signatures."""

    topic: float
    thesis: float
    story: float
    argument: float
    hook: float
    ending: float

    @property
    def worst(self) -> float:
        return max(
            self.topic,
            self.thesis,
            self.story,
            self.argument,
            self.hook,
            self.ending,
        )


_DEFAULTS = {"accept_below": 0.5, "review_above": 0.8}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def thresholds(strategy: ChannelStrategyVersion) -> dict[str, float]:
    """Per-strategy distinctiveness thresholds with safe defaults."""

    policy = strategy.topic_scoring_policy_json or {}
    raw = policy.get("distinctiveness", {})
    config = raw if isinstance(raw, dict) else {}
    return {key: float(config.get(key, default)) for key, default in _DEFAULTS.items()}


def _overlap(
    candidate: TopicCandidate,
    candidate_unit_ids: set[UUID],
    signature: ScriptSignature,
) -> OverlapReport:
    story_ids = set(signature.story_unit_ids)
    concept_question = _tokens(signature.question)
    return OverlapReport(
        topic=_jaccard(_tokens(candidate.video_question), concept_question),
        thesis=_jaccard(_tokens(candidate.tentative_thesis), _tokens(signature.thesis)),
        story=_jaccard({str(unit) for unit in candidate_unit_ids}, story_ids),
        argument=(
            1.0
            if signature.argument_signature
            and signature.angle.lower() == candidate.angle.lower()
            else 0.0
        ),
        hook=0.0,  # candidates have no hook yet
        ending=0.0,
    )


class DistinctivenessPlanner:
    """Decide whether a candidate is distinct enough to proceed."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def assess(
        self,
        candidate: TopicCandidate,
        strategy: ChannelStrategyVersion,
    ) -> tuple[DistinctivenessVerdict, OverlapReport]:
        async with self.database.transaction() as session:
            unit_ids = set(
                (
                    await session.scalars(
                        select(TopicCandidateUnit.knowledge_unit_id).where(
                            TopicCandidateUnit.topic_candidate_id == candidate.id
                        )
                    )
                ).all()
            )
            signatures = list(
                (
                    await session.scalars(
                        select(ScriptSignature).where(
                            ScriptSignature.editorial_channel_id
                            == candidate.editorial_channel_id
                        )
                    )
                ).all()
            )
        if not signatures:
            return DistinctivenessVerdict.ACCEPT, OverlapReport(0, 0, 0, 0, 0, 0)
        reports = [_overlap(candidate, unit_ids, signature) for signature in signatures]
        merged = OverlapReport(
            topic=max(report.topic for report in reports),
            thesis=max(report.thesis for report in reports),
            story=max(report.story for report in reports),
            argument=max(report.argument for report in reports),
            hook=max(report.hook for report in reports),
            ending=max(report.ending for report in reports),
        )
        limits = thresholds(strategy)
        if merged.worst >= limits["review_above"]:
            return DistinctivenessVerdict.REVIEW_REQUIRED, merged
        if merged.worst >= limits["accept_below"]:
            return DistinctivenessVerdict.REPLAN, merged
        return DistinctivenessVerdict.ACCEPT, merged
