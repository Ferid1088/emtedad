"""Persistence for semantic source trees and generated long-form content."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PostgresSchema
from app.ops.assets.models import utc_now

KNOWLEDGE = PostgresSchema.KNOWLEDGE.value
CONTENT = PostgresSchema.CONTENT.value
RETRIEVAL = PostgresSchema.RETRIEVAL.value


class SemanticStructureRun(Base):
    """Immutable derivation run that turns one transcript version into a topic tree."""

    __tablename__ = "semantic_structure_runs"
    __table_args__ = (
        UniqueConstraint(
            "source_version_id",
            "input_hash",
            "prompt_version",
            "provider",
            "model",
            name="uq_semantic_structure_run_identity",
        ),
        UniqueConstraint(
            "id",
            "source_version_id",
            name="uq_semantic_structure_run_id_source",
        ),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="valid_input_hash"),
        CheckConstraint(
            "output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'",
            name="valid_output_hash",
        ),
        Index(
            "ix_semantic_structure_runs_source_status",
            "source_version_id",
            "status",
        ),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.source_versions.id", ondelete="RESTRICT")
    )
    input_hash: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(128))
    model: Mapped[str] = mapped_column(String(128))
    configuration: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    window_count: Mapped[int] = mapped_column(Integer, default=0)
    node_count: Mapped[int] = mapped_column(Integer, default=0)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PreferredSemanticStructureRun(Base):
    """Editorial pointer to the currently preferred tree for a source version."""

    __tablename__ = "preferred_semantic_structure_runs"
    __table_args__ = (
        UniqueConstraint(
            "semantic_structure_run_id",
            name="uq_preferred_semantic_structure_run",
        ),
        ForeignKeyConstraint(
            ["semantic_structure_run_id", "source_version_id"],
            [
                f"{KNOWLEDGE}.semantic_structure_runs.id",
                f"{KNOWLEDGE}.semantic_structure_runs.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": KNOWLEDGE},
    )

    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.source_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    semantic_structure_run_id: Mapped[UUID] = mapped_column()
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class SemanticNode(Base):
    """One addressable semantic unit such as 1, 1.1, or 1.1.2."""

    __tablename__ = "semantic_nodes"
    __table_args__ = (
        UniqueConstraint(
            "semantic_structure_run_id",
            "path",
            name="uq_semantic_node_run_path",
        ),
        UniqueConstraint(
            "semantic_structure_run_id",
            "ordinal",
            name="uq_semantic_node_run_ordinal",
        ),
        CheckConstraint("depth > 0", name="positive_depth"),
        CheckConstraint("ordinal > 0", name="positive_ordinal"),
        CheckConstraint("start_sequence > 0", name="positive_start_sequence"),
        CheckConstraint("end_sequence >= start_sequence", name="valid_sequence_range"),
        CheckConstraint("end_seconds >= start_seconds", name="valid_time_range"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="valid_content_hash"),
        Index("ix_semantic_nodes_run_parent", "semantic_structure_run_id", "parent_id"),
        Index("ix_semantic_nodes_run_depth", "semantic_structure_run_id", "depth"),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    semantic_structure_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.semantic_structure_runs.id", ondelete="CASCADE")
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.semantic_nodes.id", ondelete="CASCADE"), nullable=True
    )
    path: Mapped[str] = mapped_column(String(128))
    depth: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    node_kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(1024))
    summary: Mapped[str] = mapped_column(Text)
    main_idea: Mapped[str] = mapped_column(Text)
    claims: Mapped[list[str]] = mapped_column(JSONB, default=list)
    definitions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    examples: Mapped[list[str]] = mapped_column(JSONB, default=list)
    qualifications: Mapped[list[str]] = mapped_column(JSONB, default=list)
    start_sequence: Mapped[int] = mapped_column(Integer)
    end_sequence: Mapped[int] = mapped_column(Integer)
    start_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    end_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class SemanticNodeSegment(Base):
    """Exact transcript provenance for every semantic node."""

    __tablename__ = "semantic_node_segments"
    __table_args__ = (
        UniqueConstraint(
            "semantic_node_id", "position", name="uq_semantic_node_segment_position"
        ),
        Index(
            "ix_semantic_node_segments_source_segment_id",
            "source_segment_id",
        ),
        {"schema": KNOWLEDGE},
    )

    semantic_node_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.semantic_nodes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_segment_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.source_segments.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer)


class GeneratedContentProject(Base):
    """One automated long-form content request and its frozen intermediate states."""

    __tablename__ = "generated_content_projects"
    __table_args__ = (
        CheckConstraint("target_duration_seconds >= 60", name="valid_duration"),
        CheckConstraint("target_word_count >= 100", name="valid_word_count"),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    topic: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(16))
    target_duration_seconds: Mapped[int] = mapped_column(Integer, default=1200)
    target_word_count: Mapped[int] = mapped_column(Integer, default=2500)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    chunking_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunking_runs.id", ondelete="RESTRICT")
    )
    embedding_model_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.embedding_models.id", ondelete="RESTRICT")
    )
    context_expansion_mode: Mapped[str] = mapped_column(
        String(32), default="FULL_ROOT_FAMILY"
    )
    plan: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    retrieval_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    synthesis: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    outline: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    coherence_report: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    final_script: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(255), default="operator")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class GeneratedContentSection(Base):
    """Section-scoped evidence pack and prose, keeping writer context bounded."""

    __tablename__ = "generated_content_sections"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "ordinal", name="uq_generated_content_section_ordinal"
        ),
        CheckConstraint("ordinal > 0", name="positive_ordinal"),
        CheckConstraint("target_word_count > 0", name="positive_target_word_count"),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.generated_content_projects.id", ondelete="CASCADE"),
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(1024))
    purpose: Mapped[str] = mapped_column(Text)
    transition_from_previous: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_word_count: Mapped[int] = mapped_column(Integer)
    evidence_pack: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    draft_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision_notes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
