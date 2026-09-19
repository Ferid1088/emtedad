"""Relational, versioned Manasek models with typed provenance."""

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ayin.domain import (
    CorpusZone,
    EditorialStatus,
    LanguageCode,
    ReviewStatus,
)
from app.db.base import Base, PostgresSchema
from app.ops.assets.models import utc_now
from app.ritual.domain import (
    CueType,
    GateKey,
    RitualFamilyType,
    RitualMode,
    RitualPieceType,
    RitualRelationType,
    RitualReviewReason,
    SafetyCategory,
    SafetySeverity,
)

CORE = PostgresSchema.CORE.value
OPS = PostgresSchema.OPS.value
RITUAL = PostgresSchema.RITUAL.value


def _enum(enum_type: type[Any], name: str) -> ENUM:
    return ENUM(
        enum_type,
        name=name,
        schema=RITUAL,
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


class RitualDocument(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "corpus_zone IN ('MANASEK_WORKING', 'MANASEK_CANON')",
            name="manasek_document_zone",
        ),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(255), unique=True)
    title: Mapped[str] = mapped_column(String(512))
    original_language: Mapped[LanguageCode] = mapped_column(
        _core_enum(LanguageCode, "language_code")
    )
    corpus_zone: Mapped[CorpusZone] = mapped_column(
        _core_enum(CorpusZone, "corpus_zone")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class RitualSourceVersion(Base):
    __tablename__ = "versions"
    __table_args__ = (
        Index(
            "uq_ritual_versions_source_identity",
            "document_id",
            "source_file_hash",
            "corpus_zone",
            text("COALESCE(semantic_version, '')"),
            unique=True,
        ),
        CheckConstraint("source_file_hash ~ '^[0-9a-f]{64}$'", name="valid_hash"),
        CheckConstraint(
            "((corpus_zone = 'MANASEK_WORKING' AND status IN "
            "('draft', 'review', 'deprecated')) OR "
            "(corpus_zone = 'MANASEK_CANON' AND status IN "
            "('approved', 'superseded', 'deprecated')))",
            name="status_matches_zone",
        ),
        CheckConstraint(
            "(status <> 'approved') OR "
            "(semantic_version IS NOT NULL AND approved_by IS NOT NULL AND "
            "approved_at IS NOT NULL AND effective_from IS NOT NULL AND "
            "corpus_zone = 'MANASEK_CANON')",
            name="approved_metadata",
        ),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.documents.id", ondelete="RESTRICT"), index=True
    )
    designed_against_ayin_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.canon_versions.id", ondelete="RESTRICT")
    )
    supersedes_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{RITUAL}.versions.id", ondelete="RESTRICT"), nullable=True
    )
    semantic_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[EditorialStatus] = mapped_column(
        _core_enum(EditorialStatus, "editorial_status")
    )
    corpus_zone: Mapped[CorpusZone] = mapped_column(
        _core_enum(CorpusZone, "corpus_zone")
    )
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


class RitualVersionSourceAsset(Base):
    __tablename__ = "version_source_assets"
    __table_args__ = (
        UniqueConstraint("source_version_id", "source_asset_id"),
        {"schema": RITUAL},
    )

    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.versions.id", ondelete="RESTRICT"), primary_key=True
    )
    source_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{OPS}.object_assets.id", ondelete="RESTRICT")
    )


class RitualExtractionRun(Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        UniqueConstraint("id", "source_version_id"),
        UniqueConstraint(
            "source_version_id",
            "importer_version",
            "extractor_name",
            "extractor_version",
            "normalization_version",
            "segmentation_version",
            "configuration_hash",
        ),
        ForeignKeyConstraint(
            ["source_version_id", "source_asset_id"],
            [
                f"{RITUAL}.version_source_assets.source_version_id",
                f"{RITUAL}.version_source_assets.source_asset_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("page_count > 0", name="positive_page_count"),
        CheckConstraint("passage_count > 0", name="positive_passage_count"),
        CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name="valid_configuration_hash",
        ),
        CheckConstraint("output_hash ~ '^[0-9a-f]{64}$'", name="valid_output_hash"),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID] = mapped_column(index=True)
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


class PreferredRitualExtractionRun(Base):
    __tablename__ = "preferred_extraction_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["extraction_run_id", "source_version_id"],
            [
                f"{RITUAL}.extraction_runs.id",
                f"{RITUAL}.extraction_runs.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": RITUAL},
    )

    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.versions.id", ondelete="CASCADE"), primary_key=True
    )
    extraction_run_id: Mapped[UUID]
    selected_by: Mapped[str] = mapped_column(String(255))
    reason: Mapped[str] = mapped_column(Text)
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class RitualPassage(Base):
    __tablename__ = "passages"
    __table_args__ = (
        UniqueConstraint("extraction_run_id", "sequence"),
        UniqueConstraint("id", "source_version_id"),
        UniqueConstraint("id", "extraction_run_id"),
        ForeignKeyConstraint(
            ["extraction_run_id", "source_version_id"],
            [
                f"{RITUAL}.extraction_runs.id",
                f"{RITUAL}.extraction_runs.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_version_id", "source_asset_id"],
            [
                f"{RITUAL}.version_source_assets.source_version_id",
                f"{RITUAL}.version_source_assets.source_asset_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("page_number > 0", name="positive_page_number"),
        CheckConstraint("sequence > 0", name="positive_sequence"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="valid_hash"),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID] = mapped_column(index=True)
    extraction_run_id: Mapped[UUID] = mapped_column(index=True)
    source_asset_id: Mapped[UUID]
    sequence: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int] = mapped_column(Integer)
    printed_page_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    heading_path: Mapped[list[str]] = mapped_column(JSONB)
    paragraph_index: Mapped[int] = mapped_column(Integer, default=1)
    raw_text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    language: Mapped[LanguageCode] = mapped_column(
        _core_enum(LanguageCode, "language_code")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class RitualFamily(Base):
    __tablename__ = "families"
    __table_args__ = ({"schema": RITUAL},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    stable_key: Mapped[str] = mapped_column(String(64), unique=True)
    family_type: Mapped[RitualFamilyType] = mapped_column(
        _enum(RitualFamilyType, "family_type"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class RitualFamilyVersion(Base):
    __tablename__ = "family_versions"
    __table_args__ = (
        UniqueConstraint("family_id", "source_version_id", "version_number"),
        ForeignKeyConstraint(
            ["source_passage_id", "source_version_id"],
            [f"{RITUAL}.passages.id", f"{RITUAL}.passages.source_version_id"],
            ondelete="RESTRICT",
        ),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.families.id", ondelete="RESTRICT")
    )
    source_version_id: Mapped[UUID]
    source_passage_id: Mapped[UUID]
    version_number: Mapped[int] = mapped_column(Integer)
    title_fa: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[EditorialStatus] = mapped_column(
        _core_enum(EditorialStatus, "editorial_status")
    )


class Gate(Base):
    __tablename__ = "gates"
    __table_args__ = (
        CheckConstraint("sequence_position BETWEEN 1 AND 5", name="five_gate_slots"),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    stable_key: Mapped[GateKey] = mapped_column(_enum(GateKey, "gate_key"), unique=True)
    sequence_position: Mapped[int] = mapped_column(Integer, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class GateVersion(Base):
    __tablename__ = "gate_versions"
    __table_args__ = (
        UniqueConstraint("gate_id", "source_version_id", "version_number"),
        ForeignKeyConstraint(
            ["source_passage_id", "source_version_id"],
            [f"{RITUAL}.passages.id", f"{RITUAL}.passages.source_version_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("is_bon_component = false", name="not_bon_component"),
        CheckConstraint(
            "is_metaphysical_element = false", name="not_metaphysical_element"
        ),
        CheckConstraint(
            "is_personality_category = false", name="not_personality_category"
        ),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    gate_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.gates.id", ondelete="RESTRICT")
    )
    source_version_id: Mapped[UUID]
    source_passage_id: Mapped[UUID]
    version_number: Mapped[int] = mapped_column(Integer)
    title_fa: Mapped[str] = mapped_column(String(128))
    symbolic_role: Mapped[str] = mapped_column(Text)
    is_bon_component: Mapped[bool] = mapped_column(Boolean, default=False)
    is_metaphysical_element: Mapped[bool] = mapped_column(Boolean, default=False)
    is_personality_category: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[EditorialStatus] = mapped_column(
        _core_enum(EditorialStatus, "editorial_status")
    )


class ArchitectureVersion(Base):
    __tablename__ = "architecture_versions"
    __table_args__ = (
        UniqueConstraint("id", "source_version_id"),
        UniqueConstraint("source_version_id", "mode", "version_number"),
        ForeignKeyConstraint(
            ["source_passage_id", "source_version_id"],
            [f"{RITUAL}.passages.id", f"{RITUAL}.passages.source_version_id"],
            ondelete="RESTRICT",
        ),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID]
    source_passage_id: Mapped[UUID]
    mode: Mapped[RitualMode] = mapped_column(_enum(RitualMode, "ritual_mode"))
    version_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[EditorialStatus] = mapped_column(
        _core_enum(EditorialStatus, "editorial_status")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class RitualStage(Base):
    __tablename__ = "stages"
    __table_args__ = (
        UniqueConstraint("id", "architecture_version_id"),
        UniqueConstraint("architecture_version_id", "sequence_position"),
        UniqueConstraint("architecture_version_id", "stable_key"),
        ForeignKeyConstraint(
            ["architecture_version_id", "source_version_id"],
            [
                f"{RITUAL}.architecture_versions.id",
                f"{RITUAL}.architecture_versions.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_passage_id", "source_version_id"],
            [f"{RITUAL}.passages.id", f"{RITUAL}.passages.source_version_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("sequence_position BETWEEN 1 AND 7", name="seven_stage_slots"),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    architecture_version_id: Mapped[UUID]
    source_version_id: Mapped[UUID]
    source_passage_id: Mapped[UUID]
    stable_key: Mapped[str] = mapped_column(String(64))
    sequence_position: Mapped[int] = mapped_column(Integer)
    title_fa: Mapped[str] = mapped_column(String(255))
    purpose: Mapped[str] = mapped_column(Text)


class Ritual(Base):
    __tablename__ = "rituals"
    __table_args__ = ({"schema": RITUAL},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    stable_key: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class RitualVersion(Base):
    __tablename__ = "ritual_versions"
    __table_args__ = (
        UniqueConstraint("id", "piece_type"),
        UniqueConstraint("id", "architecture_version_id", "piece_type"),
        UniqueConstraint("ritual_id", "source_version_id", "version_number"),
        ForeignKeyConstraint(
            ["architecture_version_id", "source_version_id"],
            [
                f"{RITUAL}.architecture_versions.id",
                f"{RITUAL}.architecture_versions.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["stage_id", "architecture_version_id"],
            [f"{RITUAL}.stages.id", f"{RITUAL}.stages.architecture_version_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_passage_id", "source_version_id"],
            [f"{RITUAL}.passages.id", f"{RITUAL}.passages.source_version_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(piece_type = 'GATE' AND mode = 'INDIVIDUAL' AND stage_id IS NOT NULL "
            "AND gate_id IS NOT NULL) OR "
            "(piece_type = 'RETURN' AND mode = 'INDIVIDUAL' AND stage_id IS NOT NULL "
            "AND gate_id IS NULL) OR "
            "(piece_type = 'COLLECTIVE' AND mode = 'COLLECTIVE' "
            "AND stage_id IS NULL AND gate_id IS NULL)",
            name="piece_shape",
        ),
        CheckConstraint("estimated_duration_seconds > 0", name="positive_duration"),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ritual_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.rituals.id", ondelete="RESTRICT"), index=True
    )
    source_version_id: Mapped[UUID]
    source_passage_id: Mapped[UUID]
    architecture_version_id: Mapped[UUID]
    family_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.families.id", ondelete="RESTRICT")
    )
    designed_against_ayin_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.canon_versions.id", ondelete="RESTRICT")
    )
    stage_id: Mapped[UUID | None]
    gate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{RITUAL}.gates.id", ondelete="RESTRICT"), nullable=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    piece_type: Mapped[RitualPieceType] = mapped_column(
        _enum(RitualPieceType, "piece_type")
    )
    mode: Mapped[RitualMode] = mapped_column(_enum(RitualMode, "ritual_mode"))
    title: Mapped[str] = mapped_column(String(512))
    purpose: Mapped[str] = mapped_column(Text)
    estimated_duration_seconds: Mapped[int] = mapped_column(Integer)
    preparation: Mapped[str | None] = mapped_column(Text, nullable=True)
    experiential_instructions: Mapped[str] = mapped_column(Text)
    safety_notes: Mapped[str] = mapped_column(Text)
    exit_instructions: Mapped[str] = mapped_column(Text)
    status: Mapped[EditorialStatus] = mapped_column(
        _core_enum(EditorialStatus, "editorial_status")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class RitualReturn(Base):
    __tablename__ = "returns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["ritual_version_id", "piece_type"],
            [f"{RITUAL}.ritual_versions.id", f"{RITUAL}.ritual_versions.piece_type"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("piece_type = 'RETURN'", name="return_not_gate"),
        {"schema": RITUAL},
    )

    ritual_version_id: Mapped[UUID] = mapped_column(primary_key=True)
    piece_type: Mapped[RitualPieceType] = mapped_column(
        _enum(RitualPieceType, "piece_type")
    )
    integration_function: Mapped[str] = mapped_column(Text)
    ordinary_reorientation: Mapped[bool] = mapped_column(Boolean, default=True)
    lowers_interpretive_intensity: Mapped[bool] = mapped_column(Boolean, default=True)


class RitualSequenceItem(Base):
    __tablename__ = "ritual_sequence_items"
    __table_args__ = (
        UniqueConstraint("architecture_version_id", "sequence_position"),
        UniqueConstraint("stage_id", "stage_sequence_position"),
        UniqueConstraint("ritual_version_id"),
        Index(
            "uq_ritual_sequence_items_stage_gate_position",
            "stage_id",
            "gate_position",
            unique=True,
            postgresql_where=text("slot_kind = 'GATE'"),
        ),
        Index(
            "uq_ritual_sequence_items_one_return_per_stage",
            "stage_id",
            unique=True,
            postgresql_where=text("slot_kind = 'RETURN'"),
        ),
        ForeignKeyConstraint(
            ["stage_id", "architecture_version_id"],
            [f"{RITUAL}.stages.id", f"{RITUAL}.stages.architecture_version_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["ritual_version_id", "architecture_version_id", "slot_kind"],
            [
                f"{RITUAL}.ritual_versions.id",
                f"{RITUAL}.ritual_versions.architecture_version_id",
                f"{RITUAL}.ritual_versions.piece_type",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("sequence_position > 0", name="positive_sequence"),
        CheckConstraint(
            "(slot_kind = 'GATE' AND stage_id IS NOT NULL AND "
            "stage_sequence_position BETWEEN 1 AND 5 AND "
            "gate_position BETWEEN 1 AND 5) "
            "OR (slot_kind = 'RETURN' AND stage_id IS NOT NULL AND "
            "stage_sequence_position = 6 AND gate_position IS NULL) "
            "OR (slot_kind = 'COLLECTIVE' AND stage_id IS NULL AND "
            "stage_sequence_position IS NULL AND gate_position IS NULL)",
            name="sequence_slot_shape",
        ),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    architecture_version_id: Mapped[UUID]
    stage_id: Mapped[UUID | None]
    ritual_version_id: Mapped[UUID]
    sequence_position: Mapped[int] = mapped_column(Integer)
    stage_sequence_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slot_kind: Mapped[RitualPieceType] = mapped_column(
        _enum(RitualPieceType, "piece_type")
    )
    gate_position: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RitualCue(Base):
    __tablename__ = "cues"
    __table_args__ = (
        UniqueConstraint("ritual_version_id", "sequence"),
        CheckConstraint("sequence > 0", name="positive_sequence"),
        CheckConstraint(
            "start_seconds IS NULL OR start_seconds >= 0", name="nonnegative_start"
        ),
        CheckConstraint(
            "end_seconds IS NULL OR (start_seconds IS NOT NULL AND "
            "end_seconds > start_seconds)",
            name="valid_interval",
        ),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ritual_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.ritual_versions.id", ondelete="CASCADE"), index=True
    )
    source_passage_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.passages.id", ondelete="RESTRICT")
    )
    sequence: Mapped[int] = mapped_column(Integer)
    cue_type: Mapped[CueType] = mapped_column(_enum(CueType, "cue_type"))
    start_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[LanguageCode] = mapped_column(
        _core_enum(LanguageCode, "language_code")
    )
    optional: Mapped[bool] = mapped_column(Boolean, default=True)


class MusicSpecification(Base):
    __tablename__ = "music_specifications"
    __table_args__ = (
        CheckConstraint("duration_seconds > 0", name="positive_duration"),
        {"schema": RITUAL},
    )

    ritual_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.ritual_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_passage_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.passages.id", ondelete="RESTRICT")
    )
    duration_seconds: Mapped[int] = mapped_column(Integer)
    sonic_family: Mapped[str] = mapped_column(Text)
    emotional_arc: Mapped[str] = mapped_column(Text)
    intensity_profile: Mapped[str] = mapped_column(Text)
    prohibited_features: Mapped[list[str]] = mapped_column(JSONB)
    transition_requirements: Mapped[str] = mapped_column(Text)
    ending_requirements: Mapped[str] = mapped_column(Text)
    original_prompt: Mapped[str] = mapped_column(Text)


class RitualLocalization(Base):
    __tablename__ = "localizations"
    __table_args__ = (
        UniqueConstraint("ritual_version_id", "language", "version_number"),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ritual_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.ritual_versions.id", ondelete="CASCADE"), index=True
    )
    source_passage_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.passages.id", ondelete="RESTRICT")
    )
    language: Mapped[LanguageCode] = mapped_column(
        _core_enum(LanguageCode, "language_code")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(512))
    narration_text: Mapped[str] = mapped_column(Text)
    instructions: Mapped[str] = mapped_column(Text)
    safety_language: Mapped[str] = mapped_column(Text)
    terminology_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[EditorialStatus] = mapped_column(
        _core_enum(EditorialStatus, "editorial_status")
    )


class SafetyRule(Base):
    __tablename__ = "safety_rules"
    __table_args__ = ({"schema": RITUAL},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    stable_key: Mapped[str] = mapped_column(String(128), unique=True)
    category: Mapped[SafetyCategory] = mapped_column(
        _enum(SafetyCategory, "safety_category")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class SafetyRuleVersion(Base):
    __tablename__ = "safety_rule_versions"
    __table_args__ = (
        UniqueConstraint("rule_id", "source_version_id", "version_number"),
        ForeignKeyConstraint(
            ["source_passage_id", "source_version_id"],
            [f"{RITUAL}.passages.id", f"{RITUAL}.passages.source_version_id"],
            ondelete="RESTRICT",
        ),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    rule_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.safety_rules.id", ondelete="RESTRICT"), index=True
    )
    source_version_id: Mapped[UUID]
    source_passage_id: Mapped[UUID]
    version_number: Mapped[int] = mapped_column(Integer)
    severity: Mapped[SafetySeverity] = mapped_column(
        _enum(SafetySeverity, "safety_severity")
    )
    requirement_text: Mapped[str] = mapped_column(Text)
    required_capability: Mapped[str] = mapped_column(String(128))
    prohibited_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[EditorialStatus] = mapped_column(
        _core_enum(EditorialStatus, "editorial_status")
    )


class RitualVersionSafetyRule(Base):
    __tablename__ = "ritual_version_safety_rules"
    __table_args__ = ({"schema": RITUAL},)

    ritual_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.ritual_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    safety_rule_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.safety_rule_versions.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class LocalizationSafetyRule(Base):
    __tablename__ = "localization_safety_rules"
    __table_args__ = ({"schema": RITUAL},)

    localization_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.localizations.id", ondelete="CASCADE"), primary_key=True
    )
    safety_rule_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.safety_rule_versions.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class RitualConceptLink(Base):
    __tablename__ = "concept_links"
    __table_args__ = (
        UniqueConstraint("ritual_version_id", "ayin_concept_version_id", "relation"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="valid_confidence",
        ),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ritual_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.ritual_versions.id", ondelete="CASCADE")
    )
    ayin_concept_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.ayin_concept_versions.id", ondelete="RESTRICT")
    )
    source_passage_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.passages.id", ondelete="RESTRICT")
    )
    relation: Mapped[RitualRelationType] = mapped_column(
        _enum(RitualRelationType, "concept_relation_type")
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        _core_enum(ReviewStatus, "ayin_review_status")
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    proposed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class GateConceptLink(Base):
    __tablename__ = "gate_concept_links"
    __table_args__ = (
        UniqueConstraint(
            "gate_id", "ayin_concept_version_id", "relation", "source_version_id"
        ),
        ForeignKeyConstraint(
            ["source_passage_id", "source_version_id"],
            [f"{RITUAL}.passages.id", f"{RITUAL}.passages.source_version_id"],
            ondelete="RESTRICT",
        ),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    gate_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.gates.id", ondelete="RESTRICT")
    )
    ayin_concept_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.ayin_concept_versions.id", ondelete="RESTRICT")
    )
    source_version_id: Mapped[UUID]
    source_passage_id: Mapped[UUID]
    relation: Mapped[RitualRelationType] = mapped_column(
        _enum(RitualRelationType, "concept_relation_type")
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        _core_enum(ReviewStatus, "ayin_review_status")
    )


class StageConceptLink(Base):
    __tablename__ = "stage_concept_links"
    __table_args__ = (
        UniqueConstraint("stage_id", "ayin_concept_version_id", "relation"),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    stage_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.stages.id", ondelete="RESTRICT")
    )
    ayin_concept_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.ayin_concept_versions.id", ondelete="RESTRICT")
    )
    source_passage_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.passages.id", ondelete="RESTRICT")
    )
    relation: Mapped[RitualRelationType] = mapped_column(
        _enum(RitualRelationType, "concept_relation_type")
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        _core_enum(ReviewStatus, "ayin_review_status")
    )


class StageConceptLinkProposal(Base):
    __tablename__ = "stage_concept_link_proposals"
    __table_args__ = (
        UniqueConstraint("stage_id", "proposed_stable_key", "relation"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="valid_confidence",
        ),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    stage_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.stages.id", ondelete="CASCADE")
    )
    proposed_stable_key: Mapped[str] = mapped_column(String(255))
    source_passage_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.passages.id", ondelete="RESTRICT")
    )
    relation: Mapped[RitualRelationType] = mapped_column(
        _enum(RitualRelationType, "concept_relation_type")
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        _core_enum(ReviewStatus, "ayin_review_status")
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    proposed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class RitualReviewFlag(Base):
    __tablename__ = "review_flags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["extraction_run_id", "source_version_id"],
            [
                f"{RITUAL}.extraction_runs.id",
                f"{RITUAL}.extraction_runs.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(status = 'open' AND reviewed_at IS NULL) OR "
            "(status IN ('resolved', 'dismissed') AND reviewed_at IS NOT NULL)",
            name="review_completion_metadata",
        ),
        {"schema": RITUAL},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_version_id: Mapped[UUID]
    extraction_run_id: Mapped[UUID] = mapped_column(index=True)
    source_passage_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.passages.id", ondelete="RESTRICT")
    )
    ritual_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{RITUAL}.ritual_versions.id", ondelete="RESTRICT"), nullable=True
    )
    source_page: Mapped[int] = mapped_column(Integer)
    reason: Mapped[RitualReviewReason] = mapped_column(
        _enum(RitualReviewReason, "review_reason")
    )
    status: Mapped[ReviewStatus] = mapped_column(
        _core_enum(ReviewStatus, "ayin_review_status")
    )
    message: Mapped[str] = mapped_column(Text)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class SafetyValidationResult(Base):
    __tablename__ = "safety_validation_results"
    __table_args__ = ({"schema": RITUAL},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ritual_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.ritual_versions.id", ondelete="CASCADE"), index=True
    )
    valid: Mapped[bool] = mapped_column(Boolean)
    publishable: Mapped[bool] = mapped_column(Boolean)
    issues: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    validator_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
