"""Pydantic boundaries for ritual reads and validation reports."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.ayin.domain import CorpusZone, EditorialStatus, LanguageCode, ReviewStatus
from app.ritual.domain import (
    CueType,
    GateKey,
    RitualFamilyType,
    RitualMode,
    RitualPieceType,
    RitualReviewReason,
    SafetyCategory,
    SafetySeverity,
)


class ReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class FamilyRead(ReadModel):
    id: UUID
    stable_key: str
    family_type: RitualFamilyType


class GateRead(ReadModel):
    id: UUID
    stable_key: GateKey
    sequence_position: int
    title_fa: str
    symbolic_role: str


class StageRead(ReadModel):
    id: UUID
    stable_key: str
    sequence_position: int
    title_fa: str
    purpose: str


class CueRead(ReadModel):
    id: UUID
    sequence: int
    cue_type: CueType
    start_seconds: int | None
    end_seconds: int | None
    text: str
    language: LanguageCode
    optional: bool


class MusicSpecificationRead(ReadModel):
    duration_seconds: int
    sonic_family: str
    emotional_arc: str
    intensity_profile: str
    prohibited_features: list[str]
    transition_requirements: str
    ending_requirements: str
    original_prompt: str


class RitualSummary(ReadModel):
    id: UUID
    stable_key: str
    version_id: UUID
    title: str
    mode: RitualMode
    piece_type: RitualPieceType
    status: EditorialStatus
    stage_id: UUID | None
    gate_id: UUID | None


class RitualDetail(RitualSummary):
    purpose: str
    estimated_duration_seconds: int
    experiential_instructions: str
    safety_notes: str
    exit_instructions: str
    cues: list[CueRead]
    music: MusicSpecificationRead


class SequenceItemRead(ReadModel):
    sequence_position: int
    stage_sequence_position: int | None
    slot_kind: RitualPieceType
    gate_position: int | None
    ritual_version_id: UUID


class SafetyRuleRead(ReadModel):
    id: UUID
    stable_key: str
    category: SafetyCategory
    version_id: UUID
    severity: SafetySeverity
    requirement_text: str
    status: EditorialStatus


class ReviewFlagRead(ReadModel):
    id: UUID
    extraction_run_id: UUID
    source_passage_id: UUID
    ritual_version_id: UUID | None
    source_page: int
    reason: RitualReviewReason
    status: ReviewStatus
    message: str
    reviewer_notes: str | None
    reviewed_at: datetime | None


class RitualDocumentRead(ReadModel):
    id: UUID
    slug: str
    title: str
    corpus_zone: CorpusZone


class ValidationIssue(BaseModel):
    code: str
    message: str
    record_id: UUID | None = None
    severity: SafetySeverity = SafetySeverity.BLOCKING


class ValidationReport(BaseModel):
    valid: bool
    publishable: bool = False
    issue_count: int
    issues: list[ValidationIssue]
