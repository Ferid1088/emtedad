"""Typed content strategy graph and publication package records."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.content_strategy.domain import (
    ContentStatus,
    LectureAngle,
    PublicationPackageStatus,
    RepetitionDecision,
    TopicOrigin,
    TopicRelationType,
    TopicWorkspaceStatus,
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
    primary_concept_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
    analysis_json: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    workspace_status: Mapped[TopicWorkspaceStatus] = mapped_column(
        String(32), default=TopicWorkspaceStatus.NEW
    )
    suggestion_batch_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.topic_suggestion_batches.id", ondelete="SET NULL"),
        nullable=True,
    )


class TopicSuggestionBatch(Base):
    """One owner-triggered, reproducible dynamic-topic discovery run."""

    __tablename__ = "topic_suggestion_batches"
    __table_args__ = {"schema": CONTENT}
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    requested_count: Mapped[int] = mapped_column(Integer)
    owner_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    generator: Mapped[str] = mapped_column(String(128), default="deterministic-v1")
    prompt_version: Mapped[str] = mapped_column(
        String(64), default="topic-discovery-v2"
    )
    corpus_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class TopicStrategy(Base):
    """Versioned fixed Emtedad topic tree, separate from dynamic topics."""

    __tablename__ = "topic_strategies"
    __table_args__ = (UniqueConstraint("version_number"), {"schema": CONTENT})
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    version_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    source_hash: Mapped[str] = mapped_column(String(64))
    grounding: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TopicStrategyNode(Base):
    """Root, branch, or fixed leaf in one strategy version."""

    __tablename__ = "topic_strategy_nodes"
    __table_args__ = (
        UniqueConstraint("strategy_id", "stable_key"),
        {"schema": CONTENT},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    strategy_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.topic_strategies.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.topic_strategy_nodes.id", ondelete="CASCADE"),
        nullable=True,
    )
    node_type: Mapped[str] = mapped_column(String(16))
    stable_key: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    human_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer)
    grounding: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    generation_count: Mapped[int] = mapped_column(Integer, default=0)
    last_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class EditorialProject(Base):
    """Production workspace shell; research remains an explicit next action."""

    __tablename__ = "editorial_projects"
    __table_args__ = {"schema": CONTENT}
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    strategy_node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.topic_strategy_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    strategy_topic_snapshot: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    content_topic_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.content_topics.id", ondelete="RESTRICT"), nullable=True
    )
    research_project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.research_projects.id", ondelete="RESTRICT"),
        nullable=True,
    )
    research_package_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="RESTRICT"),
        nullable=True,
    )
    semantic_master_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_master_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(512))
    human_question: Mapped[str] = mapped_column(Text)
    owner_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_duration_minutes: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="RESEARCH_PENDING")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class TopicUseHistory(Base):
    """Immutable use record; a fixed topic remains selectable after use."""

    __tablename__ = "topic_use_history"
    __table_args__ = {"schema": CONTENT}
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    strategy_node_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.topic_strategy_nodes.id", ondelete="RESTRICT")
    )
    editorial_project_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.editorial_projects.id", ondelete="RESTRICT")
    )
    owner_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_duration_minutes: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class PersianDraft(Base):
    """Versioned Persian authoring artifact derived from one Semantic Master."""

    __tablename__ = "persian_drafts"
    __table_args__ = {"schema": CONTENT}
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    editorial_project_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.editorial_projects.id", ondelete="RESTRICT")
    )
    parent_draft_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.persian_drafts.id", ondelete="RESTRICT"), nullable=True
    )
    semantic_master_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_master_versions.id", ondelete="RESTRICT")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    variant_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="PROPOSED")
    owner_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_duration_minutes: Mapped[int] = mapped_column(Integer)
    target_word_count_min: Mapped[int] = mapped_column(Integer)
    target_word_count_max: Mapped[int] = mapped_column(Integer)
    actual_word_count: Mapped[int] = mapped_column(Integer)
    estimated_duration_seconds: Mapped[int] = mapped_column(Integer)
    speaking_rate_profile: Mapped[str] = mapped_column(
        String(64), default="fa-spoken-v1"
    )
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class PersianReviewFinding(Base):
    __tablename__ = "persian_review_findings"
    __table_args__ = {"schema": CONTENT}
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    draft_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.persian_drafts.id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    blocking: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class EditorialLanguageTrack(Base):
    """One versioned FA/DE/EN/AR text track sourced from approved Persian."""

    __tablename__ = "editorial_language_tracks"
    __table_args__ = {"schema": CONTENT}
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    editorial_project_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.editorial_projects.id", ondelete="RESTRICT")
    )
    source_persian_draft_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.persian_drafts.id", ondelete="RESTRICT")
    )
    semantic_master_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_master_versions.id", ondelete="RESTRICT")
    )
    language: Mapped[str] = mapped_column(String(8))
    version_number: Mapped[int] = mapped_column(Integer)
    display_text: Mapped[str] = mapped_column(Text)
    voice_ready_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provider-specific text is kept separate from publication and
    # pronunciation text.  It may contain ElevenLabs performance tags, but
    # no provider is called by this application in Phase 12.
    elevenlabs_performance_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="TRANSLATED")
    semantic_validation_status: Mapped[str] = mapped_column(
        String(32), default="NOT_VALIDATED"
    )
    actual_word_count: Mapped[int] = mapped_column(Integer)
    estimated_duration_seconds: Mapped[int] = mapped_column(Integer)
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


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
