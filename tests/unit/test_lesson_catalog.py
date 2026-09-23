from pathlib import Path
from types import SimpleNamespace
from typing import cast

from app.content_strategy.lesson_canon import LessonCanonRepository
from app.content_strategy.lesson_catalog import LessonCatalogItem, filter_lesson_catalog
from app.content_strategy.lesson_workflow import (
    lesson_project_metadata,
    lesson_project_snapshot,
)
from app.content_strategy.models import EditorialProject


def _repository() -> LessonCanonRepository:
    return LessonCanonRepository(
        Path(__file__).parents[2] / "resources" / "editorial" / "lesson_canon"
    )


def test_lesson_catalog_searches_canonical_content_without_chunks() -> None:
    repository = _repository()
    package = repository.package("1.1")
    item = LessonCatalogItem(
        package=package,
        number=1,
        total=100,
        concepts=(),
        prerequisite_count=0,
        related_count=len(package.lesson_relations),
        project_count=0,
        status_key="NOT_STARTED",
        status_label="Noch nicht begonnen",
        published=False,
        prerequisites_met=True,
    )

    assert filter_lesson_catalog([item], query="پاسخ نهایی") == [item]
    assert filter_lesson_catalog([item], query="unrelated vector chunk") == []
    assert filter_lesson_catalog([item], status="PUBLISHED") == []


def test_lesson_project_snapshot_pins_canonical_identity() -> None:
    repository = _repository()
    package = repository.package("3.1")
    snapshot = lesson_project_snapshot(repository, package)
    project = cast(
        EditorialProject,
        SimpleNamespace(strategy_topic_snapshot=snapshot),
    )

    metadata = lesson_project_metadata(project)

    assert metadata is not None
    assert metadata.lesson_id == "3.1"
    assert metadata.total == 100
    assert metadata.title == package.canonical_lesson_title
    assert snapshot["lesson_canon_hash"] == repository.content_hash


def test_imported_canon_exposes_real_counts_and_relations() -> None:
    repository = _repository()

    assert repository.lesson_count == 100
    assert repository.relation_count == 837
    assert len(repository.core_concepts()) == 22
    assert repository.outgoing_relations("3.1")
    assert repository.incoming_relations("3.1")
