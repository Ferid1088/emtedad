"""Topic candidates mined from channel-assigned knowledge."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PostgresSchema
from app.knowledge.models import ExternalConcept
from app.ops.assets.models import utc_now
from app.topics.domain import TopicStatus

CONTENT = PostgresSchema.CONTENT.value
KNOWLEDGE = PostgresSchema.KNOWLEDGE.value


def _enum(enum_type: type[Any], name: str) -> ENUM:
    return ENUM(
        enum_type,
        name=name,
        schema=CONTENT,
        values_callable=lambda members: [member.value for member in members],
    )


class TopicCandidate(Base):
    __tablename__ = "topic_candidates"
    __table_args__ = (
        CheckConstraint(
            "knowledge_coverage_score >= 0 AND knowledge_coverage_score <= 1",
            name="valid_coverage",
        ),
        CheckConstraint(
            "channel_fit_score >= 0 AND channel_fit_score <= 1",
            name="valid_channel_fit",
        ),
        CheckConstraint(
            "novelty_score >= 0 AND novelty_score <= 1", name="valid_novelty"
        ),
        CheckConstraint(
            "curiosity_score >= 0 AND curiosity_score <= 1",
            name="valid_curiosity",
        ),
        CheckConstraint(
            "emotional_score >= 0 AND emotional_score <= 1",
            name="valid_emotional",
        ),
        CheckConstraint(
            "practical_value_score >= 0 AND practical_value_score <= 1",
            name="valid_practical",
        ),
        CheckConstraint("total_score >= 0 AND total_score <= 1", name="valid_total"),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    editorial_channel_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.editorial_channels.id", ondelete="CASCADE"),
        index=True,
    )
    strategy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.channel_strategy_versions.id", ondelete="RESTRICT")
    )

    title: Mapped[str] = mapped_column(String(1024))
    video_question: Mapped[str] = mapped_column(Text)
    tentative_thesis: Mapped[str] = mapped_column(Text)
    angle: Mapped[str] = mapped_column(Text)

    knowledge_coverage_score: Mapped[float] = mapped_column(Float)
    channel_fit_score: Mapped[float] = mapped_column(Float)
    novelty_score: Mapped[float] = mapped_column(Float)
    curiosity_score: Mapped[float] = mapped_column(Float)
    emotional_score: Mapped[float] = mapped_column(Float)
    practical_value_score: Mapped[float] = mapped_column(Float)
    total_score: Mapped[float] = mapped_column(Float, index=True)

    status: Mapped[TopicStatus] = mapped_column(
        _enum(TopicStatus, "topic_status"), default=TopicStatus.CANDIDATE
    )
    provenance_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    units: Mapped[list["TopicCandidateUnit"]] = relationship(
        back_populates="topic_candidate", cascade="all, delete-orphan"
    )
    concepts: Mapped[list["TopicCandidateConcept"]] = relationship(
        back_populates="topic_candidate", cascade="all, delete-orphan"
    )


class TopicCandidateUnit(Base):
    """Units that ground one topic candidate."""

    __tablename__ = "topic_candidate_units"
    __table_args__ = (
        UniqueConstraint(
            "topic_candidate_id",
            "knowledge_unit_id",
            name="uq_topic_candidate_unit",
        ),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    topic_candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.topic_candidates.id", ondelete="CASCADE"),
        index=True,
    )
    knowledge_unit_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.knowledge_units.id", ondelete="RESTRICT"),
        index=True,
    )

    topic_candidate: Mapped["TopicCandidate"] = relationship(back_populates="units")


class TopicCandidateConcept(Base):
    """Concepts that ground one topic candidate."""

    __tablename__ = "topic_candidate_concepts"
    __table_args__ = (
        UniqueConstraint(
            "topic_candidate_id",
            "concept_id",
            name="uq_topic_candidate_concept",
        ),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    topic_candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.topic_candidates.id", ondelete="CASCADE"),
        index=True,
    )
    concept_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.external_concepts.id", ondelete="RESTRICT"),
        index=True,
    )

    topic_candidate: Mapped["TopicCandidate"] = relationship(back_populates="concepts")
    concept: Mapped["ExternalConcept"] = relationship()


class ScriptSignature(Base):
    """Semantic signature of a published script — never full prose.

    Records the shape of a finished video so the DistinctivenessPlanner can
    compare new topics against what the channel has already said.
    """

    __tablename__ = "script_signatures"
    __table_args__ = (
        UniqueConstraint("script_draft_id", name="uq_script_signatures_draft"),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    editorial_channel_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.editorial_channels.id", ondelete="CASCADE"),
        index=True,
    )
    topic_candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.topic_candidates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    script_draft_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.script_drafts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    editorial_project_id: Mapped[UUID | None] = mapped_column(nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), default="")

    question: Mapped[str] = mapped_column(Text)
    thesis: Mapped[str] = mapped_column(Text)
    angle: Mapped[str] = mapped_column(Text)
    concept_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    story_unit_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    argument_signature: Mapped[str] = mapped_column(String(1024), default="")
    hook_type: Mapped[str] = mapped_column(String(128), default="")
    ending_type: Mapped[str] = mapped_column(String(128), default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
