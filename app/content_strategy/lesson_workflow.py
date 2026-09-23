"""Bridge canonical lessons into the existing editorial-project workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.content_strategy.lesson_canon import (
    LessonCanonRepository,
    LessonContentPackage,
)
from app.content_strategy.models import EditorialProject

LESSON_SOURCE_TYPE = "LESSON_CANON"


@dataclass(frozen=True, slots=True)
class LessonProjectMetadata:
    """Owner-facing lesson identity persisted with an editorial project."""

    lesson_id: str
    number: int
    total: int
    title: str
    canon_hash: str
    package_version: str


def lesson_project_metadata(
    project: EditorialProject,
) -> LessonProjectMetadata | None:
    """Read lesson provenance only from an explicitly typed project snapshot."""

    snapshot = getattr(project, "strategy_topic_snapshot", None)
    if not snapshot or snapshot.get("source_type") != LESSON_SOURCE_TYPE:
        return None
    try:
        return LessonProjectMetadata(
            lesson_id=str(snapshot["lesson_id"]),
            number=int(cast(int, snapshot["lesson_number"])),
            total=int(cast(int, snapshot["lesson_count"])),
            title=str(snapshot["lesson_title"]),
            canon_hash=str(snapshot["lesson_canon_hash"]),
            package_version=str(snapshot["lesson_content_package_version"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def lesson_package_from_project(
    project: EditorialProject,
) -> LessonContentPackage | None:
    """Return the pinned package snapshot rather than silently loading a revision."""

    snapshot = getattr(project, "strategy_topic_snapshot", None)
    if not snapshot or snapshot.get("source_type") != LESSON_SOURCE_TYPE:
        return None
    package = snapshot.get("lesson_content_package_snapshot")
    if not isinstance(package, dict):
        return None
    return LessonContentPackage.model_validate(package)


def lesson_project_snapshot(
    repository: LessonCanonRepository,
    package: LessonContentPackage,
) -> dict[str, object]:
    """Create the immutable lesson package snapshot used by an existing project."""

    return {
        "source_type": LESSON_SOURCE_TYPE,
        "lesson_id": package.lesson_id,
        "lesson_number": repository.ordinal(package.lesson_id),
        "lesson_count": repository.lesson_count,
        "lesson_title": package.canonical_lesson_title,
        "lesson_canon_hash": package.lesson_canon_hash,
        "lesson_content_package_version": package.package_version,
        "lesson_content_package_snapshot": package.model_dump(mode="json"),
    }


async def create_lesson_project(
    session: AsyncSession,
    repository: LessonCanonRepository,
    lesson_id: str,
    *,
    owner_prompt: str | None = None,
    target_duration_minutes: int | None = None,
) -> EditorialProject:
    """Start a lesson in the established EditorialProject pipeline."""

    package = repository.package(lesson_id)
    project = EditorialProject(
        strategy_topic_snapshot=lesson_project_snapshot(repository, package),
        title=package.canonical_lesson_title,
        human_question=package.central_question or package.canonical_lesson_title,
        owner_prompt=owner_prompt,
        target_duration_minutes=target_duration_minutes,
        status="RESEARCH_PENDING",
    )
    session.add(project)
    await session.flush()
    return project
