"""Persisted Knowledge Units anchored to structure nodes and segment spans."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PostgresSchema
from app.knowledge.units.domain import (
    ClaimType,
    EvidenceLevel,
    KnowledgeUnitType,
)
from app.ops.assets.models import utc_now

KNOWLEDGE = PostgresSchema.KNOWLEDGE.value


def _enum(enum_type: type[Any], name: str) -> ENUM:
    return ENUM(
        enum_type,
        name=name,
        schema=KNOWLEDGE,
        values_callable=lambda members: [member.value for member in members],
    )


class KnowledgeUnit(Base):
    """One atomic unit of source-derived knowledge.

    ``full_text`` is reconstructed deterministically from the ordered source
    segments between ``start_segment_id`` and ``end_segment_id``; the LLM
    summary is never authoritative.
    """

    __tablename__ = "knowledge_units"
    __table_args__ = (
        UniqueConstraint(
            "source_version_id",
            "unit_type",
            "content_hash",
            name="uq_knowledge_unit_dedup",
        ),
        ForeignKeyConstraint(
            ["structure_node_id", "source_version_id"],
            [
                f"{KNOWLEDGE}.source_structure_nodes.id",
                f"{KNOWLEDGE}.source_structure_nodes.source_version_id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["start_segment_id", "source_version_id"],
            [
                f"{KNOWLEDGE}.source_segments.id",
                f"{KNOWLEDGE}.source_segments.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["end_segment_id", "source_version_id"],
            [
                f"{KNOWLEDGE}.source_segments.id",
                f"{KNOWLEDGE}.source_segments.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="valid_content_hash"),
        Index(
            "ix_knowledge_units_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.source_versions.id", ondelete="CASCADE"),
        index=True,
    )
    structure_node_id: Mapped[UUID] = mapped_column(nullable=False)

    unit_type: Mapped[KnowledgeUnitType] = mapped_column(
        _enum(KnowledgeUnitType, "knowledge_unit_type")
    )

    title: Mapped[str] = mapped_column(String(1024))
    summary: Mapped[str] = mapped_column(Text)
    full_text: Mapped[str] = mapped_column(Text)

    start_segment_id: Mapped[UUID] = mapped_column(nullable=False)
    end_segment_id: Mapped[UUID] = mapped_column(nullable=False)

    atomic: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_level: Mapped[EvidenceLevel] = mapped_column(
        _enum(EvidenceLevel, "evidence_level"),
        default=EvidenceLevel.NONE,
    )
    claim_type: Mapped[ClaimType] = mapped_column(
        _enum(ClaimType, "claim_type"),
        default=ClaimType.UNKNOWN,
    )

    content_hash: Mapped[str] = mapped_column(String(64))
    extraction_version: Mapped[str] = mapped_column(String(128))
    search_vector: Mapped[object] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple', coalesce(title, '') || ' ' || "
            "coalesce(summary, '') || ' ' || coalesce(full_text, ''))",
            persisted=True,
        ),
    )
    extraction_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.extraction_runs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class KnowledgeUnitConcept(Base):
    """Typed association between a Knowledge Unit and an ExternalConcept."""

    __tablename__ = "knowledge_unit_concepts"
    __table_args__ = (
        UniqueConstraint("knowledge_unit_id", "concept_id", "relation_role"),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_unit_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.knowledge_units.id", ondelete="CASCADE"),
        index=True,
    )
    concept_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.external_concepts.id", ondelete="RESTRICT"),
        index=True,
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    relation_role: Mapped[str] = mapped_column(String(32), default="MENTIONED")


class ConceptRelationType(StrEnum):
    RELATED_TO = "RELATED_TO"
    PART_OF = "PART_OF"
    CAUSES = "CAUSES"
    MAY_CAUSE = "MAY_CAUSE"
    CONTRASTS = "CONTRASTS"
    SUPPORTS = "SUPPORTS"
    CHALLENGES = "CHALLENGES"
    EXAMPLE_OF = "EXAMPLE_OF"


class ConceptRelationship(Base):
    """Directed relation between two concepts in the global concept graph."""

    __tablename__ = "concept_relationships"
    __table_args__ = (
        UniqueConstraint("from_concept_id", "to_concept_id", "relation_type"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="valid_confidence"),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    from_concept_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.external_concepts.id", ondelete="CASCADE"),
        index=True,
    )
    to_concept_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.external_concepts.id", ondelete="CASCADE"),
        index=True,
    )
    relation_type: Mapped[ConceptRelationType] = mapped_column(
        _enum(ConceptRelationType, "concept_relation_type")
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    provenance_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
