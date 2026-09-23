"""Pydantic contracts for Phase 8 lecture architecture boundaries."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.lecture.domain import (
    LectureProjectStatus,
    LectureType,
    MasterStatus,
    PublicationLanguage,
    ValidationDimension,
)


class LectureProjectCreate(BaseModel):
    research_package_id: UUID
    lecture_type: LectureType
    working_title: str = Field(min_length=1, max_length=512)
    target_duration_seconds: int | None = Field(default=None, ge=60)
    target_audience: str | None = None
    created_by: str = "operator"


class LectureProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    research_package_id: UUID
    lecture_type: LectureType
    working_title: str
    target_duration_seconds: int | None
    target_audience: str | None
    status: LectureProjectStatus
    created_at: datetime
    updated_at: datetime


class LectureMasterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lecture_project_id: UUID
    version_number: int
    research_package_id: UUID
    research_package_version: int
    research_package_content_hash: str
    canon_version_id: UUID
    manasek_version_id: UUID | None
    package_authority: dict[str, object]
    central_human_question: str
    ending_mode: str
    architecture: dict[str, object]
    prohibited_conflations: list[str]
    uncertainty_constraints: list[str]
    status: MasterStatus
    input_hash: str
    created_by: str
    created_at: datetime
    frozen_at: datetime | None


class ValidationFindingRead(BaseModel):
    dimension: ValidationDimension
    code: str
    severity: str
    message: str
    blocking: bool


class LectureValidationRead(BaseModel):
    valid: bool
    findings: list[ValidationFindingRead]


class LectureBuildResult(BaseModel):
    master: LectureMasterRead
    validation: LectureValidationRead


class SemanticLectureMasterExport(BaseModel):
    """Standalone, language-neutral contract for all four Phase 9 targets."""

    export_version: str
    supported_languages: list[PublicationLanguage]
    master: dict[str, object]
    sections: list[dict[str, object]]
    claims: list[dict[str, object]]
    evidence: list[dict[str, object]]
    citations: list[dict[str, object]]
    ritual_links: list[dict[str, object]]
    dialogue_relations: list[dict[str, object]]
    terminology_references: list[dict[str, object]]
    validation: LectureValidationRead
