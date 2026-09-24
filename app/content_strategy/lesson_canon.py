"""Direct, non-RAG access to the approved 100-lesson production canon."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_LESSON_CANON_ROOT = (
    Path(__file__).resolve().parents[2] / "resources" / "editorial" / "lesson_canon"
)


class AyinProvenance(BaseModel):
    """Optional source-level provenance supplied by a future canon revision."""

    model_config = ConfigDict(extra="forbid")

    source_version: str | None = None
    passage_ids: list[str] = Field(default_factory=list)
    pages: list[int] = Field(default_factory=list)
    related_concepts: list[str] = Field(default_factory=list)
    relevant_distinctions: list[str] = Field(default_factory=list)


class LessonRecord(BaseModel):
    """One approved lesson record; optional fields are never inferred."""

    model_config = ConfigDict(extra="forbid")

    lesson_id: str = Field(min_length=1)
    chapter: int = Field(ge=1)
    chapter_title_fa: str = Field(min_length=1)
    order_in_chapter: int = Field(ge=1)
    level: int = Field(ge=1)
    title_fa: str = Field(min_length=1)
    is_core_concept: bool
    prerequisites: list[str] = Field(default_factory=list)
    text_fa: str = Field(min_length=1)
    relations_section_fa: str = ""
    central_question: str | None = None
    core_concepts: list[str] = Field(default_factory=list)
    required_distinctions: list[str] = Field(default_factory=list)
    conceptual_boundaries: list[str] = Field(default_factory=list)
    what_this_lesson_develops: list[str] = Field(default_factory=list)
    what_should_remain_open: list[str] = Field(default_factory=list)
    ayin_provenance: AyinProvenance | None = None


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
    """Complete direct writer input for one lesson, without book retrieval."""

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


class LessonSummary(BaseModel):
    lesson_id: str
    chapter: int
    order_in_chapter: int
    title_fa: str


class LessonCanonRepository:
    """Validate and expose the file-backed approved lesson canon directly."""

    def __init__(self, root: Path = DEFAULT_LESSON_CANON_ROOT) -> None:
        self.root = root
        self._lessons_path = root / "lessons.json"
        self._relations_path = root / "lesson_relations.json"
        lesson_bytes = self._lessons_path.read_bytes()
        relation_bytes = self._relations_path.read_bytes()
        self.content_hash = sha256(lesson_bytes + b"\0" + relation_bytes).hexdigest()
        lessons_raw = json.loads(lesson_bytes)
        relations_raw = json.loads(relation_bytes)
        if not isinstance(lessons_raw, list) or not isinstance(relations_raw, list):
            raise ValueError("lesson canon files must contain JSON arrays")
        lessons = [LessonRecord.model_validate(item) for item in lessons_raw]
        relations = [LessonRelation.model_validate(item) for item in relations_raw]
        self._lessons = {item.lesson_id: item for item in lessons}
        self._relations = relations
        self._validate(lessons, relations)

    def summaries(self) -> list[LessonSummary]:
        return [
            LessonSummary(
                lesson_id=item.lesson_id,
                chapter=item.chapter,
                order_in_chapter=item.order_in_chapter,
                title_fa=item.title_fa,
            )
            for item in sorted(
                self._lessons.values(),
                key=lambda lesson: (lesson.chapter, lesson.order_in_chapter),
            )
        ]

    @property
    def lesson_count(self) -> int:
        """Return the validated number of canonical lessons."""

        return len(self._lessons)

    @property
    def relation_count(self) -> int:
        """Return the number of canon-supplied directed relationships."""

        return len(self._relations)

    def lessons(self) -> list[LessonRecord]:
        """Return canonical lesson records in stable editorial order."""

        return sorted(
            self._lessons.values(),
            key=lambda lesson: (lesson.chapter, lesson.order_in_chapter),
        )

    def core_concepts(self) -> list[LessonRecord]:
        """Return the actual core-concept records supplied by the canon."""

        return [lesson for lesson in self.lessons() if lesson.is_core_concept]

    def lesson(self, lesson_id: str) -> LessonRecord:
        """Return one canonical lesson without deriving missing content."""

        lesson = self._lessons.get(lesson_id)
        if lesson is None:
            raise ValueError(f"lesson not found in approved canon: {lesson_id}")
        return lesson

    def ordinal(self, lesson_id: str) -> int:
        """Return the one-based position in the approved 100-lesson sequence."""

        for index, lesson in enumerate(self.lessons(), start=1):
            if lesson.lesson_id == lesson_id:
                return index
        raise ValueError(f"lesson not found in approved canon: {lesson_id}")

    def outgoing_relations(self, lesson_id: str) -> list[LessonRelation]:
        self.lesson(lesson_id)
        return [
            relation
            for relation in self._relations
            if relation.from_lesson_id == lesson_id
        ]

    def incoming_relations(self, lesson_id: str) -> list[LessonRelation]:
        self.lesson(lesson_id)
        return [
            relation
            for relation in self._relations
            if relation.to_lesson_id == lesson_id
        ]

    def package(self, lesson_id: str) -> LessonContentPackage:
        lesson = self.lesson(lesson_id)
        relations = self.outgoing_relations(lesson_id)
        relevant_ids = {
            lesson_id,
            *lesson.prerequisites,
            *(relation.to_lesson_id for relation in relations),
        }
        registry = [
            CoreConceptDefinition(
                lesson_id=item.lesson_id,
                title_fa=item.title_fa,
                locked_definition_fa=item.text_fa,
            )
            for item in self._lessons.values()
            if item.is_core_concept and item.lesson_id in relevant_ids
        ]
        review_items = []
        if lesson.ayin_provenance is None:
            review_items.append("MISSING_LESSON_AYIN_PROVENANCE")
        return LessonContentPackage(
            lesson_canon_hash=self.content_hash,
            lesson_id=lesson.lesson_id,
            lesson_number=self.ordinal(lesson.lesson_id),
            lesson_count=self.lesson_count,
            chapter=lesson.chapter,
            chapter_title_fa=lesson.chapter_title_fa,
            order_in_chapter=lesson.order_in_chapter,
            level=lesson.level,
            canonical_lesson_title=lesson.title_fa,
            is_core_concept=lesson.is_core_concept,
            central_question=lesson.central_question,
            canonical_lesson_explanation=lesson.text_fa,
            core_concepts=lesson.core_concepts,
            required_distinctions=lesson.required_distinctions,
            conceptual_boundaries=lesson.conceptual_boundaries,
            prerequisites=lesson.prerequisites,
            lesson_relations=relations,
            canonical_relations_section_fa=lesson.relations_section_fa,
            what_this_lesson_develops=lesson.what_this_lesson_develops,
            what_should_remain_open=lesson.what_should_remain_open,
            ayin_provenance=lesson.ayin_provenance,
            provenance_complete=lesson.ayin_provenance is not None,
            review_items=review_items,
            core_concept_registry=sorted(
                registry, key=lambda item: _lesson_id_key(item.lesson_id)
            ),
        )

    def _validate(
        self, lessons: list[LessonRecord], relations: list[LessonRelation]
    ) -> None:
        if len(lessons) != 100:
            raise ValueError("approved lesson canon must contain exactly 100 lessons")
        if len(self._lessons) != len(lessons):
            raise ValueError("lesson IDs must be unique")
        lesson_ids = set(self._lessons)
        for lesson in lessons:
            unknown = set(lesson.prerequisites) - lesson_ids
            if unknown:
                raise ValueError(
                    f"lesson {lesson.lesson_id} has unknown prerequisites: "
                    f"{sorted(unknown)}"
                )
        for relation in relations:
            if relation.from_lesson_id not in lesson_ids:
                raise ValueError(
                    f"lesson relation has unknown source: {relation.from_lesson_id}"
                )
            if relation.to_lesson_id not in lesson_ids:
                raise ValueError(
                    f"lesson relation has unknown target: {relation.to_lesson_id}"
                )


def _lesson_id_key(lesson_id: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in lesson_id.split("."))
    except ValueError:
        return (10**9,)
