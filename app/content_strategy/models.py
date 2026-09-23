"""Typed content strategy graph and publication package records."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.content_strategy.domain import (
    ContentStatus,
    LectureAngle,
    PublicationPackageStatus,
    RepetitionDecision,
    TopicOrigin,
    TopicRelationType,
)
from app.db.base import Base, PostgresSchema
from app.ops.assets.models import utc_now

CONTENT = PostgresSchema.CONTENT.value


def _enum(enum_type: type[object], name: str) -> ENUM:
    return ENUM(
        enum_type,
        name=name,
        schema=CONTENT,
        values_callable=lambda members: [member.value for member in members],
    )


class ContentSeries(Base):
    __tablename__ = "content_series"
    __table_args__ = {"schema": CONTENT}
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    stable_key: Mapped[str] = mapped_column(String(255), unique=True)
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[ContentStatus] = mapped_column(
        _enum(ContentStatus, "content_status"), default=ContentStatus.PLANNED
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ContentPathway(Base):
    __tablename__ = "content_pathways"
    __table_args__ = {"schema": CONTENT}
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    series_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.content_series.id", ondelete="RESTRICT")
    )
    stable_key: Mapped[str] = mapped_column(String(255), unique=True)
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer)
    status: Mapped[ContentStatus] = mapped_column(
        _enum(ContentStatus, "content_status"), default=ContentStatus.PLANNED
    )


class ContentTopic(Base):
    __tablename__ = "content_topics"
    __table_args__ = {"schema": CONTENT}
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    stable_key: Mapped[str] = mapped_column(String(255), unique=True)
    title: Mapped[str] = mapped_column(String(512))
    human_question: Mapped[str] = mapped_column(Text)
    primary_concept_key: Mapped[str] = mapped_column(String(255))
    life_domain: Mapped[str] = mapped_column(String(64))
    lecture_angle: Mapped[LectureAngle] = mapped_column(
        _enum(LectureAngle, "lecture_angle")
    )
    status: Mapped[ContentStatus] = mapped_column(
        _enum(ContentStatus, "content_status"), default=ContentStatus.PLANNED
    )
    origin: Mapped[TopicOrigin] = mapped_column(
        _enum(TopicOrigin, "topic_origin"), default=TopicOrigin.USER_CREATED
    )
    semantic_hash: Mapped[str] = mapped_column(String(64))


class ContentTopicRelation(Base):
    __tablename__ = "content_topic_relations"
    __table_args__ = {"schema": CONTENT}
    from_topic_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.content_topics.id", ondelete="CASCADE"), primary_key=True
    )
    to_topic_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.content_topics.id", ondelete="CASCADE"), primary_key=True
    )
    relation_type: Mapped[TopicRelationType] = mapped_column(
        _enum(TopicRelationType, "topic_relation_type")
    )


class ContentLectureLink(Base):
    __tablename__ = "content_lecture_links"
    __table_args__ = {"schema": CONTENT}
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    lecture_master_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_master_versions.id", ondelete="RESTRICT"),
        unique=True,
    )
    series_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.content_series.id", ondelete="RESTRICT")
    )
    pathway_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.content_pathways.id", ondelete="RESTRICT"), nullable=True
    )
    topic_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.content_topics.id", ondelete="RESTRICT")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    status: Mapped[ContentStatus] = mapped_column(
        _enum(ContentStatus, "content_status"), default=ContentStatus.READY
    )


class ContentCoverage(Base):
    __tablename__ = "content_coverage"
    __table_args__ = {"schema": CONTENT}
    lecture_master_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_master_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    concept_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    distinction_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    required: Mapped[bool] = mapped_column(Boolean, default=True)


class ContentRepetitionAssessment(Base):
    __tablename__ = "content_repetition_assessments"
    __table_args__ = {"schema": CONTENT}
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    lecture_master_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_master_versions.id", ondelete="RESTRICT")
    )
    compared_lecture_master_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_master_versions.id", ondelete="RESTRICT")
    )
    overlap_score: Mapped[float] = mapped_column()
    reasons: Mapped[list[str]] = mapped_column(JSONB, default=list)
    decision: Mapped[RepetitionDecision] = mapped_column(
        _enum(RepetitionDecision, "repetition_decision")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class PublicationPackageRecord(Base):
    __tablename__ = "publication_package_records"
    __table_args__ = {"schema": CONTENT}
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    lecture_master_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_master_versions.id", ondelete="RESTRICT")
    )
    package_version: Mapped[int] = mapped_column(Integer)
    root_path: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[PublicationPackageStatus] = mapped_column(
        _enum(PublicationPackageStatus, "publication_package_status")
    )
    manifest: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
