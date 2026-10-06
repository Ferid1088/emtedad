from types import SimpleNamespace
from typing import cast

from app.content_strategy.models import (
    ContentTopic,
    EditorialLanguageTrack,
    EditorialProject,
    PersianDraft,
    TopicStrategyNode,
)
from app.content_strategy.text_library import _origin, _status


def test_text_library_status_uses_published_language_completeness() -> None:
    project = SimpleNamespace(status="RESEARCH_PENDING")
    approved = SimpleNamespace(status="PERSIAN_APPROVED")
    tracks = {
        language: SimpleNamespace(voice_ready_text="voice")
        for language in ("fa", "de", "en", "ar")
    }

    assert _status(
        cast(dict[str, EditorialLanguageTrack], tracks),
        cast(PersianDraft, approved),
        cast(EditorialProject, project),
    ) == ("VOICE_READY", "Voice Ready")


def test_text_library_origin_prefers_strategy_node() -> None:
    project = SimpleNamespace()
    topic = SimpleNamespace(origin="AI_SUGGESTED")
    node = SimpleNamespace()

    assert _origin(
        cast(EditorialProject, project),
        cast(ContentTopic, topic),
        cast(TopicStrategyNode, node),
    ) == ("STRATEGY", "Historisches Strategiethema")
    assert _origin(
        cast(EditorialProject, project), cast(ContentTopic, topic), None
    ) == ("AI_SUGGESTED", "KI-Thema")
