"""Relational persistence for versioned speech structures."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PostgresSchema
from app.ops.assets.models import utc_now

KNOWLEDGE = PostgresSchema.KNOWLEDGE.value
JSON_TYPE = JSONB


class SpeechStructure(Base):
    __tablename__ = "speech_structures"
    __table_args__ = (
        UniqueConstraint("source_id", "version"),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.sources.id", ondelete="RESTRICT"), index=True
    )
    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.source_versions.id", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    language: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(1024))
    input_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SpeechStructureRun(Base):
    __tablename__ = "speech_structure_runs"
    __table_args__ = ({"schema": KNOWLEDGE},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    speech_structure_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.speech_structures.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(128))
    model: Mapped[str] = mapped_column(String(256))
    prompt_version: Mapped[str] = mapped_column(String(128))
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="PROCESSING")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class SpeechSection(Base):
    __tablename__ = "speech_sections"
    __table_args__ = (
        Index("ix_speech_sections_parent_id", "parent_id"),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    speech_structure_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.speech_structures.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.speech_sections.id", ondelete="CASCADE"), nullable=True
    )
    root_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.speech_sections.id", ondelete="CASCADE"), index=True
    )
    section_number: Mapped[str] = mapped_column(String(64))
    level: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(1024))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_role: Mapped[str] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SpeechSectionSegment(Base):
    __tablename__ = "speech_section_segments"
    __table_args__ = (
        UniqueConstraint("section_id", "source_segment_id", "relation_type"),
        UniqueConstraint("section_id", "sequence"),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    section_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.speech_sections.id", ondelete="CASCADE"), index=True
    )
    source_segment_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.source_segments.id", ondelete="RESTRICT"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    relation_type: Mapped[str] = mapped_column(String(32), default="PRIMARY")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
