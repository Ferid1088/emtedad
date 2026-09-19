"""Typed relational model for external knowledge and immutable provenance."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ayin.domain import CorpusZone
from app.db.base import Base, PostgresSchema
from app.knowledge.domain import (
    EntityType,
    EvidenceRelation,
    IdentifierScheme,
    IngestionStatus,
    KnowledgeReviewStatus,
    LabelKind,
    MediaStatus,
    MediaType,
    ResolutionProvider,
    ResolutionStatus,
    ReviewReason,
    RunStatus,
    SourceType,
    VerificationStatus,
    WindowStatus,
    WorkType,
)
from app.ops.assets.models import utc_now

KNOWLEDGE = PostgresSchema.KNOWLEDGE.value
OPS = PostgresSchema.OPS.value
CORE = PostgresSchema.CORE.value


def _enum(enum_type: type[Any], name: str) -> ENUM:
    return ENUM(
        enum_type,
        name=name,
        schema=KNOWLEDGE,
        values_callable=lambda members: [member.value for member in members],
    )


def _core_enum(enum_type: type[Any], name: str) -> ENUM:
    return ENUM(
        enum_type,
        name=name,
        schema=CORE,
        create_type=False,
        values_callable=lambda members: [member.value for member in members],
    )


class Creator(Base):
    __tablename__ = "creators"
    __table_args__ = ({"schema": KNOWLEDGE},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    canonical_name: Mapped[str] = mapped_column(String(512))
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="active")
    person_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.people.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint("platform", "external_id"),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    platform: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(512))
    canonical_url: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ChannelCreator(Base):
    __tablename__ = "channel_creators"
    __table_args__ = ({"schema": KNOWLEDGE},)

    channel_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.channels.id", ondelete="CASCADE"), primary_key=True
    )
    creator_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.creators.id", ondelete="RESTRICT"), primary_key=True
    )
    attribution_role: Mapped[str] = mapped_column(String(64), default="creator")


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("platform", "external_id"),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_type: Mapped[SourceType] = mapped_column(_enum(SourceType, "source_type"))
    platform: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(255))
    channel_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.channels.id", ondelete="RESTRICT"), nullable=True
    )
    canonical_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(1024))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(16))
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    ingestion_status: Mapped[IngestionStatus] = mapped_column(
        _enum(IngestionStatus, "ingestion_status")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class SourceVersion(Base):
    __tablename__ = "source_versions"
    __table_args__ = (
        UniqueConstraint("source_id", "content_hash"),
        UniqueConstraint("id", "source_id"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="valid_content_hash"),
        CheckConstraint(
            "transcript_hash ~ '^[0-9a-f]{64}$'", name="valid_transcript_hash"
        ),
        CheckConstraint(
            "corpus_zone = 'EXTERNAL_PRIMARY'", name="external_primary_only"
        ),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.sources.id", ondelete="RESTRICT"), index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    transcript_hash: Mapped[str] = mapped_column(String(64))
    corpus_zone: Mapped[CorpusZone] = mapped_column(
        _core_enum(CorpusZone, "corpus_zone"), default=CorpusZone.EXTERNAL_PRIMARY
    )
    provider_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    acquisition_tool: Mapped[str] = mapped_column(String(128))
    acquisition_version: Mapped[str] = mapped_column(String(128))
    normalization_version: Mapped[str] = mapped_column(String(128))
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class SourceSegment(Base):
    __tablename__ = "source_segments"
    __table_args__ = (
        UniqueConstraint("source_version_id", "sequence"),
        UniqueConstraint("id", "source_version_id"),
        CheckConstraint("sequence > 0", name="positive_sequence"),
        CheckConstraint("start_seconds >= 0", name="nonnegative_start"),
        CheckConstraint("end_seconds > start_seconds", name="valid_interval"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="valid_content_hash"),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.source_versions.id", ondelete="RESTRICT"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    start_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    end_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    raw_text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(16))
    speaker_person_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.people.id", ondelete="RESTRICT"), nullable=True
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        UniqueConstraint(
            "source_version_id",
            "task",
            "provider",
            "model",
            "prompt_version",
            "configuration_hash",
        ),
        UniqueConstraint("id", "source_version_id"),
        CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'", name="valid_configuration_hash"
        ),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.source_versions.id", ondelete="RESTRICT"), index=True
    )
    task: Mapped[str] = mapped_column(String(128))
    provider: Mapped[str] = mapped_column(String(128))
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64))
    configuration: Mapped[dict[str, object]] = mapped_column(JSONB)
    configuration_hash: Mapped[str] = mapped_column(String(64))
    window_size: Mapped[int] = mapped_column(Integer)
    overlap: Mapped[int] = mapped_column(Integer)
    status: Mapped[RunStatus] = mapped_column(_enum(RunStatus, "run_status"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ExtractionWindow(Base):
    __tablename__ = "extraction_windows"
    __table_args__ = (
        UniqueConstraint("source_version_id", "sequence", "window_size", "overlap"),
        UniqueConstraint("id", "source_version_id"),
        CheckConstraint("sequence > 0", name="positive_sequence"),
        CheckConstraint("window_size > 0", name="positive_window_size"),
        CheckConstraint("overlap >= 0 AND overlap < window_size", name="valid_overlap"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="valid_content_hash"),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.source_versions.id", ondelete="RESTRICT"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    window_size: Mapped[int] = mapped_column(Integer)
    overlap: Mapped[int] = mapped_column(Integer)
    start_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    end_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    language: Mapped[str] = mapped_column(String(16))
    content_hash: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)


class ExtractionWindowSegment(Base):
    __tablename__ = "extraction_window_segments"
    __table_args__ = (
        UniqueConstraint("window_id", "sequence_in_window"),
        ForeignKeyConstraint(
            ["window_id", "source_version_id"],
            [
                f"{KNOWLEDGE}.extraction_windows.id",
                f"{KNOWLEDGE}.extraction_windows.source_version_id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_segment_id", "source_version_id"],
            [
                f"{KNOWLEDGE}.source_segments.id",
                f"{KNOWLEDGE}.source_segments.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": KNOWLEDGE},
    )

    window_id: Mapped[UUID] = mapped_column(primary_key=True)
    source_segment_id: Mapped[UUID] = mapped_column(primary_key=True)
    source_version_id: Mapped[UUID]
    sequence_in_window: Mapped[int] = mapped_column(Integer)


class WindowResult(Base):
    __tablename__ = "window_results"
    __table_args__ = (
        UniqueConstraint("extraction_run_id", "window_id"),
        CheckConstraint("attempt_count > 0", name="positive_attempt_count"),
        CheckConstraint(
            "output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'",
            name="valid_output_hash",
        ),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    extraction_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.extraction_runs.id", ondelete="CASCADE"), index=True
    )
    window_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.extraction_windows.id", ondelete="RESTRICT")
    )
    status: Mapped[WindowStatus] = mapped_column(_enum(WindowStatus, "window_status"))
    structured_output: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    diagnostics: Mapped[str | None] = mapped_column(Text, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class Person(Base):
    __tablename__ = "people"
    __table_args__ = ({"schema": KNOWLEDGE},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    canonical_name: Mapped[str] = mapped_column(String(512))
    normalized_name: Mapped[str] = mapped_column(String(512), index=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = ({"schema": KNOWLEDGE},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    canonical_name: Mapped[str] = mapped_column(String(512))
    normalized_name: Mapped[str] = mapped_column(String(512), index=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class Work(Base):
    __tablename__ = "works"
    __table_args__ = ({"schema": KNOWLEDGE},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    work_type: Mapped[WorkType] = mapped_column(_enum(WorkType, "work_type"))
    canonical_title: Mapped[str] = mapped_column(String(1024))
    normalized_title: Mapped[str] = mapped_column(String(1024), index=True)
    original_title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(512), nullable=True)
    journal: Mapped[str | None] = mapped_column(String(512), nullable=True)
    volume: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issue: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pages: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class WorkAuthor(Base):
    __tablename__ = "work_authors"
    __table_args__ = (
        UniqueConstraint("work_id", "position"),
        {"schema": KNOWLEDGE},
    )

    work_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.works.id", ondelete="CASCADE"), primary_key=True
    )
    person_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.people.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)


class ExternalConcept(Base):
    __tablename__ = "external_concepts"
    __table_args__ = ({"schema": KNOWLEDGE},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    canonical_name: Mapped[str] = mapped_column(String(512))
    normalized_name: Mapped[str] = mapped_column(String(512), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class EntityLabel(Base):
    __tablename__ = "entity_labels"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(person_id, work_id, organization_id, concept_id) = 1",
            name="one_typed_entity",
        ),
        UniqueConstraint("normalized_label", "language", "person_id"),
        UniqueConstraint("normalized_label", "language", "work_id"),
        UniqueConstraint("normalized_label", "language", "organization_id"),
        UniqueConstraint("normalized_label", "language", "concept_id"),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    person_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.people.id", ondelete="CASCADE"), nullable=True
    )
    work_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.works.id", ondelete="CASCADE"), nullable=True
    )
    organization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.organizations.id", ondelete="CASCADE"), nullable=True
    )
    concept_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.external_concepts.id", ondelete="CASCADE"),
        nullable=True,
    )
    label: Mapped[str] = mapped_column(String(1024))
    normalized_label: Mapped[str] = mapped_column(String(1024))
    language: Mapped[str] = mapped_column(String(16))
    kind: Mapped[LabelKind] = mapped_column(_enum(LabelKind, "label_kind"))


class ExternalIdentifier(Base):
    __tablename__ = "external_identifiers"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(person_id, work_id, organization_id, concept_id) = 1",
            name="one_typed_entity",
        ),
        UniqueConstraint("scheme", "normalized_value"),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    scheme: Mapped[IdentifierScheme] = mapped_column(
        _enum(IdentifierScheme, "identifier_scheme")
    )
    value: Mapped[str] = mapped_column(String(512))
    normalized_value: Mapped[str] = mapped_column(String(512))
    person_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.people.id", ondelete="CASCADE"), nullable=True
    )
    work_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.works.id", ondelete="CASCADE"), nullable=True
    )
    organization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.organizations.id", ondelete="CASCADE"), nullable=True
    )
    concept_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.external_concepts.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class Mention(Base):
    __tablename__ = "mentions"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(person_id, work_id, organization_id, concept_id) <= 1",
            name="at_most_one_resolution",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="valid_confidence"),
        ForeignKeyConstraint(
            ["source_segment_id", "source_version_id"],
            [
                f"{KNOWLEDGE}.source_segments.id",
                f"{KNOWLEDGE}.source_segments.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "extraction_run_id", "source_segment_id", "entity_type", "surface_text"
        ),
        ForeignKeyConstraint(
            ["extraction_run_id", "source_version_id"],
            [
                f"{KNOWLEDGE}.extraction_runs.id",
                f"{KNOWLEDGE}.extraction_runs.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID]
    source_segment_id: Mapped[UUID]
    extraction_run_id: Mapped[UUID]
    entity_type: Mapped[EntityType] = mapped_column(_enum(EntityType, "entity_type"))
    surface_text: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    resolution_status: Mapped[ResolutionStatus] = mapped_column(
        _enum(ResolutionStatus, "resolution_status")
    )
    person_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.people.id", ondelete="RESTRICT"), nullable=True
    )
    work_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.works.id", ondelete="RESTRICT"), nullable=True
    )
    organization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.organizations.id", ondelete="RESTRICT"), nullable=True
    )
    concept_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.external_concepts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ResolutionCandidate(Base):
    __tablename__ = "resolution_candidates"
    __table_args__ = (
        UniqueConstraint("mention_id", "provider", "candidate_key"),
        CheckConstraint("score >= 0 AND score <= 100", name="valid_score"),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    mention_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.mentions.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[ResolutionProvider] = mapped_column(
        _enum(ResolutionProvider, "resolution_provider")
    )
    candidate_key: Mapped[str] = mapped_column(String(512))
    candidate_type: Mapped[EntityType] = mapped_column(_enum(EntityType, "entity_type"))
    candidate_name: Mapped[str] = mapped_column(String(1024))
    candidate_identifiers: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    candidate_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[float] = mapped_column(Float)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    status: Mapped[ResolutionStatus] = mapped_column(
        _enum(ResolutionStatus, "resolution_status")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ExternalClaim(Base):
    __tablename__ = "external_claims"
    __table_args__ = (
        CheckConstraint(
            "extraction_confidence >= 0 AND extraction_confidence <= 1",
            name="valid_confidence",
        ),
        ForeignKeyConstraint(
            ["source_segment_id", "source_version_id"],
            [
                f"{KNOWLEDGE}.source_segments.id",
                f"{KNOWLEDGE}.source_segments.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "extraction_run_id", "source_segment_id", "normalized_claim_text"
        ),
        ForeignKeyConstraint(
            ["extraction_run_id", "source_version_id"],
            [
                f"{KNOWLEDGE}.extraction_runs.id",
                f"{KNOWLEDGE}.extraction_runs.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID]
    source_segment_id: Mapped[UUID]
    extraction_run_id: Mapped[UUID]
    claimant_person_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.people.id", ondelete="RESTRICT"), nullable=True
    )
    claim_text: Mapped[str] = mapped_column(Text)
    normalized_claim_text: Mapped[str] = mapped_column(Text)
    claim_domain: Mapped[str] = mapped_column(String(255))
    claim_type: Mapped[str] = mapped_column(String(128))
    extraction_confidence: Mapped[float] = mapped_column(Float)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        _enum(VerificationStatus, "verification_status")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(work_id, source_id, source_segment_id) = 1",
            name="one_typed_evidence_target",
        ),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.external_claims.id", ondelete="CASCADE"), index=True
    )
    relation: Mapped[EvidenceRelation] = mapped_column(
        _enum(EvidenceRelation, "evidence_relation")
    )
    work_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.works.id", ondelete="RESTRICT"), nullable=True
    )
    source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.sources.id", ondelete="RESTRICT"), nullable=True
    )
    source_segment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.source_segments.id", ondelete="RESTRICT"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class SourceQuality(Base):
    __tablename__ = "source_quality"
    __table_args__ = ({"schema": KNOWLEDGE},)

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.sources.id", ondelete="CASCADE"), primary_key=True
    )
    publication_type: Mapped[str] = mapped_column(String(128))
    peer_reviewed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    primary_or_secondary: Mapped[str] = mapped_column(String(32))
    retraction_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieval_weight: Mapped[float] = mapped_column(Float, default=1.0)


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        UniqueConstraint("object_asset_id", "media_type"),
        UniqueConstraint("source_url", "media_type"),
        CheckConstraint(
            "status <> 'available' OR object_asset_id IS NOT NULL",
            name="available_requires_object",
        ),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    object_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{OPS}.object_assets.id", ondelete="RESTRICT"), nullable=True
    )
    media_type: Mapped[MediaType] = mapped_column(_enum(MediaType, "media_type"))
    source_url: Mapped[str] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    license: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    rights_status: Mapped[str] = mapped_column(String(64), default="unknown")
    status: Mapped[MediaStatus] = mapped_column(_enum(MediaStatus, "media_status"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class SourceMediaAsset(Base):
    __tablename__ = "source_media_assets"
    __table_args__ = ({"schema": KNOWLEDGE},)

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.sources.id", ondelete="CASCADE"), primary_key=True
    )
    media_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.media_assets.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class WorkMediaAsset(Base):
    __tablename__ = "work_media_assets"
    __table_args__ = ({"schema": KNOWLEDGE},)

    work_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.works.id", ondelete="CASCADE"), primary_key=True
    )
    media_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.media_assets.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class PersonMediaAsset(Base):
    __tablename__ = "person_media_assets"
    __table_args__ = ({"schema": KNOWLEDGE},)

    person_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.people.id", ondelete="CASCADE"), primary_key=True
    )
    media_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.media_assets.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class ReviewFlag(Base):
    __tablename__ = "review_flags"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(mention_id, window_result_id, resolution_candidate_id, "
            "media_asset_id) <= 1",
            name="at_most_one_specific_target",
        ),
        CheckConstraint(
            "(status IN ('open', 'in_review') AND reviewed_at IS NULL) OR "
            "(status IN ('resolved', 'rejected') AND reviewed_at IS NOT NULL)",
            name="review_completion_metadata",
        ),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.source_versions.id", ondelete="RESTRICT"), index=True
    )
    reason: Mapped[ReviewReason] = mapped_column(_enum(ReviewReason, "review_reason"))
    status: Mapped[KnowledgeReviewStatus] = mapped_column(
        _enum(KnowledgeReviewStatus, "knowledge_review_status")
    )
    message: Mapped[str] = mapped_column(Text)
    mention_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.mentions.id", ondelete="CASCADE"), nullable=True
    )
    window_result_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.window_results.id", ondelete="CASCADE"), nullable=True
    )
    resolution_candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.resolution_candidates.id", ondelete="CASCADE"),
        nullable=True,
    )
    media_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.media_assets.id", ondelete="CASCADE"), nullable=True
    )
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


Index(
    "ix_knowledge_window_results_retry",
    WindowResult.extraction_run_id,
    WindowResult.status,
)
Index(
    "ix_knowledge_mentions_resolution",
    Mention.resolution_status,
    Mention.entity_type,
)
