"""Structured classifier, API, and CLI contracts for dialogue."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.dialogue.domain import (
    AyinTargetKind,
    ClaimTestability,
    EvidenceRole,
    ExternalTargetKind,
    RelationScope,
    RelationType,
    ReviewAction,
    ReviewPriority,
    ReviewReason,
    ReviewStatus,
)
from app.retrieval.domain import QueryLanguage


class ClassifiedRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation_type: RelationType
    scope: RelationScope
    explanation: str = Field(min_length=1, max_length=1200)
    relation_confidence: float = Field(ge=0, le=1)
    review_priority: ReviewPriority
    review_reasons: list[ReviewReason]


class DialogueClassification(BaseModel):
    """Provider output; an empty relation list is a valid conservative result."""

    model_config = ConfigDict(extra="forbid")

    evidence_role: EvidenceRole
    claim_testability: ClaimTestability
    relations: list[ClassifiedRelation] = Field(max_length=3)


class ValidationIssue(BaseModel):
    code: str
    message: str
    severity: str
    review_reason: ReviewReason | None = None


class ProvenancePins(BaseModel):
    ayin_version_id: UUID | None
    ayin_passage_ids: list[UUID]
    external_version_id: UUID | None
    external_segment_ids: list[UUID]
    proposal_run_id: UUID | None


class ProposeRequest(BaseModel):
    ayin_target_kind: AyinTargetKind
    ayin_identifier: str = Field(min_length=1, max_length=255)
    language: QueryLanguage = QueryLanguage.FA
    chunking_run_id: UUID | None = None
    embedding_model_id: UUID | None = None
    model: str = "configured-default"
    max_candidates: int = Field(default=5, ge=1, le=10)
    created_by: str = Field(default="codex-cli", min_length=1, max_length=255)


class ProposalResult(BaseModel):
    proposal_run_id: UUID
    retrieval_run_id: UUID
    relation_ids: list[UUID]
    candidate_count: int
    success_count: int
    failure_count: int
    cache_hit: bool


class ReviewRequest(BaseModel):
    action: ReviewAction
    reviewer: str = Field(min_length=1, max_length=255)
    notes: str = Field(min_length=1, max_length=4000)
    relation_type: RelationType | None = None
    scope: RelationScope | None = None
    explanation: str | None = Field(default=None, min_length=1, max_length=4000)


class RelationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    proposal_id: UUID
    ayin_target_id: UUID
    ayin_target_kind: AyinTargetKind
    ayin_version_id: UUID
    ayin_canon_version_id: UUID
    ayin_passage_id: UUID
    ayin_passage_ids: list[UUID]
    external_target_id: UUID
    external_target_kind: ExternalTargetKind
    external_version_id: UUID
    external_segment_id: UUID
    external_segment_ids: list[UUID]
    external_chunk_id: UUID | None
    original_relation_type: RelationType
    original_scope: RelationScope
    original_explanation: str
    relation_type: RelationType
    scope: RelationScope
    explanation: str
    relation_confidence: float
    evidence_role: EvidenceRole
    claim_testability: ClaimTestability
    review_status: ReviewStatus
    review_priority: ReviewPriority
    proposal_run_id: UUID | None
    retrieval_run_id: UUID | None
    classifier_provider: str | None
    classifier_model: str | None
    prompt_version: str | None
    classifier_version: str | None
    configuration_hash: str | None
    created_by: str
    created_at: datetime
    reviewed_at: datetime | None
    reviewer_notes: str | None
    validation_issues: list[ValidationIssue]
    ayin_stale: bool = False
    external_stale: bool = False


class ReviewQueueRead(BaseModel):
    relation: RelationRead
    reasons: list[ReviewReason]


class ValidationReport(BaseModel):
    valid: bool
    relation_count: int
    issue_count: int
    issues: list[ValidationIssue]


class CounterevidenceRequest(BaseModel):
    ayin_target_kind: AyinTargetKind
    ayin_identifier: str
    language: QueryLanguage = QueryLanguage.FA
    chunking_run_id: UUID | None = None
    embedding_model_id: UUID | None = None
    limit: int = Field(default=10, ge=1, le=30)
