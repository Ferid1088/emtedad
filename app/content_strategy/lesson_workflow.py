"""LEGACY_PROVENANCE_ONLY: read-only helpers for historical lesson projects.

The lesson production path is retired (Phase 21): ``create_lesson_project``,
``LessonCanonRepository``, and ``LessonResearchService`` are gone. What
remains reads snapshots already persisted on ``EditorialProject`` and
``ResearchPackage`` rows so historical projects stay readable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.content_strategy.lesson_canon import LessonContentPackage
from app.content_strategy.models import EditorialProject
from app.lecture.domain import MasterStatus
from app.research.domain import ResearchQuestionKind
from app.research.models import ResearchPackage

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
    package: LessonContentPackage,
    *,
    lesson_number: int | None = None,
    lesson_count: int | None = None,
) -> dict[str, object]:
    """Build the immutable lesson snapshot shape used by historical projects.

    Only needed when constructing or inspecting legacy fixture data; no
    repository or canon file is required.
    """

    return {
        "source_type": LESSON_SOURCE_TYPE,
        "lesson_id": package.lesson_id,
        "lesson_number": lesson_number or package.lesson_number,
        "lesson_count": lesson_count or package.lesson_count,
        "lesson_title": package.canonical_lesson_title,
        "lesson_canon_hash": package.lesson_canon_hash,
        "lesson_content_package_version": package.package_version,
        "lesson_content_package_snapshot": package.model_dump(mode="json"),
    }


@dataclass(frozen=True, slots=True)
class LessonResearchSummary:
    """Owner-facing state without exposing raw package records."""

    status_label: str
    badge_class: str
    result_count: int
    source_count: int
    counterevidence_count: int
    sources: tuple[str, ...]
    query_labels: tuple[str, ...]
    issues: tuple[str, ...]
    ready_for_writing: bool
    selected_sources: tuple[SelectedExternalSource, ...]
    rejected_count: int


@dataclass(frozen=True, slots=True)
class SelectedExternalSource:
    """Owner-facing reason for including one external item."""

    title: str
    role: str
    relevant_claim: str
    inclusion_reason: str


async def lesson_research_summary(
    session: AsyncSession,
    project: EditorialProject,
) -> LessonResearchSummary | None:
    """Summarize only the package currently pinned to this project."""

    if project.research_package_id is None:
        return None
    package = await session.get(ResearchPackage, project.research_package_id)
    if package is None or package.lesson_id is None:
        return None
    snapshot = package.retrieval_snapshot
    queries = snapshot.get("queries", [])
    chunks: set[str] = set()
    counter_chunks: set[str] = set()
    sources: set[str] = set()
    selected_sources: list[SelectedExternalSource] = []
    selected_source_keys: set[tuple[str, str]] = set()
    labels: list[str] = []
    role_labels = {
        "EMPIRICAL_CONTEXT": "Empirischer Kontext",
        "CONCEPTUAL_PARALLEL": "Konzeptuelle Parallele",
        "HISTORICAL_CONTEXT": "Historischer Kontext",
        "EXAMPLE": "Beispiel",
        "ILLUSTRATION": "Illustration",
        "ALTERNATIVE_EXPLANATION": "Alternative Erklärung",
        "COUNTERARGUMENT": "Gegenargument",
        "COUNTEREVIDENCE": "Gegenposition",
        "TENSION": "Spannung",
        "CHALLENGE": "Herausforderung",
        "NON_EQUIVALENCE": "Nicht gleichzusetzen",
        "OPEN_QUESTION": "Offene Frage",
    }
    if isinstance(queries, list):
        for query in queries:
            if not isinstance(query, dict):
                continue
            label = str(query.get("label") or "Externe Recherche")
            if label not in labels:
                labels.append(label)
            results = query.get("results", [])
            if not isinstance(results, list):
                continue
            for result in results:
                if not isinstance(result, dict):
                    continue
                if result.get("selected") is False:
                    continue
                chunk_id = str(result.get("chunk_id", ""))
                if chunk_id:
                    chunks.add(chunk_id)
                    if query.get("kind") == ResearchQuestionKind.COUNTEREVIDENCE.value:
                        counter_chunks.add(chunk_id)
                provenance = result.get("provenance", {})
                if isinstance(provenance, dict):
                    title = str(provenance.get("source_title") or "").strip()
                    if title:
                        sources.add(title)
                        raw_role = str(result.get("source_role") or "")
                        source_key = (chunk_id, raw_role)
                        if source_key not in selected_source_keys:
                            selected_source_keys.add(source_key)
                            selected_sources.append(
                                SelectedExternalSource(
                                    title=title,
                                    role=role_labels.get(raw_role, label),
                                    relevant_claim=str(result.get("text") or "")[:320],
                                    inclusion_reason=str(
                                        result.get("inclusion_reason")
                                        or f"Relevant für „{label}“."
                                    ),
                                )
                            )
    master_ready = False
    if project.semantic_master_id is not None:
        from app.lecture.models import LectureMasterVersion

        master = await session.get(LectureMasterVersion, project.semantic_master_id)
        master_ready = (
            master is not None
            and master.research_package_id == package.id
            and master.status is MasterStatus.READY
        )
    issue_codes = tuple(
        str(item.get("code", ""))
        for item in package.unresolved_issues
        if isinstance(item, dict) and item.get("code")
    )
    if master_ready:
        status_label, badge_class = "Bereit für den Entwurf", "success"
    elif chunks:
        status_label, badge_class = "Prüfung erforderlich", "warning"
    else:
        status_label, badge_class = "Keine externen Treffer", "warning"
    rejected_raw = snapshot.get("rejected_candidates", [])
    rejected_count = len(rejected_raw) if isinstance(rejected_raw, list) else 0
    return LessonResearchSummary(
        status_label=status_label,
        badge_class=badge_class,
        result_count=len(chunks),
        source_count=len(sources),
        counterevidence_count=len(counter_chunks),
        sources=tuple(sorted(sources)),
        query_labels=tuple(labels),
        issues=issue_codes,
        ready_for_writing=master_ready,
        selected_sources=tuple(selected_sources),
        rejected_count=rejected_count,
    )
