"""Versioned, typed persistence for structured Semantic Lecture Masters."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PostgresSchema
from app.lecture.domain import (
    CitationKind,
    ClaimEpistemicStatus,
    ClaimOrigin,
    DiscourseType,
    EvidenceBindingRole,
    EvidenceKind,
    LectureProjectStatus,
    LectureType,
    MasterStatus,
    SectionRole,
    ValidationDimension,
)
from app.ops.assets.models import utc_now

CONTENT = PostgresSchema.CONTENT.value


def _enum(enum_type: type[Any], name: str) -> ENUM:
    return ENUM(
        enum_type,
        name=name,
        schema=CONTENT,
        values_callable=lambda members: [member.value for member in members],
    )


class LectureProject(Base):
    __tablename__ = "lecture_projects"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    research_package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="RESTRICT")
    )
    lecture_type: Mapped[LectureType] = mapped_column(
        _enum(LectureType, "lecture_type")
    )
    working_title: Mapped[str] = mapped_column(String(512))
    target_duration_seconds: Mapped[int | None] = mapped_column(nullable=True)
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), default="operator")
    status: Mapped[LectureProjectStatus] = mapped_column(
        _enum(LectureProjectStatus, "lecture_project_status"),
        default=LectureProjectStatus.DRAFT,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class LectureMasterVersion(Base):
    __tablename__ = "lecture_master_versions"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    lecture_project_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_projects.id", ondelete="RESTRICT")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    research_package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="RESTRICT")
    )
    research_package_version: Mapped[int] = mapped_column(Integer)
    research_package_content_hash: Mapped[str] = mapped_column(String(64))
    canon_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("core.canon_versions.id", ondelete="RESTRICT")
    )
    manasek_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ritual.ritual_versions.id", ondelete="RESTRICT"), nullable=True
    )
    package_authority: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    central_human_question: Mapped[str] = mapped_column(Text)
    ending_mode: Mapped[str] = mapped_column(String(32), default="OPEN")
    architecture: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    prohibited_conflations: Mapped[list[str]] = mapped_column(JSONB, default=list)
    uncertainty_constraints: Mapped[list[str]] = mapped_column(JSONB, default=list)
    status: Mapped[MasterStatus] = mapped_column(
        _enum(MasterStatus, "lecture_master_status"), default=MasterStatus.DRAFT
    )
    input_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    frozen_at: Mapped[datetime | None] = mapped_column(nullable=True)


class LectureSection(Base):
    __tablename__ = "lecture_sections"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    lecture_master_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_master_versions.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    role: Mapped[SectionRole] = mapped_column(
        _enum(SectionRole, "lecture_section_role")
    )
    purpose: Mapped[str] = mapped_column(Text)
    rhetorical_function: Mapped[str] = mapped_column(Text)
    transition_intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(nullable=True)
    required_terminology: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, default=list
    )
    prohibited_formulations: Mapped[list[str]] = mapped_column(JSONB, default=list)


class LectureClaim(Base):
    __tablename__ = "lecture_claims"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    lecture_master_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_master_versions.id", ondelete="CASCADE")
    )
    section_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_sections.id", ondelete="SET NULL"), nullable=True
    )
    stable_key: Mapped[str] = mapped_column(String(255))
    sequence: Mapped[int] = mapped_column(Integer)
    claim_intent: Mapped[str] = mapped_column(Text)
    # Human-readable semantic payload.  Nullable for historical masters only;
    # newly generated masters must populate it and pass standalone validation.
    semantic_proposition: Mapped[str | None] = mapped_column(Text, nullable=True)
    plain_meaning: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_concepts: Mapped[list[str]] = mapped_column(JSONB, default=list)
    required_qualifiers: Mapped[list[str]] = mapped_column(JSONB, default=list)
    prohibited_overstatements: Mapped[list[str]] = mapped_column(JSONB, default=list)
    source_support_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_evidence: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, default=list
    )
    claim_origin: Mapped[ClaimOrigin] = mapped_column(
        _enum(ClaimOrigin, "claim_origin")
    )
    discourse_type: Mapped[DiscourseType | None] = mapped_column(
        _enum(DiscourseType, "lecture_discourse_type"), nullable=True
    )
    epistemic_status: Mapped[ClaimEpistemicStatus] = mapped_column(
        _enum(ClaimEpistemicStatus, "claim_epistemic_status")
    )
    certainty: Mapped[str] = mapped_column(String(32), default="CALIBRATED")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    formulation_constraints: Mapped[list[str]] = mapped_column(JSONB, default=list)


class LectureClaimDependency(Base):
    __tablename__ = "lecture_claim_dependencies"
    __table_args__ = {"schema": CONTENT}

    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_claims.id", ondelete="CASCADE"), primary_key=True
    )
    premise_claim_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_claims.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    dependency_role: Mapped[str] = mapped_column(String(32), default="PREMISE")


class LectureClaimEvidence(Base):
    __tablename__ = "lecture_claim_evidence"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_claims.id", ondelete="CASCADE")
    )
    evidence_kind: Mapped[EvidenceKind] = mapped_column(
        _enum(EvidenceKind, "lecture_evidence_kind")
    )
    evidence_item_id: Mapped[str] = mapped_column(String(255))
    package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="RESTRICT")
    )
    binding_role: Mapped[EvidenceBindingRole] = mapped_column(
        _enum(EvidenceBindingRole, "evidence_binding_role")
    )
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class LectureCitation(Base):
    __tablename__ = "lecture_citations"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    lecture_master_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_master_versions.id", ondelete="CASCADE")
    )
    claim_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_claims.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[CitationKind] = mapped_column(_enum(CitationKind, "citation_kind"))
    package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="RESTRICT")
    )
    citation_data: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class LectureRitualLink(Base):
    __tablename__ = "lecture_ritual_links"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    lecture_master_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_master_versions.id", ondelete="CASCADE")
    )
    package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="RESTRICT")
    )
    ritual_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("ritual.ritual_versions.id", ondelete="RESTRICT")
    )
    relation_type: Mapped[str] = mapped_column(String(64))
    optional: Mapped[bool] = mapped_column(Boolean, default=True)
    safety_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class ValidationRun(Base):
    __tablename__ = "validation_runs"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    lecture_master_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_master_versions.id", ondelete="CASCADE")
    )
    valid: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ValidationFinding(Base):
    __tablename__ = "validation_findings"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    validation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.validation_runs.id", ondelete="CASCADE")
    )
    dimension: Mapped[ValidationDimension] = mapped_column(
        _enum(ValidationDimension, "lecture_validation_dimension")
    )
    code: Mapped[str] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    blocking: Mapped[bool] = mapped_column(Boolean, default=True)


class MasterExport(Base):
    __tablename__ = "master_exports"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    lecture_master_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_master_versions.id", ondelete="RESTRICT")
    )
    export_version: Mapped[str] = mapped_column(String(32), default="1")
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
