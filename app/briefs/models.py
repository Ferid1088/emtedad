"""ContentBrief: the required editorial contract for a topic candidate."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.briefs.domain import BriefStatus
from app.db.base import Base, PostgresSchema
from app.ops.assets.models import utc_now
from app.topics.models import TopicCandidate

CONTENT = PostgresSchema.CONTENT.value


def _enum(enum_type: type[Any], name: str) -> ENUM:
    return ENUM(
        enum_type,
        name=name,
        schema=CONTENT,
        values_callable=lambda members: [member.value for member in members],
    )


class ContentBrief(Base):
    """Frozen editorial intent; required before research can start.

    The §9.2 gate is enforced by the NOT NULL columns plus
    ``BriefService.validate_ready``.
    """

    __tablename__ = "content_briefs"
    __table_args__ = (
        CheckConstraint("target_duration_minutes > 0", name="positive_target_duration"),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    topic_candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.topic_candidates.id", ondelete="CASCADE"),
        index=True,
    )
    editorial_channel_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.editorial_channels.id", ondelete="RESTRICT")
    )
    strategy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.channel_strategy_versions.id", ondelete="RESTRICT")
    )

    question: Mapped[str] = mapped_column(Text)
    thesis: Mapped[str] = mapped_column(Text)
    target_audience: Mapped[str] = mapped_column(Text, default="")
    angle: Mapped[str] = mapped_column(Text, default="")

    primary_concepts_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    required_evidence_roles_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    preferred_story_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_counterargument: Mapped[str | None] = mapped_column(Text, nullable=True)
    forbidden_claims_json: Mapped[list[str]] = mapped_column(JSONB, default=list)
    forbidden_repetitions_json: Mapped[list[str]] = mapped_column(JSONB, default=list)

    target_duration_minutes: Mapped[int] = mapped_column(Integer)

    status: Mapped[BriefStatus] = mapped_column(
        _enum(BriefStatus, "content_brief_status"),
        default=BriefStatus.DRAFT,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    topic_candidate: Mapped[TopicCandidate] = relationship()
