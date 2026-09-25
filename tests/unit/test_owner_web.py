from pathlib import Path

from app.content_strategy.story_library import StoryLibrary
from app.core.config import Settings
from app.main import create_app
from app.web.routes import router as owner_router
from app.web.service import TopicSuggestionService, validate_youtube_url


def test_youtube_locator_validation() -> None:
    assert (
        validate_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )


def test_invalid_youtube_locator_is_rejected() -> None:
    try:
        validate_youtube_url("https://example.com/not-youtube")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid URL must be rejected")


def test_owner_routes_are_registered(test_settings: Settings) -> None:
    _app = create_app(test_settings)
    paths = {getattr(route, "path", "") for route in owner_router.routes}
    assert {
        "/",
        "/sources",
        "/sources/new",
        "/knowledge",
        "/topics",
        "/lessons",
        "/lessons/{lesson_id}",
        "/stories",
        "/stories/{story_id}",
        "/archive",
        "/workspace/{project_id}/research",
    } <= paths


def test_primary_navigation_uses_lessons_not_strategy_tree() -> None:
    template = (
        Path(__file__).parents[2] / "app" / "web" / "templates" / "base.html"
    ).read_text(encoding="utf-8")

    assert "('/lessons', 'Lektionen')" in template
    assert "('/strategy', 'Themenbaum')" not in template


def test_story_library_is_curated_and_lesson_filterable() -> None:
    library = StoryLibrary()

    assert library.count == 50
    assert library.categories
    linked = library.for_lesson("8.8")
    assert linked
    assert all(
        any(relation.lesson_id == "8.8" for relation in story.related_lessons)
        for story in linked
    )
    assert library.search(query="اسپنکس")[0].story_id == "S01"


def test_story_bank_is_external_material_not_ayin_provenance() -> None:
    story = StoryLibrary().story("S07")

    assert story.uncertain_or_myth_fa
    assert story.sources
    assert "Ayin" not in story.narrative_fa


def test_legacy_strategy_templates_are_removed() -> None:
    templates = Path(__file__).parents[2] / "app" / "web" / "templates"

    assert not (templates / "strategy_tree.html").exists()
    assert not (templates / "strategy_topic_detail.html").exists()


def test_lesson_studio_exposes_real_external_research_action() -> None:
    template = (
        Path(__file__).parents[2]
        / "app"
        / "web"
        / "templates"
        / "editorial_workspace.html"
    ).read_text(encoding="utf-8")

    assert 'action="/workspace/{{ project.id }}/research"' in template
    assert "Externe Recherche starten" in template
    assert "Recherche starten (nächster Schritt)" not in template
    assert "Wird ausschließlich in der externen Wissensbasis gesucht." in template


def test_overlap_is_deterministic() -> None:
    assert (
        TopicSuggestionService._overlap("pattern and change", "pattern and change")
        == 1.0
    )
    assert TopicSuggestionService._overlap("one", "two") == 0.0
