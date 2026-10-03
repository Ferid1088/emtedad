"""LEGACY_PROVENANCE_ONLY: lesson package snapshot models.

The file-backed 100-lesson canon, its ``LessonCanonRepository``, and the
exactly-100 validation have been retired with the lesson production path
(Phase 21). These pydantic models remain only so historical database
snapshots — ``strategy_topic_snapshot.lesson_content_package_snapshot`` on
``EditorialProject`` and ``lesson_content_package_snapshot`` on research
rows — stay decodable and readable. No new production may be built from
them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AyinProvenance(BaseModel):
    """Optional source-level provenance supplied by a future canon revision."""

    model_config = ConfigDict(extra="forbid")

    source_version: str | None = None
    passage_ids: list[str] = Field(default_factory=list)
    pages: list[int] = Field(default_factory=list)
    related_concepts: list[str] = Field(default_factory=list)
    relevant_distinctions: list[str] = Field(default_factory=list)


class LessonRelation(BaseModel):
    """One directed, canon-supplied relationship between lessons."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_lesson_id: str = Field(alias="from", min_length=1)
    to_lesson_id: str = Field(alias="to", min_length=1)
    is_prerequisite: bool
    explanation_fa: str = Field(min_length=1)


class CoreConceptDefinition(BaseModel):
    """A directly selected definition from a related core-concept lesson."""

    lesson_id: str
    title_fa: str
    locked_definition_fa: str


class LessonContentPackage(BaseModel):
    """LEGACY_PROVENANCE_ONLY: immutable writer input snapshot of one lesson."""

    package_version: str = "1"
    catalog_version: str = "100-lessons-v1"
    lesson_canon_hash: str
    lesson_id: str
    lesson_number: int | None = None
    lesson_count: int = 100
    chapter: int
    chapter_title_fa: str
    order_in_chapter: int
    level: int
    canonical_lesson_title: str
    is_core_concept: bool
    central_question: str | None
    canonical_lesson_explanation: str
    core_concepts: list[str]
    required_distinctions: list[str]
    conceptual_boundaries: list[str]
    prerequisites: list[str]
    lesson_relations: list[LessonRelation]
    canonical_relations_section_fa: str
    what_this_lesson_develops: list[str]
    what_should_remain_open: list[str]
    ayin_provenance: AyinProvenance | None
    provenance_complete: bool
    review_items: list[str]
    core_concept_registry: list[CoreConceptDefinition]
