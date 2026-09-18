"""Pydantic boundaries for Ayin queries and operator reports."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.ayin.domain import (
    CorpusZone,
    DiscourseType,
    DistinctionRelation,
    EditorialStatus,
    LanguageCode,
    OpenQuestionStatus,
    TermFormType,
)


class ReadModel(BaseModel):
    """Strict serialization base for read-only boundaries."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class VersionSummary(ReadModel):
    id: UUID
    status: EditorialStatus
    corpus_zone: CorpusZone
    semantic_version: str | None
    source_file_hash: str
    importer_version: str
    page_count: int
    created_at: datetime


class DocumentSummary(ReadModel):
    id: UUID
    slug: str
    title: str
    original_language: LanguageCode
    corpus_zone: CorpusZone


class DocumentDetail(DocumentSummary):
    versions: list[VersionSummary]


class ConceptVersionRead(ReadModel):
    id: UUID
    canon_version_id: UUID
    source_passage_id: UUID
    version_number: int
    definition: str
    approval_status: EditorialStatus


class ConceptRead(ReadModel):
    id: UUID
    stable_key: str
    status: EditorialStatus
    versions: list[ConceptVersionRead]


class DistinctionVersionRead(ReadModel):
    id: UUID
    canon_version_id: UUID
    source_passage_id: UUID
    version_number: int
    relation: DistinctionRelation
    right_label: str | None
    explanation: str
    discourse_type: DiscourseType
    status: EditorialStatus


class DistinctionRead(ReadModel):
    id: UUID
    stable_key: str
    left_concept_id: UUID
    versions: list[DistinctionVersionRead]


class RelationRead(ReadModel):
    id: UUID
    subject_concept_id: UUID
    relation_type: DistinctionRelation
    object_concept_id: UUID
    explanation: str
    discourse_type: DiscourseType
    canon_version_id: UUID
    source_passage_id: UUID
    status: EditorialStatus


class PrincipleVersionRead(ReadModel):
    id: UUID
    canon_version_id: UUID
    source_passage_id: UUID
    version_number: int
    statement: str
    discourse_type: DiscourseType
    status: EditorialStatus


class PrincipleRead(ReadModel):
    id: UUID
    stable_key: str
    versions: list[PrincipleVersionRead]


class OpenQuestionVersionRead(ReadModel):
    id: UUID
    canon_version_id: UUID
    source_passage_id: UUID
    version_number: int
    question: str
    context: str
    discourse_type: DiscourseType
    status: OpenQuestionStatus


class OpenQuestionRead(ReadModel):
    id: UUID
    stable_key: str
    versions: list[OpenQuestionVersionRead]


class TermFormRead(ReadModel):
    id: UUID
    canon_version_id: UUID
    source_passage_id: UUID
    language: LanguageCode
    script: str
    scope: str
    form: str
    form_type: TermFormType
    approval_status: EditorialStatus
    version: int
    effective_from: date | None
    effective_to: date | None


class TermRead(ReadModel):
    id: UUID
    stable_key: str
    concept_id: UUID | None
    status: EditorialStatus
    forms: list[TermFormRead]


class ValidationIssue(ReadModel):
    code: str
    message: str
    record_id: UUID | None = None


class ValidationReport(ReadModel):
    valid: bool
    issue_count: int
    issues: list[ValidationIssue]
