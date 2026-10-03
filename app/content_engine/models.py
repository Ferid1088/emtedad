"""Versioned argument and narrative plans for generic productions."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.content_engine.domain import (
    DraftStatus,
    FindingSeverity,
    FindingStatus,
    PlanStatus,
)
from app.db.base import Base, PostgresSchema
from app.ops.assets.models import utc_now

CONTENT = PostgresSchema.CONTENT.value


def _enum(enum_type: type[Any], name: str) -> ENUM:
    return ENUM(
        enum_type,
        name=name,
        schema=CONTENT,
        values_callable=lambda members: [member.value for member in members],
    )


class ArgumentPlan(Base):
    """Versioned argument architecture for one ContentBrief. No prose."""

    __tablename__ = "argument_plans"
    __table_args__ = (
        UniqueConstraint("content_brief_id", "version_number"),
        CheckConstraint("version_number > 0", name="positive_plan_version"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="valid_plan_hash"),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    content_brief_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.content_briefs.id", ondelete="RESTRICT"),
        index=True,
    )
    evidence_matrix_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.evidence_matrices.id", ondelete="RESTRICT")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[PlanStatus] = mapped_column(
        _enum(PlanStatus, "argument_plan_status"),
        default=PlanStatus.DRAFT,
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    provenance_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    sections: Mapped[list["ArgumentPlanSection"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class ArgumentPlanSection(Base):
    """One structural slot in an ArgumentPlan — claims, not prose."""

    __tablename__ = "argument_plan_sections"
    __table_args__ = (
        UniqueConstraint("argument_plan_id", "ordinal"),
        CheckConstraint("ordinal > 0", name="positive_section_ordinal"),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    argument_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.argument_plans.id", ondelete="CASCADE"),
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(Text)
    claim_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    evidence_item_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    story_unit_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    counterargument_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    transition_intent: Mapped[str] = mapped_column(Text, default="")
    must_include: Mapped[list[str]] = mapped_column(JSONB, default=list)
    must_not_claim: Mapped[list[str]] = mapped_column(JSONB, default=list)

    plan: Mapped[ArgumentPlan] = relationship(back_populates="sections")


class NarrativePlan(Base):
    """Versioned narrative architecture over an ArgumentPlan. No prose."""

    __tablename__ = "narrative_plans"
    __table_args__ = (
        UniqueConstraint("content_brief_id", "version_number"),
        CheckConstraint("version_number > 0", name="positive_narr_version"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="valid_narr_hash"),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    content_brief_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.content_briefs.id", ondelete="RESTRICT"),
        index=True,
    )
    argument_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.argument_plans.id", ondelete="RESTRICT")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[PlanStatus] = mapped_column(
        _enum(PlanStatus, "narrative_plan_status"),
        default=PlanStatus.DRAFT,
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    provenance_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    sections: Mapped[list["NarrativePlanSection"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class NarrativePlanSection(Base):
    """One narrative slot bound to argument sections and story units."""

    __tablename__ = "narrative_plan_sections"
    __table_args__ = (
        UniqueConstraint("narrative_plan_id", "ordinal"),
        CheckConstraint("ordinal > 0", name="positive_narr_ordinal"),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    narrative_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.narrative_plans.id", ondelete="CASCADE"),
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    narrative_role: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(Text)
    target_seconds: Mapped[int] = mapped_column(Integer, default=60)
    argument_section_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    story_unit_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    emotional_function: Mapped[str] = mapped_column(String(128), default="")
    transition_in: Mapped[str] = mapped_column(Text, default="")
    transition_out: Mapped[str] = mapped_column(Text, default="")
    opening_method: Mapped[str] = mapped_column(String(128), default="")
    ending_method: Mapped[str] = mapped_column(String(128), default="")

    plan: Mapped[NarrativePlan] = relationship(back_populates="sections")


class ScriptDraft(Base):
    """One versioned script draft for a brief — the generic Phase 14 path.

    ``editorial_project_id`` stays optional so the generic pipeline does not
    depend on the legacy lesson project tables.
    """

    __tablename__ = "script_drafts"
    __table_args__ = (
        UniqueConstraint("content_brief_id", "language", "version_number"),
        CheckConstraint("version_number > 0", name="positive_draft_version"),
        CheckConstraint("variant_index >= 0", name="nonnegative_variant"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="valid_draft_hash"),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    content_brief_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.content_briefs.id", ondelete="RESTRICT"),
        index=True,
    )
    narrative_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.narrative_plans.id", ondelete="RESTRICT")
    )
    lecture_master_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_master_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    editorial_project_id: Mapped[UUID | None] = mapped_column(nullable=True)

    language: Mapped[str] = mapped_column(String(16), default="fa")
    version_number: Mapped[int] = mapped_column(Integer)
    variant_index: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[DraftStatus] = mapped_column(
        _enum(DraftStatus, "script_draft_status"), default=DraftStatus.DRAFT
    )
    provenance_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64))
    target_duration_minutes: Mapped[int] = mapped_column(Integer)
    actual_word_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ReviewFinding(Base):
    """One critic finding. Critics never rewrite — they report."""

    __tablename__ = "review_findings"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    script_draft_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.script_drafts.id", ondelete="CASCADE"),
        index=True,
    )
    critic_role: Mapped[str] = mapped_column(String(64))
    severity: Mapped[FindingSeverity] = mapped_column(
        _enum(FindingSeverity, "finding_severity")
    )
    location: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(String(128))
    explanation: Mapped[str] = mapped_column(Text)
    correction_constraint: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[FindingStatus] = mapped_column(
        _enum(FindingStatus, "finding_status"), default=FindingStatus.OPEN
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
