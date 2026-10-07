"""Studio research page renders text, video and image results."""

import pytest

from app.search_engine.models import SearchHit, SearchKind
from tests.integration.test_studio_ui import studio_client  # noqa: F401

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("kind", ["text", "video", "image"])
def test_research_page_renders_results(
    studio_client,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    import app.search_engine.engine as engine_module

    async def fake_search(self, queries, *, kind, topic, per_query=15, limit=40):  # type: ignore[no-untyped-def]
        assert set(queries) == {"fa", "en"}
        return [
            SearchHit(
                kind,
                "عرفان و فلسفه",
                "https://www.youtube.com/watch?v=abcdefghijk"
                if kind is SearchKind.VIDEO
                else "https://plato.stanford.edu/entries/mysticism/",
                "fa",
                snippet="snippet",
                image_url="https://img.example/x.jpg",
                domain="plato.stanford.edu",
                quality_category="akademisch",
                quality_weight=0.95,
                score=0.9,
                found_by=["a", "b"],
            )
        ]

    monkeypatch.setattr(engine_module.SearchEngine, "search", fake_search)
    client, _ = studio_client
    page = client.get(f"/studio/research?q=عرفان&kind={kind}&plan=0")
    assert page.status_code == 200
    assert "عرفان و فلسفه" in page.text
    assert "akademisch" in page.text
    if kind == "video":
        assert "Als Ressource importieren" in page.text
    if kind == "text":
        assert "Als Ressource übernehmen" in page.text
    if kind == "image":
        assert "Lizenz vor Verwendung prüfen" in page.text
