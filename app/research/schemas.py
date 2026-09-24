"""Pydantic contracts for the Phase 7 Research Engine boundaries."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.research.domain import (
    PackageIssueSeverity,
    PackageStatus,
    ResearchPlanStatus,
    ResearchProjectStatus,
    ResearchQuestionKind,
    ResearchQuestionStatus,
    SpineConceptRole,
    SpineStatus,
)
from app.retrieval.domain import QueryLanguage


class ResearchProjectCreate(BaseModel):
    human_question: str = Field(min_length=1, max_length=4000)
    created_by: str = Field(default="operator", min_length=1, max_length=255)


class ResearchProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    human_question: str
    status: ResearchProjectStatus
    created_by: str
    created_at: datetime


class SpineConceptInput(BaseModel):
    identifier: str = Field(min_length=1, max_length=255)
    role: SpineConceptRole = SpineConceptRole.SECONDARY


class AyinSpineBuildRequest(BaseModel):
    project_id: UUID
    primary_concept: str = Field(min_length=1, max_length=255)
    secondary_concepts: list[str] = Field(default_factory=list, max_length=20)
    principle_ids: list[str] = Field(default_factory=list, max_length=20)
    distinction_ids: list[str] = Field(default_factory=list, max_length=20)
    open_question_ids: list[str] = Field(default_factory=list, max_length=20)
    passage_ids: list[UUID] = Field(default_factory=list, max_length=50)
    canon_version_id: UUID | None = None
    canonical_question: str | None = Field(default=None, max_length=4000)
    prohibited_conflations: list[str] = Field(default_factory=list, max_length=50)
    optional_ritual_links: list[dict[str, object]] = Field(
        default_factory=list, max_length=20
    )
    created_by: str = Field(default="operator", min_length=1, max_length=255)


class AyinSpineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    research_project_id: UUID
    canon_version_id: UUID
    version_number: int
    central_human_question: str
    canonical_question: str
    concept_version_ids: list[UUID]
    principle_version_ids: list[UUID]
    distinction_version_ids: list[UUID]
    open_question_version_ids: list[UUID]
    passage_ids: list[UUID]
    discourse_types: list[str]
    prohibited_conflations: list[str]
    optional_ritual_links: list[dict[str, object]]
    input_hash: str
    status: SpineStatus
    created_by: str
    created_at: datetime


class ResearchQuestionInput(BaseModel):
    kind: ResearchQuestionKind
    question: str = Field(min_length=1, max_length=4000)
    retrieval_text: str | None = Field(default=None, max_length=4000)
    requires_counterevidence: bool = False


class ResearchPlanCreate(BaseModel):
    spine_id: UUID
    questions: list[ResearchQuestionInput] = Field(default_factory=list, max_length=30)
    manasek_relevant: bool = False
    manasek_reason: str | None = Field(default=None, max_length=2000)
    prohibited_conflations: list[str] = Field(default_factory=list, max_length=50)
    created_by: str = Field(default="operator", min_length=1, max_length=255)


class ResearchQuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ordinal: int
    kind: ResearchQuestionKind
    question: str
    retrieval_text: str
    requires_counterevidence: bool
    status: ResearchQuestionStatus


class ResearchPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ayin_spine_id: UUID | None
    lesson_id: str | None
    lesson_canon_hash: str | None
    lesson_content_package_snapshot: dict[str, object] | None
    human_question: str | None
    query_provenance: dict[str, object]
    version_number: int
    manasek_relevant: bool
    manasek_reason: str | None
    prohibited_conflations: list[str]
    retrieval_configuration: dict[str, object]
    input_hash: str
    status: ResearchPlanStatus
    created_by: str
    created_at: datetime
    questions: list[ResearchQuestionRead]


class ResearchPackageBuildRequest(BaseModel):
    plan_id: UUID
    language: QueryLanguage = QueryLanguage.FA
    chunking_run_id: UUID | None = None
    embedding_model_id: UUID | None = None
    max_candidates_per_question: int = Field(default=5, ge=1, le=20)
    include_manasek: bool = False
    created_by: str = Field(default="operator", min_length=1, max_length=255)


class PackageIssueRead(BaseModel):
    code: str
    severity: PackageIssueSeverity
    message: str
    resolved: bool


class PackageEvidenceCounts(BaseModel):
    ayin_passages: int
    ayin_concepts: int
    ayin_principles: int
    ayin_distinctions: int
    ayin_open_questions: int
    external_chunks: int
    external_claims: int
    external_works: int
    external_people: int
    dialogue_relations: int
    ritual_versions: int


class ResearchPackageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    research_project_id: UUID
    ayin_spine_id: UUID | None
    research_plan_id: UUID | None
    canon_version_id: UUID | None
    lesson_id: str | None
    lesson_canon_hash: str | None
    lesson_content_package_version: str | None
    lesson_content_package_snapshot: dict[str, object] | None
    retrieval_configuration_id: UUID
    package_version: int
    status: PackageStatus
    retrieval_snapshot: dict[str, object]
    unresolved_issues: list[dict[str, object]]
    input_hash: str
    content_hash: str
    created_by: str
    created_at: datetime
    frozen_at: datetime | None
    evidence_counts: PackageEvidenceCounts


class ResearchValidationReport(BaseModel):
    valid: bool
    issue_count: int
    issues: list[PackageIssueRead]


class ResearchPackageBuildResult(BaseModel):
    package: ResearchPackageRead
    cache_hit: bool
    retrieval_run_ids: list[UUID]
