"""Source structure nodes and post-ingestion processing state."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
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

from app.db.base import Base, PostgresSchema
from app.knowledge.structure.domain import (
    SourceProcessingStatus,
    StructureNodeType,
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


class SourceProcessingState(Base):
    """Explicit post-ingestion lifecycle, separate from ingestion_status."""

    __tablename__ = "source_processing_states"
    __table_args__ = ({"schema": KNOWLEDGE},)

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.sources.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.source_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[SourceProcessingStatus] = mapped_column(
        _enum(SourceProcessingStatus, "source_processing_status"),
        default=SourceProcessingStatus.INGESTED,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SourceStructureNode(Base):
    """One node in the persisted hierarchical structure of a source version.

    Every node owns a contiguous transcript span between ``start_segment_id``
    and ``end_segment_id`` of the same source version.
    """

    __tablename__ = "source_structure_nodes"
    __table_args__ = (
        UniqueConstraint("source_version_id", "id"),
        ForeignKeyConstraint(
            ["source_version_id", "parent_id"],
            [
                "knowledge.source_structure_nodes.source_version_id",
                "knowledge.source_structure_nodes.id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["start_segment_id", "source_version_id"],
            [
                "knowledge.source_segments.id",
                "knowledge.source_segments.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["end_segment_id", "source_version_id"],
            [
                "knowledge.source_segments.id",
                "knowledge.source_segments.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("level >= 1", name="positive_level"),
        CheckConstraint("ordinal > 0", name="positive_ordinal"),
        Index(
            "uq_structure_node_sibling_ordinal",
            "source_version_id",
            "parent_id",
            "ordinal",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.source_versions.id", ondelete="CASCADE"),
        index=True,
    )
    parent_id: Mapped[UUID | None] = mapped_column(nullable=True)

    level: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)

    node_type: Mapped[StructureNodeType] = mapped_column(
        _enum(StructureNodeType, "structure_node_type")
    )

    title: Mapped[str] = mapped_column(String(1024))
    summary: Mapped[str] = mapped_column(Text)

    start_segment_id: Mapped[UUID] = mapped_column(nullable=False)
    end_segment_id: Mapped[UUID] = mapped_column(nullable=False)

    start_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    end_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)

    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    extraction_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.extraction_runs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
