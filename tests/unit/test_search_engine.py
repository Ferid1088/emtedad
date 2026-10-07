"""Emtedad search engine: SearXNG client, ranking, parallel planning."""

import asyncio
import json

import httpx
import pytest

from app.search_engine.engine import SearchEngine
from app.search_engine.models import SearchHit, SearchKind
from app.search_engine.quality import classify_domain
from app.search_engine.ranking import canonical_url, rank
from app.search_engine.searxng import SearchBackendError, SearxngClient


def _searx_transport(seen: list[dict[str, str]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen.append(params)
        lang = params["language"]
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": f"https://plato.stanford.edu/entries/x-{lang}/",
                        "title": f"Mysticism {lang}",
                        "content": "mysticism and the self",
                        "engines": ["google"],
                    },
                    {
                        "url": "https://www.reddit.com/r/x/?utm_source=a",
                        "title": "thread",
                        "content": "",
                        "engines": ["bing"],
                    },
                    {"url": "javascript:alert(1)", "title": "bad"},
                ]
            },
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_searxng_client_maps_results_and_language() -> None:
    seen: list[dict[str, str]] = []
    client = SearxngClient("http://searx", transport=_searx_transport(seen))
    hits = await client.search("عرفان", language="fa", kind=SearchKind.TEXT)
    assert seen[0]["format"] == "json" and seen[0]["language"] == "fa"
    assert seen[0]["categories"] == "general"
    assert [h.position for h in hits] == [1, 2]  # non-http URL dropped
    assert hits[0].found_by == ["عرفان"]


@pytest.mark.asyncio
async def test_unreachable_backend_gives_actionable_message() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = SearxngClient("http://searx", transport=httpx.MockTransport(down))
    with pytest.raises(SearchBackendError, match="docker compose up -d searxng"):
        await client.search("x", language="en", kind=SearchKind.TEXT)


def test_quality_categories() -> None:
    assert classify_domain("plato.stanford.edu")[0] == "akademisch"
    assert classify_domain("iranicaonline.org")[0] == "Enzyklopädie"
    assert classify_domain("ganjoor.net")[0] == "Primärtext/Archiv"
    assert classify_domain("fa.wikipedia.org")[0] == "Wikipedia"
    assert classify_domain("reddit.com")[1] < 0.3


def test_ranking_merges_duplicates_and_prefers_quality() -> None:
    hits = [
        SearchHit(
            SearchKind.TEXT,
            "thread",
            "https://reddit.com/r/x",
            "en",
            position=1,
            found_by=["q1"],
        ),
        SearchHit(
            SearchKind.TEXT,
            "Mysticism",
            "https://www.plato.stanford.edu/m/",
            "en",
            snippet="mysticism",
            position=3,
            found_by=["q1"],
        ),
        SearchHit(
            SearchKind.TEXT,
            "Mysticism",
            "https://plato.stanford.edu/m?utm_x=1",
            "fa",
            position=2,
            found_by=["q2"],
        ),
    ]
    ranked = rank(hits, "mysticism", 10)
    assert len(ranked) == 2  # same page found twice → one hit
    assert ranked[0].domain.endswith("plato.stanford.edu")
    assert set(ranked[0].found_by) == {"q1", "q2"}
    assert canonical_url("http://www.a.org/x/?utm_source=z&id=3") == (
        "https://a.org/x?id=3"
    )


class _SlowSearx:
    def __init__(self) -> None:
        self.running = 0
        self.peak = 0

    async def search(self, query, *, language, kind, limit=20):  # type: ignore[no-untyped-def]
        self.running += 1
        self.peak = max(self.peak, self.running)
        await asyncio.sleep(0.02)
        self.running -= 1
        return [
            SearchHit(
                kind,
                query,
                f"https://example.org/{language}/{query}",
                language,
                position=1,
                found_by=[query],
            )
        ]


class _Planner:
    def __init__(self) -> None:
        self.languages: list[str] = []

    async def plan(self, *, topic, thesis, gaps, language, max_queries, previous):  # type: ignore[no-untyped-def]
        self.languages.append(language)
        return [f"{topic}-{language}-{i}" for i in range(max_queries)]


@pytest.mark.asyncio
async def test_engine_plans_per_language_and_searches_in_parallel() -> None:
    searx = _SlowSearx()
    planner = _Planner()
    engine = SearchEngine(searx, planner=planner, concurrency=6)  # type: ignore[arg-type]
    queries = await engine.plan_queries(topic="t", per_language=3)
    assert set(queries) == {"fa", "en"} and sorted(planner.languages) == ["en", "fa"]
    hits = await engine.search(queries, kind=SearchKind.TEXT, topic="t")
    assert len(hits) == 6
    assert searx.peak == 6  # all six queries ran at the same time


@pytest.mark.asyncio
async def test_failed_planning_still_searches_the_topic() -> None:
    class Broken:
        async def plan(self, **_):  # type: ignore[no-untyped-def]
            raise RuntimeError("llm down")

    engine = SearchEngine(_SlowSearx(), planner=Broken())  # type: ignore[arg-type]
    assert await engine.plan_queries(topic="t") == {"fa": ["t"], "en": ["t"]}


def test_planner_payload_passes_context_firewall() -> None:
    from app.knowledge.llm.context import guard_payload
    from app.knowledge.llm.roles import AgentRole

    guard_payload(
        AgentRole.SEARCH_PLANNER,
        json.loads(
            json.dumps(
                {
                    "brief": "x",
                    "thesis": "",
                    "evidence_gaps": [],
                    "language": "fa",
                    "source_policy": {},
                }
            )
        ),
    )
