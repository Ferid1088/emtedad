"""Versioned Ayin Spine, ResearchPlan, and frozen ResearchPackage models."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PostgresSchema
from app.ops.assets.models import utc_now
from app.research.domain import (
    EvidenceSelectionRole,
    PackageIssueSeverity,
    PackageStatus,
    ResearchPlanStatus,
    ResearchProjectStatus,
    ResearchQuestionKind,
    ResearchQuestionStatus,
    SpineConceptRole,
    SpineStatus,
)

CORE = PostgresSchema.CORE.value
CONTENT = PostgresSchema.CONTENT.value
KNOWLEDGE = PostgresSchema.KNOWLEDGE.value
RETRIEVAL = PostgresSchema.RETRIEVAL.value
RITUAL = PostgresSchema.RITUAL.value


def _enum(enum_type: type[Any], name: str) -> ENUM:
    return ENUM(
        enum_type,
        name=name,
        schema=CONTENT,
        values_callable=lambda members: [member.value for member in members],
    )


class ResearchProject(Base):
    """Human research request; no lecture or publication object is implied."""

    __tablename__ = "research_projects"
    __table_args__ = ({"schema": CONTENT},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    human_question: Mapped[str] = mapped_column(Text)
    status: Mapped[ResearchProjectStatus] = mapped_column(
        _enum(ResearchProjectStatus, "research_project_status"),
        default=ResearchProjectStatus.DRAFT,
    )
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class AyinSpine(Base):
    """One source-pinned interpretation boundary for a question."""

    __tablename__ = "ayin_spines"
    __table_args__ = (
        UniqueConstraint("research_project_id", "version_number"),
        CheckConstraint("version_number > 0", name="positive_version"),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="valid_input_hash"),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    research_project_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_projects.id", ondelete="RESTRICT"), index=True
    )
    canon_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.canon_versions.id", ondelete="RESTRICT")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    central_human_question: Mapped[str] = mapped_column(Text)
    canonical_question: Mapped[str] = mapped_column(Text)
    discourse_types: Mapped[list[str]] = mapped_column(JSONB)
    prohibited_conflations: Mapped[list[str]] = mapped_column(JSONB)
    optional_ritual_links: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[SpineStatus] = mapped_column(
        _enum(SpineStatus, "spine_status"), default=SpineStatus.DRAFT
    )
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class AyinSpineConcept(Base):
    __tablename__ = "ayin_spine_concepts"
    __table_args__ = (
        UniqueConstraint("ayin_spine_id", "concept_version_id"),
        ForeignKeyConstraint(
            ["concept_version_id", "canon_version_id"],
            [
                f"{CORE}.ayin_concept_versions.id",
                f"{CORE}.ayin_concept_versions.canon_version_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": CONTENT},
    )

    ayin_spine_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.ayin_spines.id", ondelete="CASCADE"), primary_key=True
    )
    concept_version_id: Mapped[UUID] = mapped_column(primary_key=True)
    canon_version_id: Mapped[UUID]
    role: Mapped[SpineConceptRole] = mapped_column(
        _enum(SpineConceptRole, "spine_concept_role")
    )


class AyinSpinePrinciple(Base):
    __tablename__ = "ayin_spine_principles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["principle_version_id", "canon_version_id"],
            [
                f"{CORE}.ayin_principle_versions.id",
                f"{CORE}.ayin_principle_versions.canon_version_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": CONTENT},
    )

    ayin_spine_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.ayin_spines.id", ondelete="CASCADE"), primary_key=True
    )
    principle_version_id: Mapped[UUID] = mapped_column(primary_key=True)
    canon_version_id: Mapped[UUID]


class AyinSpineDistinction(Base):
    __tablename__ = "ayin_spine_distinctions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["distinction_version_id", "canon_version_id"],
            [
                f"{CORE}.ayin_distinction_versions.id",
                f"{CORE}.ayin_distinction_versions.canon_version_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": CONTENT},
    )

    ayin_spine_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.ayin_spines.id", ondelete="CASCADE"), primary_key=True
    )
    distinction_version_id: Mapped[UUID] = mapped_column(primary_key=True)
    canon_version_id: Mapped[UUID]


class AyinSpineOpenQuestion(Base):
    __tablename__ = "ayin_spine_open_questions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["open_question_version_id", "canon_version_id"],
            [
                f"{CORE}.ayin_open_question_versions.id",
                f"{CORE}.ayin_open_question_versions.canon_version_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": CONTENT},
    )

    ayin_spine_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.ayin_spines.id", ondelete="CASCADE"), primary_key=True
    )
    open_question_version_id: Mapped[UUID] = mapped_column(primary_key=True)
    canon_version_id: Mapped[UUID]


class AyinSpinePassage(Base):
    __tablename__ = "ayin_spine_passages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["passage_id", "canon_version_id"],
            [f"{CORE}.canon_passages.id", f"{CORE}.canon_passages.canon_version_id"],
            ondelete="RESTRICT",
        ),
        {"schema": CONTENT},
    )

    ayin_spine_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.ayin_spines.id", ondelete="CASCADE"), primary_key=True
    )
    passage_id: Mapped[UUID] = mapped_column(primary_key=True)
    canon_version_id: Mapped[UUID]
    role: Mapped[str] = mapped_column(String(64), default="GROUNDING")


class ResearchPlan(Base):
    """Versioned research instructions from a specialist spine or lesson."""

    __tablename__ = "research_plans"
    __table_args__ = (
        UniqueConstraint("ayin_spine_id", "version_number"),
        UniqueConstraint(
            "lesson_id",
            "lesson_canon_hash",
            "version_number",
            name="uq_research_plan_lesson_version",
        ),
        CheckConstraint("version_number > 0", name="positive_version"),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="valid_input_hash"),
        CheckConstraint(
            "(ayin_spine_id IS NOT NULL AND lesson_id IS NULL "
            "AND lesson_canon_hash IS NULL "
            "AND lesson_content_package_snapshot IS NULL) "
            "OR (ayin_spine_id IS NULL AND lesson_id IS NOT NULL "
            "AND lesson_canon_hash IS NOT NULL "
            "AND lesson_content_package_snapshot IS NOT NULL)",
            name="valid_research_plan_origin",
        ),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ayin_spine_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.ayin_spines.id", ondelete="RESTRICT"),
        index=True,
        nullable=True,
    )
    lesson_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    lesson_canon_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lesson_content_package_snapshot: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    human_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_provenance: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    version_number: Mapped[int] = mapped_column(Integer)
    manasek_relevant: Mapped[bool] = mapped_column(Boolean, default=False)
    manasek_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    prohibited_conflations: Mapped[list[str]] = mapped_column(JSONB)
    retrieval_configuration: Mapped[dict[str, object]] = mapped_column(JSONB)
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[ResearchPlanStatus] = mapped_column(
        _enum(ResearchPlanStatus, "research_plan_status"),
        default=ResearchPlanStatus.DRAFT,
    )
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ResearchPlanQuestion(Base):
    __tablename__ = "research_plan_questions"
    __table_args__ = (
        UniqueConstraint("research_plan_id", "ordinal"),
        CheckConstraint("ordinal > 0", name="positive_ordinal"),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    research_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_plans.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[ResearchQuestionKind] = mapped_column(
        _enum(ResearchQuestionKind, "research_question_kind")
    )
    question: Mapped[str] = mapped_column(Text)
    retrieval_text: Mapped[str] = mapped_column(Text)
    requires_counterevidence: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[ResearchQuestionStatus] = mapped_column(
        _enum(ResearchQuestionStatus, "research_question_status"),
        default=ResearchQuestionStatus.OPEN,
    )


class ResearchPackage(Base):
    """Frozen retrieval/evidence snapshot consumed by later writing phases."""

    __tablename__ = "research_packages"
    __table_args__ = (
        UniqueConstraint("research_project_id", "package_version"),
        CheckConstraint("package_version > 0", name="positive_package_version"),
        CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="valid_input_hash"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="valid_content_hash"),
        CheckConstraint(
            "(lesson_id IS NOT NULL AND lesson_canon_hash IS NOT NULL "
            "AND lesson_content_package_version IS NOT NULL "
            "AND lesson_content_package_snapshot IS NOT NULL "
            "AND ayin_spine_id IS NULL AND research_plan_id IS NOT NULL "
            "AND canon_version_id IS NULL) OR "
            "(lesson_id IS NULL AND ayin_spine_id IS NOT NULL "
            "AND research_plan_id IS NOT NULL AND canon_version_id IS NOT NULL)",
            name="valid_research_origin",
        ),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    research_project_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_projects.id", ondelete="RESTRICT"), index=True
    )
    ayin_spine_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.ayin_spines.id", ondelete="RESTRICT"), nullable=True
    )
    research_plan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTENT}.research_plans.id", ondelete="RESTRICT"), nullable=True
    )
    canon_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CORE}.canon_versions.id", ondelete="RESTRICT"), nullable=True
    )
    lesson_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    lesson_canon_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lesson_content_package_version: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    lesson_content_package_snapshot: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    retrieval_configuration_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.configurations.id", ondelete="RESTRICT")
    )
    package_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[PackageStatus] = mapped_column(
        _enum(PackageStatus, "research_package_status"), default=PackageStatus.BUILDING
    )
    retrieval_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    unresolved_issues: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    input_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    frozen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ResearchPackageAyinPassage(Base):
    __tablename__ = "research_package_ayin_passages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["passage_id", "canon_version_id"],
            [f"{CORE}.canon_passages.id", f"{CORE}.canon_passages.canon_version_id"],
            ondelete="RESTRICT",
        ),
        {"schema": CONTENT},
    )
    package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    passage_id: Mapped[UUID] = mapped_column(primary_key=True)
    canon_version_id: Mapped[UUID]


class ResearchPackageAyinConcept(Base):
    __tablename__ = "research_package_ayin_concepts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["concept_version_id", "canon_version_id"],
            [
                f"{CORE}.ayin_concept_versions.id",
                f"{CORE}.ayin_concept_versions.canon_version_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": CONTENT},
    )
    package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    concept_version_id: Mapped[UUID] = mapped_column(primary_key=True)
    canon_version_id: Mapped[UUID]


class ResearchPackageAyinPrinciple(Base):
    __tablename__ = "research_package_ayin_principles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["principle_version_id", "canon_version_id"],
            [
                f"{CORE}.ayin_principle_versions.id",
                f"{CORE}.ayin_principle_versions.canon_version_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": CONTENT},
    )
    package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    principle_version_id: Mapped[UUID] = mapped_column(primary_key=True)
    canon_version_id: Mapped[UUID]


class ResearchPackageAyinDistinction(Base):
    __tablename__ = "research_package_ayin_distinctions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["distinction_version_id", "canon_version_id"],
            [
                f"{CORE}.ayin_distinction_versions.id",
                f"{CORE}.ayin_distinction_versions.canon_version_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": CONTENT},
    )
    package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    distinction_version_id: Mapped[UUID] = mapped_column(primary_key=True)
    canon_version_id: Mapped[UUID]


class ResearchPackageAyinOpenQuestion(Base):
    __tablename__ = "research_package_ayin_open_questions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["open_question_version_id", "canon_version_id"],
            [
                f"{CORE}.ayin_open_question_versions.id",
                f"{CORE}.ayin_open_question_versions.canon_version_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": CONTENT},
    )
    package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    open_question_version_id: Mapped[UUID] = mapped_column(primary_key=True)
    canon_version_id: Mapped[UUID]


class ResearchPackageExternalChunk(Base):
    __tablename__ = "research_package_external_chunks"
    __table_args__ = (
        UniqueConstraint("package_id", "chunk_id"),
        {"schema": CONTENT},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.chunks.id", ondelete="RESTRICT")
    )
    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.source_versions.id", ondelete="RESTRICT")
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    selection_role: Mapped[EvidenceSelectionRole] = mapped_column(
        _enum(EvidenceSelectionRole, "evidence_selection_role")
    )
    retrieval_result_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{RETRIEVAL}.results.id", ondelete="RESTRICT"), nullable=True
    )


class ResearchPackageExternalClaim(Base):
    __tablename__ = "research_package_external_claims"
    __table_args__ = (
        ForeignKeyConstraint(
            ["claim_id", "source_version_id", "source_segment_id"],
            [
                f"{KNOWLEDGE}.external_claims.id",
                f"{KNOWLEDGE}.external_claims.source_version_id",
                f"{KNOWLEDGE}.external_claims.source_segment_id",
            ],
            ondelete="RESTRICT",
        ),
        {"schema": CONTENT},
    )
    package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    claim_id: Mapped[UUID] = mapped_column(primary_key=True)
    source_version_id: Mapped[UUID]
    source_segment_id: Mapped[UUID]


class ResearchPackageExternalWork(Base):
    __tablename__ = "research_package_external_works"
    __table_args__ = ({"schema": CONTENT},)
    package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    work_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.works.id", ondelete="RESTRICT"), primary_key=True
    )


class ResearchPackageExternalPerson(Base):
    __tablename__ = "research_package_external_people"
    __table_args__ = ({"schema": CONTENT},)
    package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    person_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.people.id", ondelete="RESTRICT"), primary_key=True
    )


class ResearchPackageDialogueRelation(Base):
    __tablename__ = "research_package_dialogue_relations"
    __table_args__ = ({"schema": CONTENT},)
    package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    relation_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.dialogue_relations.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    review_status: Mapped[str] = mapped_column(String(32))
    selection_role: Mapped[EvidenceSelectionRole] = mapped_column(
        _enum(EvidenceSelectionRole, "evidence_selection_role")
    )


class ResearchPackageRitualVersion(Base):
    __tablename__ = "research_package_ritual_versions"
    __table_args__ = ({"schema": CONTENT},)
    package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ritual_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{RITUAL}.ritual_versions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    selection_role: Mapped[EvidenceSelectionRole] = mapped_column(
        _enum(EvidenceSelectionRole, "evidence_selection_role")
    )


class ResearchPackageIssue(Base):
    __tablename__ = "research_package_issues"
    __table_args__ = ({"schema": CONTENT},)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    package_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.research_packages.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(128))
    severity: Mapped[PackageIssueSeverity] = mapped_column(
        _enum(PackageIssueSeverity, "package_issue_severity")
    )
    message: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
