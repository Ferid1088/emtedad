"""Read-boundary schemas for external knowledge provenance."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.ayin.domain import CorpusZone
from app.knowledge.domain import (
    EntityType,
    KnowledgeReviewStatus,
    ResolutionStatus,
    VerificationStatus,
)


class OrmRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SourceRead(OrmRead):
    id: UUID
    platform: str
    external_id: str
    canonical_url: str
    title: str
    language: str
    ingestion_status: str


class SourceVersionRead(OrmRead):
    id: UUID
    source_id: UUID
    content_hash: str
    transcript_hash: str
    corpus_zone: CorpusZone
    provider_metadata: dict[str, object]
    normalization_version: str
    acquired_at: datetime


class SegmentRead(OrmRead):
    id: UUID
    source_version_id: UUID
    sequence: int
    start_seconds: Decimal
    end_seconds: Decimal
    raw_text: str
    normalized_text: str
    language: str


class MentionRead(OrmRead):
    id: UUID
    source_version_id: UUID
    source_segment_id: UUID
    extraction_run_id: UUID
    entity_type: EntityType
    surface_text: str
    context: str
    confidence: float
    resolution_status: ResolutionStatus


class ClaimRead(OrmRead):
    id: UUID
    source_version_id: UUID
    source_segment_id: UUID
    extraction_run_id: UUID
    claim_text: str
    claim_domain: str
    claim_type: str
    extraction_confidence: float
    verification_status: VerificationStatus


class EntityRead(OrmRead):
    id: UUID
    canonical_name: str


class WorkRead(OrmRead):
    id: UUID
    canonical_title: str
    publication_year: int | None
    publisher: str | None
    journal: str | None


class ReviewFlagRead(OrmRead):
    id: UUID
    source_version_id: UUID
    reason: str
    status: KnowledgeReviewStatus
    message: str


class ValidationIssue(BaseModel):
    code: str
    message: str
    record_id: UUID | None = None


class ValidationReport(BaseModel):
    valid: bool
    issue_count: int
    issues: list[ValidationIssue]
