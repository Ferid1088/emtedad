"""Versioned argument and narrative plans for generic productions."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.content_engine.domain import (
    DraftStatus,
    FindingSeverity,
    FindingStatus,
    PlanStatus,
    ReviewRunStatus,
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
    target_duration_minutes: Mapped[float] = mapped_column(Float)
    actual_word_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    # Which owner-authorized review cycle produced this draft via
    # revise_draft. NULL for initial/regenerated drafts — only revisions
    # consume the per-cycle automatic revision budget.
    revision_cycle: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ReviewCycle(Base):
    """Owner-authorized review/revision cycle for one brief.

    The automatic revision budget applies per cycle, not per brief
    lifetime: when a cycle exhausts its rounds the pipeline stops at
    OWNER_REVIEW_REQUIRED until the owner explicitly starts the next
    cycle by inserting the next row. History is never renumbered —
    ReviewRuns keep their global ``round_number`` and record which
    cycle they belong to via ``ReviewRun.cycle_number``.
    """

    __tablename__ = "review_cycles"
    __table_args__ = (
        UniqueConstraint("content_brief_id", "cycle_number"),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    content_brief_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.content_briefs.id", ondelete="CASCADE"),
        index=True,
    )
    cycle_number: Mapped[int] = mapped_column(Integer)
    started_by: Mapped[str] = mapped_column(String(64), default="owner")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ReviewRun(Base):
    """One persisted critic pass over an exact draft version+hash.

    Findings alone can never prove a review happened — a completed run
    with finding_count=0 is a truthful clean review, while missing runs
    mean review never ran. Only the latest COMPLETED run matching the
    current draft id+version+hash can certify the draft.
    """

    __tablename__ = "review_runs"
    __table_args__ = (
        UniqueConstraint("content_brief_id", "round_number"),
        # Mirrors migration i1a2b3c4d5e6: at most one PENDING/RUNNING run
        # per exact draft state — concurrent review POSTs cannot create
        # ambiguous active runs; completed history stays unrestricted.
        Index(
            "uq_review_runs_active_draft",
            "script_draft_id",
            "draft_hash",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'RUNNING')"),
        ),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    content_brief_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.content_briefs.id", ondelete="CASCADE"),
        index=True,
    )
    script_draft_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.script_drafts.id", ondelete="CASCADE"),
        index=True,
    )
    draft_version: Mapped[int] = mapped_column(Integer)
    draft_hash: Mapped[str] = mapped_column(String(64))
    round_number: Mapped[int] = mapped_column(Integer)
    # Which owner-authorized review cycle this run belongs to. Runs that
    # predate cycles count as the implicit first cycle (1).
    cycle_number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[ReviewRunStatus] = mapped_column(
        _enum(ReviewRunStatus, "review_run_status"),
        default=ReviewRunStatus.RUNNING,
    )
    critic_profile_version: Mapped[str] = mapped_column(String(64))
    critics_requested: Mapped[int] = mapped_column(Integer, default=0)
    critics_completed: Mapped[int] = mapped_column(Integer, default=0)
    finding_count: Mapped[int] = mapped_column(Integer, default=0)
    blocking_count: Mapped[int] = mapped_column(Integer, default=0)
    # WARNING-severity findings count as major under the owner policy
    # (warning blocks approval unless waived).
    major_count: Mapped[int] = mapped_column(Integer, default=0)
    minor_count: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
    review_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.review_runs.id", ondelete="SET NULL"),
        nullable=True,
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
    # WHO resolved/recommended on this finding and WHY. A waiver is an
    # owner editorial decision — the actor and justification are
    # persisted so agent recommendations never masquerade as owner
    # approval.
    resolution_actor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
