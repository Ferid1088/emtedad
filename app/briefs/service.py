"""Create and validate ContentBriefs for topic candidates."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from app.briefs.domain import BriefStatus
from app.briefs.models import ContentBrief
from app.db.session import Database
from app.topics.domain import TopicStatus
from app.topics.models import TopicCandidate


@dataclass(frozen=True)
class BriefInput:
    """All required §9.1 fields; None where optional."""

    question: str
    thesis: str
    target_duration_minutes: int
    target_audience: str = ""
    angle: str = ""
    primary_concepts: tuple[str, ...] = ()
    required_evidence_roles: tuple[str, ...] = ()
    preferred_story_role: str | None = None
    required_counterargument: str | None = None
    forbidden_claims: tuple[str, ...] = ()
    forbidden_repetitions: tuple[str, ...] = ()


class BriefIncompleteError(ValueError):
    """Raised when a gate-required brief field is missing."""


def validate_ready(brief: ContentBrief) -> list[str]:
    """Return missing gate fields per §9.2; empty means research may start."""

    missing = [
        field
        for field, present in (
            ("question", bool(brief.question.strip())),
            ("thesis", bool(brief.thesis.strip())),
            ("editorial_channel_id", brief.editorial_channel_id is not None),
            ("strategy_version_id", brief.strategy_version_id is not None),
            (
                "target_duration_minutes",
                brief.target_duration_minutes > 0,
            ),
        )
        if not present
    ]
    return missing


class BriefService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_for_candidate(
        self, candidate_id: UUID, fields: BriefInput
    ) -> ContentBrief:
        """Create a brief pinned to a candidate's channel and strategy."""

        async with self.database.transaction() as session:
            candidate = await session.get(TopicCandidate, candidate_id)
            if candidate is None:
                raise LookupError(f"Unknown topic candidate {candidate_id}")
            if candidate.status in {
                TopicStatus.REJECTED,
                TopicStatus.ARCHIVED,
            }:
                raise ValueError(f"Candidate is {candidate.status}; cannot brief it")
            brief = ContentBrief(
                topic_candidate_id=candidate.id,
                editorial_channel_id=candidate.editorial_channel_id,
                strategy_version_id=candidate.strategy_version_id,
                question=fields.question,
                thesis=fields.thesis,
                target_audience=fields.target_audience,
                angle=fields.angle,
                primary_concepts_json=list(fields.primary_concepts),
                required_evidence_roles_json=list(fields.required_evidence_roles),
                preferred_story_role=fields.preferred_story_role,
                required_counterargument=fields.required_counterargument,
                forbidden_claims_json=list(fields.forbidden_claims),
                forbidden_repetitions_json=list(fields.forbidden_repetitions),
                target_duration_minutes=fields.target_duration_minutes,
            )
            missing = validate_ready(brief)
            if missing:
                raise BriefIncompleteError(
                    f"Brief is missing gate fields: {', '.join(missing)}"
                )
            session.add(brief)
            return brief

    async def list_for_candidate(self, candidate_id: UUID) -> list[ContentBrief]:
        async with self.database.transaction() as session:
            return list(
                (
                    await session.scalars(
                        select(ContentBrief).where(
                            ContentBrief.topic_candidate_id == candidate_id
                        )
                    )
                ).all()
            )

    async def get(self, brief_id: UUID) -> ContentBrief | None:
        async with self.database.transaction() as session:
            return await session.get(ContentBrief, brief_id)

    async def mark_ready(self, brief_id: UUID) -> ContentBrief:
        async with self.database.transaction() as session:
            brief = await session.get(ContentBrief, brief_id)
            if brief is None:
                raise LookupError(f"Unknown content brief {brief_id}")
            missing = validate_ready(brief)
            if missing:
                raise BriefIncompleteError(
                    f"Brief is missing gate fields: {', '.join(missing)}"
                )
            brief.status = BriefStatus.READY
            return brief
