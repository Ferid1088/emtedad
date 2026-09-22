"""Version-pinned, fully typed dialogue persistence models."""

from datetime import datetime
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
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PostgresSchema
from app.dialogue.domain import (
    AyinTargetKind,
    ClaimTestability,
    EvidenceRole,
    ExternalTargetKind,
    ProposalMethod,
    ProposalRunStatus,
    RelationScope,
    RelationType,
    ReviewAction,
    ReviewPriority,
    ReviewReason,
    ReviewStatus,
)
from app.ops.assets.models import utc_now

CORE = PostgresSchema.CORE.value
KNOWLEDGE = PostgresSchema.KNOWLEDGE.value
RETRIEVAL = PostgresSchema.RETRIEVAL.value


def _enum(enum_type: type[Any], name: str) -> ENUM:
    return ENUM(
        enum_type,
        name=name,
        schema=KNOWLEDGE,
        values_callable=lambda members: [member.value for member in members],
    )


class DialogueAyinTarget(Base):
    """One exact Ayin object version and its primary source passage."""

    __tablename__ = "dialogue_ayin_targets"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(concept_version_id, principle_version_id, "
            "distinction_version_id, open_question_version_id) = 1",
            name="one_typed_ayin_version",
        ),
        CheckConstraint(
            "(kind = 'CONCEPT_VERSION' AND concept_version_id IS NOT NULL) OR "
            "(kind = 'PRINCIPLE_VERSION' AND principle_version_id IS NOT NULL) OR "
            "(kind = 'DISTINCTION_VERSION' AND distinction_version_id IS NOT NULL) OR "
            "(kind = 'OPEN_QUESTION_VERSION' AND open_question_version_id IS NOT NULL)",
            name="ayin_kind_matches_target",
        ),
        UniqueConstraint("concept_version_id"),
        UniqueConstraint("principle_version_id"),
        UniqueConstraint("distinction_version_id"),
        UniqueConstraint("open_question_version_id"),
        ForeignKeyConstraint(
            ["source_passage_id", "canon_version_id"],
            [f"{CORE}.canon_passages.id", f"{CORE}.canon_passages.canon_version_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["concept_version_id", "canon_version_id"],
            [
                f"{CORE}.ayin_concept_versions.id",
                f"{CORE}.ayin_concept_versions.canon_version_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["principle_version_id", "canon_version_id"],
            [
                f"{CORE}.ayin_principle_versions.id",
                f"{CORE}.ayin_principle_versions.canon_version_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["distinction_version_id", "canon_version_id"],
            [
                f"{CORE}.ayin_distinction_versions.id",
                f"{CORE}.ayin_distinction_versions.canon_version_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["open_question_version_id", "canon_version_id"],
            [
                f"{CORE}.ayin_open_question_versions.id",
                f"{CORE}.ayin_open_question_versions.canon_version_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[AyinTargetKind] = mapped_column(
        _enum(AyinTargetKind, "dialogue_ayin_target_kind")
    )
    canon_version_id: Mapped[UUID]
    source_passage_id: Mapped[UUID]
    concept_version_id: Mapped[UUID | None] = mapped_column(nullable=True)
    principle_version_id: Mapped[UUID | None] = mapped_column(nullable=True)
    distinction_version_id: Mapped[UUID | None] = mapped_column(nullable=True)
    open_question_version_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class DialogueAyinEvidence(Base):
    """Additional exact Ayin passage supporting the assessed target context."""

    __tablename__ = "dialogue_ayin_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["passage_id", "canon_version_id"],
            [f"{CORE}.canon_passages.id", f"{CORE}.canon_passages.canon_version_id"],
            ondelete="RESTRICT",
        ),
        {"schema": KNOWLEDGE},
    )
    ayin_target_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.dialogue_ayin_targets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    passage_id: Mapped[UUID] = mapped_column(primary_key=True)
    canon_version_id: Mapped[UUID]


class DialogueExternalTarget(Base):
    """One typed external object plus exact primary source evidence."""

    __tablename__ = "dialogue_external_targets"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(claim_id, work_id, chunk_id, external_concept_id, "
            "person_id) = 1",
            name="one_typed_external_target",
        ),
        CheckConstraint(
            "(kind = 'CLAIM' AND claim_id IS NOT NULL) OR "
            "(kind = 'WORK' AND work_id IS NOT NULL) OR "
            "(kind = 'CHUNK' AND chunk_id IS NOT NULL) OR "
            "(kind = 'EXTERNAL_CONCEPT' AND external_concept_id IS NOT NULL) OR "
            "(kind = 'PERSON' AND person_id IS NOT NULL)",
            name="external_kind_matches_target",
        ),
        ForeignKeyConstraint(
            ["source_segment_id", "source_version_id"],
            [
                f"{KNOWLEDGE}.source_segments.id",
                f"{KNOWLEDGE}.source_segments.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["claim_id", "source_version_id", "source_segment_id"],
            [
                f"{KNOWLEDGE}.external_claims.id",
                f"{KNOWLEDGE}.external_claims.source_version_id",
                f"{KNOWLEDGE}.external_claims.source_segment_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["chunk_id", "source_segment_id"],
            [
                f"{RETRIEVAL}.chunk_external_segments.chunk_id",
                f"{RETRIEVAL}.chunk_external_segments.source_segment_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[ExternalTargetKind] = mapped_column(
        _enum(ExternalTargetKind, "dialogue_external_target_kind")
    )
    source_version_id: Mapped[UUID]
    source_segment_id: Mapped[UUID]
    claim_id: Mapped[UUID | None] = mapped_column(nullable=True)
    work_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.works.id", ondelete="RESTRICT"), nullable=True
    )
    chunk_id: Mapped[UUID | None] = mapped_column(nullable=True)
    external_concept_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.external_concepts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    person_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.people.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class DialogueExternalEvidence(Base):
    """Additional exact external segments/chunks used in one assessment."""

    __tablename__ = "dialogue_external_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_segment_id", "source_version_id"],
            [
                f"{KNOWLEDGE}.source_segments.id",
                f"{KNOWLEDGE}.source_segments.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["chunk_id", "source_segment_id"],
            [
                f"{RETRIEVAL}.chunk_external_segments.chunk_id",
                f"{RETRIEVAL}.chunk_external_segments.source_segment_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": KNOWLEDGE},
    )
    external_target_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.dialogue_external_targets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_segment_id: Mapped[UUID] = mapped_column(primary_key=True)
    source_version_id: Mapped[UUID]
    chunk_id: Mapped[UUID | None] = mapped_column(nullable=True)


class DialogueProposalRun(Base):
    """Reproducible classifier run pinned to retrieval and model configuration."""

    __tablename__ = "dialogue_proposal_runs"
    __table_args__ = (
        UniqueConstraint("cache_key"),
        CheckConstraint("cache_key ~ '^[0-9a-f]{64}$'", name="valid_cache_key"),
        CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'", name="valid_configuration_hash"
        ),
        CheckConstraint(
            "ayin_input_hash ~ '^[0-9a-f]{64}$'", name="valid_ayin_input_hash"
        ),
        CheckConstraint(
            "candidate_input_hash ~ '^[0-9a-f]{64}$'",
            name="valid_candidate_input_hash",
        ),
        CheckConstraint(
            "candidate_count >= 0 AND success_count >= 0 AND failure_count >= 0",
            name="nonnegative_counts",
        ),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ayin_target_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.dialogue_ayin_targets.id", ondelete="RESTRICT")
    )
    retrieval_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.runs.id", ondelete="RESTRICT")
    )
    provider: Mapped[str] = mapped_column(String(128))
    model: Mapped[str] = mapped_column(String(512))
    prompt_version: Mapped[str] = mapped_column(String(64))
    classifier_version: Mapped[str] = mapped_column(String(64))
    retrieval_configuration: Mapped[dict[str, object]] = mapped_column(JSONB)
    configuration_hash: Mapped[str] = mapped_column(String(64))
    ayin_input_hash: Mapped[str] = mapped_column(String(64))
    candidate_input_hash: Mapped[str] = mapped_column(String(64))
    cache_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[ProposalRunStatus] = mapped_column(
        _enum(ProposalRunStatus, "dialogue_proposal_run_status")
    )
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DialogueProposalRunCandidate(Base):
    """A real retrieved external chunk and its cached structured classification."""

    __tablename__ = "dialogue_proposal_run_candidates"
    __table_args__ = (
        UniqueConstraint("proposal_run_id", "chunk_id"),
        CheckConstraint("rank > 0", name="positive_rank"),
        CheckConstraint(
            "classifier_cache_key ~ '^[0-9a-f]{64}$'",
            name="valid_classifier_cache_key",
        ),
        {"schema": KNOWLEDGE},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    proposal_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.dialogue_proposal_runs.id", ondelete="CASCADE")
    )
    external_target_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.dialogue_external_targets.id", ondelete="RESTRICT")
    )
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunks.id", ondelete="RESTRICT")
    )
    rank: Mapped[int] = mapped_column(Integer)
    chunk_content_hash: Mapped[str] = mapped_column(String(64))
    classifier_cache_key: Mapped[str] = mapped_column(String(64))
    structured_output: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class DialogueProposal(Base):
    """Immutable original machine or manual classification proposal."""

    __tablename__ = "dialogue_proposals"
    __table_args__ = (
        CheckConstraint(
            "relation_confidence >= 0 AND relation_confidence <= 1",
            name="valid_relation_confidence",
        ),
        CheckConstraint(
            "(proposal_method = 'MODEL_CLASSIFIER' AND proposal_run_id IS NOT NULL "
            "AND candidate_id IS NOT NULL) OR proposal_method = 'MANUAL'",
            name="machine_proposal_has_run",
        ),
        UniqueConstraint("candidate_id", "relation_type", "scope"),
        {"schema": KNOWLEDGE},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    proposal_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.dialogue_proposal_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            f"{KNOWLEDGE}.dialogue_proposal_run_candidates.id", ondelete="RESTRICT"
        ),
        nullable=True,
    )
    ayin_target_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.dialogue_ayin_targets.id", ondelete="RESTRICT")
    )
    external_target_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.dialogue_external_targets.id", ondelete="RESTRICT")
    )
    relation_type: Mapped[RelationType] = mapped_column(
        _enum(RelationType, "dialogue_relation_type")
    )
    scope: Mapped[RelationScope] = mapped_column(
        _enum(RelationScope, "dialogue_relation_scope")
    )
    explanation: Mapped[str] = mapped_column(Text)
    relation_confidence: Mapped[float] = mapped_column(Float)
    evidence_role: Mapped[EvidenceRole] = mapped_column(
        _enum(EvidenceRole, "dialogue_evidence_role")
    )
    claim_testability: Mapped[ClaimTestability] = mapped_column(
        _enum(ClaimTestability, "dialogue_claim_testability")
    )
    proposal_method: Mapped[ProposalMethod] = mapped_column(
        _enum(ProposalMethod, "dialogue_proposal_method")
    )
    review_priority: Mapped[ReviewPriority] = mapped_column(
        _enum(ReviewPriority, "dialogue_review_priority")
    )
    created_by: Mapped[str] = mapped_column(String(255))
    validation_issues: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class DialogueRelation(Base):
    """Current reviewed classification; original proposal remains immutable."""

    __tablename__ = "dialogue_relations"
    __table_args__ = (
        UniqueConstraint("proposal_id"),
        CheckConstraint(
            "(review_status IN ('PROPOSED', 'IN_REVIEW') AND reviewed_at IS NULL) OR "
            "(review_status IN ('APPROVED', 'REJECTED', 'SUPERSEDED') AND "
            "reviewed_at IS NOT NULL)",
            name="review_completion_metadata",
        ),
        {"schema": KNOWLEDGE},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    proposal_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.dialogue_proposals.id", ondelete="RESTRICT")
    )
    relation_type: Mapped[RelationType] = mapped_column(
        _enum(RelationType, "dialogue_relation_type")
    )
    scope: Mapped[RelationScope] = mapped_column(
        _enum(RelationScope, "dialogue_relation_scope")
    )
    explanation: Mapped[str] = mapped_column(Text)
    review_status: Mapped[ReviewStatus] = mapped_column(
        _enum(ReviewStatus, "dialogue_review_status"),
        default=ReviewStatus.PROPOSED,
        server_default=ReviewStatus.PROPOSED.value,
    )
    review_priority: Mapped[ReviewPriority] = mapped_column(
        _enum(ReviewPriority, "dialogue_review_priority")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class DialogueReviewDecision(Base):
    """Append-only human review history, including classification overrides."""

    __tablename__ = "dialogue_review_decisions"
    __table_args__ = ({"schema": KNOWLEDGE},)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    relation_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.dialogue_relations.id", ondelete="RESTRICT"),
        index=True,
    )
    action: Mapped[ReviewAction] = mapped_column(
        _enum(ReviewAction, "dialogue_review_action")
    )
    reviewer: Mapped[str] = mapped_column(String(255))
    previous_relation_type: Mapped[RelationType] = mapped_column(
        _enum(RelationType, "dialogue_relation_type")
    )
    new_relation_type: Mapped[RelationType] = mapped_column(
        _enum(RelationType, "dialogue_relation_type")
    )
    previous_scope: Mapped[RelationScope] = mapped_column(
        _enum(RelationScope, "dialogue_relation_scope")
    )
    new_scope: Mapped[RelationScope] = mapped_column(
        _enum(RelationScope, "dialogue_relation_scope")
    )
    previous_explanation: Mapped[str] = mapped_column(Text)
    new_explanation: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class DialogueReviewFlag(Base):
    """Typed reason placing a proposed relation into the review queue."""

    __tablename__ = "dialogue_review_flags"
    __table_args__ = (
        UniqueConstraint("relation_id", "reason"),
        {"schema": KNOWLEDGE},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    relation_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.dialogue_relations.id", ondelete="CASCADE"),
        index=True,
    )
    reason: Mapped[ReviewReason] = mapped_column(
        _enum(ReviewReason, "dialogue_review_reason")
    )
    priority: Mapped[ReviewPriority] = mapped_column(
        _enum(ReviewPriority, "dialogue_review_priority")
    )
    message: Mapped[str] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


Index(
    "ix_dialogue_relations_review_queue",
    DialogueRelation.review_status,
    DialogueRelation.review_priority,
)
Index(
    "ix_dialogue_proposals_ayin_external",
    DialogueProposal.ayin_target_id,
    DialogueProposal.external_target_id,
)
