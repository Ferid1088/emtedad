from pathlib import Path

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
        "/archive",
    } <= paths


def test_primary_navigation_uses_lessons_not_strategy_tree() -> None:
    template = (
        Path(__file__).parents[2] / "app" / "web" / "templates" / "base.html"
    ).read_text(encoding="utf-8")

    assert "('/lessons', 'Lektionen')" in template
    assert "('/strategy', 'Themenbaum')" not in template


def test_overlap_is_deterministic() -> None:
    assert (
        TopicSuggestionService._overlap("pattern and change", "pattern and change")
        == 1.0
    )
    assert TopicSuggestionService._overlap("one", "two") == 0.0
