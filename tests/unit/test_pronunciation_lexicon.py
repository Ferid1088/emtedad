"""Owner pronunciation lexicon: routes, navigation, and input validation."""

from pathlib import Path

import pytest

from app.db.session import Database
from app.localization.lexicon import PronunciationLexiconService
from app.web.routes import router as owner_router


def _service() -> PronunciationLexiconService:
    # Engine creation is lazy; validation happens before any connection.
    return PronunciationLexiconService(
        Database("postgresql+psycopg://emtedad:test-only@127.0.0.1:5432/emtedad")
    )


def test_lexicon_routes_are_registered() -> None:
    paths = {getattr(route, "path", "") for route in owner_router.routes}
    assert {
        "/lexicon",
        "/lexicon/preview",
        "/lexicon/{entry_id}/approve",
        "/lexicon/{entry_id}/deprecate",
    } <= paths


def test_primary_navigation_contains_lexicon() -> None:
    template = (
        Path(__file__).parents[2] / "app" / "web" / "templates" / "base.html"
    ).read_text(encoding="utf-8")

    assert "('/lexicon', 'Lexikon')" in template


def test_lexicon_template_exposes_review_lifecycle() -> None:
    template = (
        Path(__file__).parents[2] / "app" / "web" / "templates" / "lexicon.html"
    ).read_text(encoding="utf-8")

    assert 'action="/lexicon"' in template
    assert 'action="/lexicon/preview"' in template
    assert '/approve"' in template
    assert '/deprecate"' in template
    assert "Freigeben" in template
    assert "Vorschlagen" in template


async def test_propose_rejects_invalid_input_without_database() -> None:
    service = _service()
    with pytest.raises(ValueError, match="unsupported language"):
        await service.propose(
            language="xx",
            written_form="تست",
            preferred_pronunciation="تِست",
        )
    with pytest.raises(ValueError, match="required"):
        await service.propose(
            language="fa",
            written_form="   ",
            preferred_pronunciation="تِست",
        )
    with pytest.raises(ValueError, match="unsupported criticality"):
        await service.propose(
            language="fa",
            written_form="تست",
            preferred_pronunciation="تِست",
            criticality="URGENT",
        )
