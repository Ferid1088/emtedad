"""Relational Ayin document, passage, ontology, and review models."""

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ayin.domain import (
    CorpusZone,
    DiscourseType,
    DistinctionRelation,
    EditorialStatus,
    LanguageCode,
    OpenQuestionStatus,
    ReviewKind,
    ReviewReason,
    ReviewStatus,
)
from app.db.base import Base, PostgresSchema
from app.ops.assets.models import utc_now

CORE = PostgresSchema.CORE.value
OPS = PostgresSchema.OPS.value


def _enum(enum_type: type[Any], name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        schema=CORE,
        native_enum=True,
        values_callable=lambda members: [member.value for member in members],
    )


class CanonDocument(Base):
    """Stable intellectual identity for an Ayin work."""

    __tablename__ = "canon_documents"
    __table_args__ = (
        CheckConstraint(
            "corpus_zone IN ('AYIN_WORKING', 'AYIN_CANON')",
            name="ayin_document_zone",
        ),
        {"schema": CORE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(255), unique=True)
    document_type: Mapped[str] = mapped_column(String(64), default="ayin")
    title: Mapped[str] = mapped_column(String(512))
    original_language: Mapped[LanguageCode] = mapped_column(
        _enum(LanguageCode, "language_code")
    )
    corpus_zone: Mapped[CorpusZone] = mapped_column(_enum(CorpusZone, "corpus_zone"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class CanonVersion(Base):
    """Immutable imported or editorial version of one Ayin document."""

    __tablename__ = "canon_versions"
    __table_args__ = (
        Index(
            "uq_canon_versions_source_identity",
            "document_id",
            "source_file_hash",
            "corpus_zone",
            text("COALESCE(semantic_version, '')"),
            unique=True,
        ),
        CheckConstraint("source_file_hash ~ '^[0-9a-f]{64}$'", name="valid_hash"),
        CheckConstraint(
            "((corpus_zone = 'AYIN_WORKING' AND status IN "
            "('draft', 'review', 'deprecated')) OR "
            "(corpus_zone = 'AYIN_CANON' AND status IN "
            "('approved', 'superseded', 'deprecated')))",
            name="status_matches_zone",
        ),
        CheckConstraint(
            "(status <> 'approved') OR "
            "(semantic_version IS NOT NULL AND approved_by IS NOT NULL AND "
            "approved_at IS NOT NULL AND effective_from IS NOT NULL AND "
            "corpus_zone = 'AYIN_CANON')",
            name="approved_metadata",
        ),
        {"schema": CORE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.canon_documents.id", ondelete="RESTRICT"), index=True
    )
    supersedes_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CORE}.canon_versions.id", ondelete="RESTRICT"), nullable=True
    )
    semantic_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[EditorialStatus] = mapped_column(
        _enum(EditorialStatus, "editorial_status")
    )
    corpus_zone: Mapped[CorpusZone] = mapped_column(_enum(CorpusZone, "corpus_zone"))
    source_file_hash: Mapped[str] = mapped_column(String(64))
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    change_summary: Mapped[str] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class CanonVersionSourceAsset(Base):
    """Typed association between one version and its exact source bytes."""

    __tablename__ = "canon_version_source_assets"
    __table_args__ = (
        UniqueConstraint("canon_version_id", "source_asset_id"),
        {"schema": CORE},
    )

    canon_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.canon_versions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    source_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{OPS}.object_assets.id", ondelete="RESTRICT")
    )


class ExtractionRun(Base):
    """Reproducible transformation of one immutable source version."""

    __tablename__ = "extraction_runs"
    __table_args__ = (
        UniqueConstraint("id", "canon_version_id"),
        UniqueConstraint(
            "canon_version_id",
            "importer_version",
            "extractor_name",
            "extractor_version",
            "normalization_version",
            "segmentation_version",
            "configuration_hash",
        ),
        ForeignKeyConstraint(
            ["canon_version_id", "source_asset_id"],
            [
                f"{CORE}.canon_version_source_assets.canon_version_id",
                f"{CORE}.canon_version_source_assets.source_asset_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("page_count > 0", name="positive_page_count"),
        CheckConstraint("passage_count > 0", name="positive_passage_count"),
        CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'", name="valid_configuration_hash"
        ),
        CheckConstraint("output_hash ~ '^[0-9a-f]{64}$'", name="valid_output_hash"),
        {"schema": CORE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    canon_version_id: Mapped[UUID] = mapped_column(index=True)
    source_asset_id: Mapped[UUID]
    importer_version: Mapped[str] = mapped_column(String(64))
    extractor_name: Mapped[str] = mapped_column(String(64))
    extractor_version: Mapped[str] = mapped_column(String(128))
    normalization_version: Mapped[str] = mapped_column(String(64))
    segmentation_version: Mapped[str] = mapped_column(String(64))
    configuration: Mapped[dict[str, object]] = mapped_column(JSONB)
    configuration_hash: Mapped[str] = mapped_column(String(64))
    output_hash: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int] = mapped_column(Integer)
    passage_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class PreferredExtractionRun(Base):
    """Explicit operator-selected extraction for a source version."""

    __tablename__ = "preferred_extraction_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["extraction_run_id", "canon_version_id"],
            [f"{CORE}.extraction_runs.id", f"{CORE}.extraction_runs.canon_version_id"],
            ondelete="RESTRICT",
        ),
        {"schema": CORE},
    )

    canon_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.canon_versions.id", ondelete="CASCADE"), primary_key=True
    )
    extraction_run_id: Mapped[UUID]
    selected_by: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str] = mapped_column(Text)
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class CanonPassage(Base):
    """Addressable extracted text pinned to version, asset, and location."""

    __tablename__ = "canon_passages"
    __table_args__ = (
        UniqueConstraint("extraction_run_id", "sequence"),
        UniqueConstraint("id", "canon_version_id"),
        UniqueConstraint("id", "extraction_run_id"),
        ForeignKeyConstraint(
            ["extraction_run_id", "canon_version_id"],
            [f"{CORE}.extraction_runs.id", f"{CORE}.extraction_runs.canon_version_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["canon_version_id", "source_asset_id"],
            [
                f"{CORE}.canon_version_source_assets.canon_version_id",
                f"{CORE}.canon_version_source_assets.source_asset_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("page_number > 0", name="positive_page_number"),
        CheckConstraint("paragraph_index > 0", name="positive_paragraph_index"),
        CheckConstraint("sequence > 0", name="positive_sequence"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="valid_hash"),
        {"schema": CORE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    canon_version_id: Mapped[UUID] = mapped_column(index=True)
    extraction_run_id: Mapped[UUID] = mapped_column(index=True)
    source_asset_id: Mapped[UUID]
    sequence: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int] = mapped_column(Integer)
    printed_page_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    heading_path: Mapped[list[str]] = mapped_column(JSONB)
    paragraph_index: Mapped[int] = mapped_column(Integer)
    raw_text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    language: Mapped[LanguageCode] = mapped_column(_enum(LanguageCode, "language_code"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class AyinConcept(Base):
    """Stable concept identity whose definitions may evolve."""

    __tablename__ = "ayin_concepts"
    __table_args__ = ({"schema": CORE},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    stable_key: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[EditorialStatus] = mapped_column(
        _enum(EditorialStatus, "editorial_status")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class AyinConceptVersion(Base):
    """Source-pinned definition of one stable concept."""

    __tablename__ = "ayin_concept_versions"
    __table_args__ = (
        UniqueConstraint("concept_id", "canon_version_id", "version_number"),
        UniqueConstraint("id", "canon_version_id"),
        ForeignKeyConstraint(
            ["source_passage_id", "canon_version_id"],
            [f"{CORE}.canon_passages.id", f"{CORE}.canon_passages.canon_version_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("version_number > 0", name="positive_version"),
        {"schema": CORE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    concept_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.ayin_concepts.id", ondelete="RESTRICT"), index=True
    )
    canon_version_id: Mapped[UUID]
    source_passage_id: Mapped[UUID]
    version_number: Mapped[int] = mapped_column(Integer)
    definition: Mapped[str] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    approval_status: Mapped[EditorialStatus] = mapped_column(
        _enum(EditorialStatus, "editorial_status")
    )


class AyinPrinciple(Base):
    """Stable identity for an Ayin principle."""

    __tablename__ = "ayin_principles"
    __table_args__ = ({"schema": CORE},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    stable_key: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class AyinPrincipleVersion(Base):
    """Source-backed statement of one principle."""

    __tablename__ = "ayin_principle_versions"
    __table_args__ = (
        UniqueConstraint("principle_id", "canon_version_id", "version_number"),
        UniqueConstraint("id", "canon_version_id"),
        ForeignKeyConstraint(
            ["source_passage_id", "canon_version_id"],
            [f"{CORE}.canon_passages.id", f"{CORE}.canon_passages.canon_version_id"],
            ondelete="RESTRICT",
        ),
        {"schema": CORE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    principle_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.ayin_principles.id", ondelete="RESTRICT")
    )
    canon_version_id: Mapped[UUID]
    source_passage_id: Mapped[UUID]
    version_number: Mapped[int] = mapped_column(Integer)
    statement: Mapped[str] = mapped_column(Text)
    discourse_type: Mapped[DiscourseType] = mapped_column(
        _enum(DiscourseType, "discourse_type")
    )
    status: Mapped[EditorialStatus] = mapped_column(
        _enum(EditorialStatus, "editorial_status")
    )


class AyinDistinction(Base):
    """Stable identity and left concept for a structured distinction."""

    __tablename__ = "ayin_distinctions"
    __table_args__ = ({"schema": CORE},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    stable_key: Mapped[str] = mapped_column(String(255), unique=True)
    left_concept_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.ayin_concepts.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class AyinDistinctionVersion(Base):
    """Versioned relation with explicit source provenance."""

    __tablename__ = "ayin_distinction_versions"
    __table_args__ = (
        UniqueConstraint("distinction_id", "canon_version_id", "version_number"),
        UniqueConstraint("id", "canon_version_id"),
        ForeignKeyConstraint(
            ["source_passage_id", "canon_version_id"],
            [f"{CORE}.canon_passages.id", f"{CORE}.canon_passages.canon_version_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "num_nonnulls(right_concept_id, right_label) = 1",
            name="one_right_side",
        ),
        {"schema": CORE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    distinction_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.ayin_distinctions.id", ondelete="RESTRICT")
    )
    canon_version_id: Mapped[UUID]
    source_passage_id: Mapped[UUID]
    version_number: Mapped[int] = mapped_column(Integer)
    relation: Mapped[DistinctionRelation] = mapped_column(
        _enum(DistinctionRelation, "distinction_relation")
    )
    right_concept_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CORE}.ayin_concepts.id", ondelete="RESTRICT"), nullable=True
    )
    right_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    explanation: Mapped[str] = mapped_column(Text)
    discourse_type: Mapped[DiscourseType] = mapped_column(
        _enum(DiscourseType, "discourse_type")
    )
    status: Mapped[EditorialStatus] = mapped_column(
        _enum(EditorialStatus, "editorial_status")
    )


class AyinRelation(Base):
    """Source-pinned, version-specific relation between two Ayin concepts."""

    __tablename__ = "ayin_relations"
    __table_args__ = (
        UniqueConstraint(
            "subject_concept_id",
            "relation_type",
            "object_concept_id",
            "canon_version_id",
        ),
        ForeignKeyConstraint(
            ["source_passage_id", "canon_version_id"],
            [f"{CORE}.canon_passages.id", f"{CORE}.canon_passages.canon_version_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "subject_concept_id <> object_concept_id", name="distinct_concepts"
        ),
        {"schema": CORE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    subject_concept_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.ayin_concepts.id", ondelete="RESTRICT"), index=True
    )
    relation_type: Mapped[DistinctionRelation] = mapped_column(
        _enum(DistinctionRelation, "distinction_relation")
    )
    object_concept_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.ayin_concepts.id", ondelete="RESTRICT"), index=True
    )
    explanation: Mapped[str] = mapped_column(Text)
    discourse_type: Mapped[DiscourseType] = mapped_column(
        _enum(DiscourseType, "discourse_type")
    )
    canon_version_id: Mapped[UUID]
    source_passage_id: Mapped[UUID]
    status: Mapped[EditorialStatus] = mapped_column(
        _enum(EditorialStatus, "editorial_status")
    )


class AyinOpenQuestion(Base):
    """Stable identity for an intentionally unresolved question."""

    __tablename__ = "ayin_open_questions"
    __table_args__ = ({"schema": CORE},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    stable_key: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class AyinOpenQuestionVersion(Base):
    """Versioned wording and lifecycle of one open question."""

    __tablename__ = "ayin_open_question_versions"
    __table_args__ = (
        UniqueConstraint("open_question_id", "canon_version_id", "version_number"),
        UniqueConstraint("id", "canon_version_id"),
        ForeignKeyConstraint(
            ["source_passage_id", "canon_version_id"],
            [f"{CORE}.canon_passages.id", f"{CORE}.canon_passages.canon_version_id"],
            ondelete="RESTRICT",
        ),
        {"schema": CORE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    open_question_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.ayin_open_questions.id", ondelete="RESTRICT")
    )
    canon_version_id: Mapped[UUID]
    source_passage_id: Mapped[UUID]
    version_number: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text)
    discourse_type: Mapped[DiscourseType] = mapped_column(
        _enum(DiscourseType, "discourse_type")
    )
    status: Mapped[OpenQuestionStatus] = mapped_column(
        _enum(OpenQuestionStatus, "open_question_status")
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AyinReviewItem(Base):
    """Typed review issue attached to one imported Ayin version."""

    __tablename__ = "ayin_review_items"
    __table_args__ = (
        UniqueConstraint("id", "extraction_run_id"),
        CheckConstraint(
            "(status = 'open' AND reviewed_at IS NULL) OR "
            "(status IN ('resolved', 'dismissed') AND reviewed_at IS NOT NULL)",
            name="review_completion_metadata",
        ),
        ForeignKeyConstraint(
            ["extraction_run_id", "canon_version_id"],
            [f"{CORE}.extraction_runs.id", f"{CORE}.extraction_runs.canon_version_id"],
            ondelete="RESTRICT",
        ),
        {"schema": CORE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    canon_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.canon_versions.id", ondelete="RESTRICT"), index=True
    )
    extraction_run_id: Mapped[UUID] = mapped_column(index=True)
    kind: Mapped[ReviewKind] = mapped_column(_enum(ReviewKind, "ayin_review_kind"))
    reason_for_review: Mapped[ReviewReason] = mapped_column(
        _enum(ReviewReason, "ayin_review_reason")
    )
    status: Mapped[ReviewStatus] = mapped_column(
        _enum(ReviewStatus, "ayin_review_status")
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class AyinPassageReview(Base):
    """Foreign-keyed passage target for an Ayin review item."""

    __tablename__ = "ayin_passage_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["review_item_id", "extraction_run_id"],
            [
                f"{CORE}.ayin_review_items.id",
                f"{CORE}.ayin_review_items.extraction_run_id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["passage_id", "extraction_run_id"],
            [f"{CORE}.canon_passages.id", f"{CORE}.canon_passages.extraction_run_id"],
            ondelete="RESTRICT",
        ),
        {"schema": CORE},
    )

    review_item_id: Mapped[UUID] = mapped_column(
        primary_key=True,
    )
    extraction_run_id: Mapped[UUID]
    passage_id: Mapped[UUID] = mapped_column(index=True)
