"""Owner-facing lesson catalog assembled from canon and editorial state."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.content_strategy.lesson_canon import (
    CoreConceptDefinition,
    LessonCanonRepository,
    LessonContentPackage,
)
from app.content_strategy.text_library import TextLibraryItem, load_library_items


@dataclass(frozen=True, slots=True)
class LessonCatalogItem:
    """A canonical lesson enriched with real production state."""

    package: LessonContentPackage
    number: int
    total: int
    concepts: tuple[CoreConceptDefinition, ...]
    prerequisite_count: int
    related_count: int
    project_count: int
    status_key: str
    status_label: str
    published: bool
    prerequisites_met: bool

    @property
    def excerpt(self) -> str:
        text = " ".join(self.package.canonical_lesson_explanation.split())
        return text if len(text) <= 260 else f"{text[:257].rstrip()}…"


@dataclass(frozen=True, slots=True)
class LessonProgress:
    total: int
    published: int
    in_progress: int
    open: int
    translations: dict[str, int]
    voice_ready: dict[str, int]


_STATUS_PRIORITY = {
    "NOT_STARTED": 0,
    "RESEARCH_PENDING": 1,
    "RESEARCH_READY": 2,
    "TEXT_AVAILABLE": 3,
    "IN_REVIEW": 4,
    "PERSIAN_APPROVED": 5,
    "TRANSLATIONS": 6,
    "COMPLETE": 7,
    "VOICE_READY": 8,
    "VIDEO_READY": 9,
    "PUBLISHED": 10,
}


def _best_project_status(
    projects: list[TextLibraryItem],
) -> tuple[str, str]:
    if not projects:
        return "NOT_STARTED", "Noch nicht begonnen"
    best = max(
        projects,
        key=lambda item: _STATUS_PRIORITY.get(item.status_key, 1),
    )
    return best.status_key, best.status_label


def _concepts_for_package(
    repository: LessonCanonRepository,
    package: LessonContentPackage,
) -> tuple[CoreConceptDefinition, ...]:
    """Use only canon relations to associate lessons with registry concepts."""

    related_ids = {
        package.lesson_id,
        *package.prerequisites,
        *(relation.to_lesson_id for relation in package.lesson_relations),
        *(
            relation.from_lesson_id
            for relation in repository.incoming_relations(package.lesson_id)
        ),
    }
    return tuple(
        CoreConceptDefinition(
            lesson_id=concept.lesson_id,
            title_fa=concept.title_fa,
            locked_definition_fa=concept.text_fa,
        )
        for concept in repository.core_concepts()
        if concept.lesson_id in related_ids
    )


async def load_lesson_catalog(
    session: AsyncSession,
    repository: LessonCanonRepository,
) -> tuple[list[LessonCatalogItem], LessonProgress]:
    """Join the file-backed canon to current production records without mutation."""

    library_items = await load_library_items(session, status=None)
    projects_by_lesson: dict[str, list[TextLibraryItem]] = {}
    for item in library_items:
        if item.lesson is not None:
            projects_by_lesson.setdefault(item.lesson.lesson_id, []).append(item)

    items: list[LessonCatalogItem] = []
    completed_lessons = {
        lesson_id
        for lesson_id, projects in projects_by_lesson.items()
        if any(project.drafts or project.tracks for project in projects)
    }
    translation_lessons: dict[str, set[str]] = {
        language: set() for language in ("fa", "de", "en", "ar")
    }
    voice_lessons: dict[str, set[str]] = {
        language: set() for language in ("fa", "de", "en", "ar")
    }
    for lesson_id, projects in projects_by_lesson.items():
        for project in projects:
            if project.approved_persian is not None:
                translation_lessons["fa"].add(lesson_id)
            for language, track in project.tracks.items():
                if language in translation_lessons:
                    translation_lessons[language].add(lesson_id)
                    if track.voice_ready_text:
                        voice_lessons[language].add(lesson_id)

    for number, lesson in enumerate(repository.lessons(), start=1):
        package = repository.package(lesson.lesson_id)
        lesson_projects = projects_by_lesson.get(lesson.lesson_id, [])
        status_key, status_label = _best_project_status(lesson_projects)
        items.append(
            LessonCatalogItem(
                package=package,
                number=number,
                total=repository.lesson_count,
                concepts=_concepts_for_package(repository, package),
                prerequisite_count=len(package.prerequisites),
                related_count=len(repository.outgoing_relations(lesson.lesson_id))
                + len(repository.incoming_relations(lesson.lesson_id)),
                project_count=len(lesson_projects),
                status_key=status_key,
                status_label=status_label,
                published=any(
                    project.status_key == "PUBLISHED" for project in lesson_projects
                ),
                prerequisites_met=all(
                    prerequisite in completed_lessons
                    for prerequisite in package.prerequisites
                ),
            )
        )

    published = sum(item.published for item in items)
    in_progress = sum(
        item.status_key not in {"NOT_STARTED", "PUBLISHED"} for item in items
    )
    progress = LessonProgress(
        total=repository.lesson_count,
        published=published,
        in_progress=in_progress,
        open=repository.lesson_count - published - in_progress,
        translations={
            language: len(lesson_ids)
            for language, lesson_ids in translation_lessons.items()
        },
        voice_ready={
            language: len(lesson_ids) for language, lesson_ids in voice_lessons.items()
        },
    )
    return items, progress


def filter_lesson_catalog(
    items: list[LessonCatalogItem],
    *,
    query: str = "",
    status: str = "",
    concept: str = "",
    prerequisites: str = "ALL",
    number_from: int | None = None,
    number_to: int | None = None,
) -> list[LessonCatalogItem]:
    """Filter the canonical catalog by owner-facing structured fields."""

    normalized_query = query.casefold().strip()
    filtered: list[LessonCatalogItem] = []
    for item in items:
        searchable = " ".join(
            [
                item.package.canonical_lesson_title,
                item.package.canonical_lesson_explanation,
                item.package.central_question or "",
                *(entry.title_fa for entry in item.concepts),
            ]
        ).casefold()
        if normalized_query and normalized_query not in searchable:
            continue
        if status and item.status_key != status:
            continue
        if concept and concept not in {entry.lesson_id for entry in item.concepts}:
            continue
        if prerequisites == "MET" and not item.prerequisites_met:
            continue
        if prerequisites == "OPEN" and item.prerequisites_met:
            continue
        if number_from is not None and item.number < number_from:
            continue
        if number_to is not None and item.number > number_to:
            continue
        filtered.append(item)
    return filtered
