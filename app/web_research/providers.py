"""Provider-agnostic web research retrieval clients.

Three URL-capable adapters share one protocol:

- ``tavily``: a Tavily-compatible ``POST /search`` API returning
  ``{answer, results: [{title, url, content}]}``.
- ``custom``: POSTs ``{"query": ...}`` to the configured base URL and parses
  common result shapes (``results``/``items``/``data`` lists with
  ``url``/``link``/``href`` entries).
- ``wikipedia``: keyless ``GET /w/api.php?action=opensearch`` against the
  configured wiki base URL (e.g. ``https://en.wikipedia.org``), returning
  real article URLs. Encyclopedic scope only — useful as a zero-credential
  grounded backend; configure tavily/custom for open-web retrieval.

Research architecture: the APIMaster LLM plans queries and evaluates
sources through role-routed providers; this layer only retrieves. An
LLM "web answer" path cannot provide verifiable source URLs, so
``apimaster`` is disabled as a retrieval provider — evidence must come
from fetched, classified pages, never from synthesized text.

All parameters — provider, base URL, model, API key, result count, timeout —
come from owner settings, never from code constants.
"""

import re
from typing import Any, Protocol

import httpx

from app.web_research.domain import WebFinding, WebResearchReport


class WebResearchError(RuntimeError):
    """Raised for transport, auth, or response-shape failures."""


class ResearchConfig:
    """Resolved settings for one research call."""

    def __init__(self, effective: dict[str, Any]) -> None:
        self.provider = str(effective.get("web_research_provider") or "tavily")
        self.base_url = str(effective.get("web_research_base_url") or "").rstrip("/")
        self.api_key = str(effective.get("web_research_api_key") or "")
        self.model = str(effective.get("web_research_model") or "")
        self.max_results = int(effective.get("web_research_max_results") or 5)
        self.timeout_seconds = float(
            effective.get("web_research_timeout_seconds") or 90
        )
        self.max_page_bytes = int(
            effective.get("web_research_max_page_bytes") or 1_500_000
        )


class WebResearchProvider(Protocol):
    async def research(self, query: str, context: str) -> WebResearchReport: ...


def build_provider(
    config: ResearchConfig, *, transport: httpx.AsyncBaseTransport | None = None
) -> WebResearchProvider:
    if not config.base_url:
        raise WebResearchError("web_research_base_url is not configured")
    if config.provider == "searxng":
        return _SearxngProvider(config, transport)
    if config.provider == "tavily":
        return _TavilyProvider(config, transport)
    if config.provider == "custom":
        return _CustomProvider(config, transport)
    if config.provider == "wikipedia":
        return _WikipediaProvider(config, transport)
    if config.provider == "apimaster":
        raise WebResearchError(
            "apimaster cannot retrieve verifiable source URLs — web "
            "research requires a URL-capable backend (tavily or custom); "
            "the LLM gateway stays for planning and evaluation only"
        )
    raise WebResearchError(f"unknown web research provider: {config.provider}")


def _client(
    config: ResearchConfig, transport: httpx.AsyncBaseTransport | None
) -> httpx.AsyncClient:
    headers: dict[str, str] = {}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    return httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(config.timeout_seconds),
        transport=transport,
        follow_redirects=True,
    )


class _TavilyProvider:
    def __init__(
        self, config: ResearchConfig, transport: httpx.AsyncBaseTransport | None
    ) -> None:
        self.config = config
        self.transport = transport

    async def research(self, query: str, context: str) -> WebResearchReport:
        if not self.config.api_key:
            raise WebResearchError(
                "tavily retrieval requires web_research_api_key — configure "
                "a real search-backend key in Studio settings"
            )
        body: dict[str, Any] = {
            "query": query if not context else f"{query} — {context[:300]}",
            "max_results": self.config.max_results,
            "include_answer": True,
        }
        if self.config.api_key:
            body["api_key"] = self.config.api_key
        try:
            async with _client(self.config, self.transport) as client:
                response = await client.post(
                    f"{self.config.base_url}/search", json=body
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise WebResearchError(f"tavily request failed: {exc}") from exc
        findings = [
            WebFinding(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                snippet=str(item.get("content") or "")[:500],
            )
            for item in payload.get("results") or []
            if item.get("url")
        ]
        return WebResearchReport(
            provider="tavily",
            query=query,
            answer_text=str(payload.get("answer") or ""),
            findings=_dedupe(findings, self.config.max_results),
        )


class _CustomProvider:
    def __init__(
        self, config: ResearchConfig, transport: httpx.AsyncBaseTransport | None
    ) -> None:
        self.config = config
        self.transport = transport

    async def research(self, query: str, context: str) -> WebResearchReport:
        try:
            async with _client(self.config, self.transport) as client:
                response = await client.post(
                    self.config.base_url,
                    json={
                        "query": query,
                        "context": context,
                        "max_results": self.config.max_results,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise WebResearchError(f"custom provider request failed: {exc}") from exc
        findings: list[WebFinding] = []
        items = payload if isinstance(payload, list) else None
        if items is None and isinstance(payload, dict):
            for key in ("results", "items", "data", "findings"):
                if isinstance(payload.get(key), list):
                    items = payload[key]
                    break
        for item in items or []:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("link") or item.get("href")
            if url:
                findings.append(
                    WebFinding(
                        title=str(item.get("title") or item.get("name") or ""),
                        url=str(url),
                        snippet=str(item.get("snippet") or item.get("content") or "")[
                            :500
                        ],
                    )
                )
        return WebResearchReport(
            provider="custom",
            query=query,
            answer_text=str(payload.get("answer") or "")
            if isinstance(payload, dict)
            else "",
            findings=_dedupe(findings, self.config.max_results),
        )


class _WikipediaProvider:
    """Keyless OpenSearch retrieval against a configured MediaWiki site."""

    def __init__(
        self, config: ResearchConfig, transport: httpx.AsyncBaseTransport | None
    ) -> None:
        self.config = config
        self.transport = transport

    async def research(self, query: str, context: str) -> WebResearchReport:
        try:
            async with _client(self.config, self.transport) as client:
                response = await client.get(
                    f"{self.config.base_url}/w/api.php",
                    headers={
                        # Wikimedia requires a descriptive UA.
                        "User-Agent": "EmtedadApp/1.0 (research; httpx)"
                    },
                    params={
                        # list=search is full-text — opensearch only does
                        # title-prefix matching and misses topical queries.
                        "action": "query",
                        "list": "search",
                        "srsearch": query,
                        "srlimit": self.config.max_results,
                        "srnamespace": 0,
                        "srprop": "snippet",
                        "format": "json",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise WebResearchError(f"wikipedia request failed: {exc}") from exc
        findings: list[WebFinding] = []
        if isinstance(payload, dict):
            for item in (payload.get("query") or {}).get("search") or []:
                title = str(item.get("title") or "")
                if not title:
                    continue
                url = f"{self.config.base_url}/wiki/{title.replace(' ', '_')}"
                findings.append(
                    WebFinding(
                        title=title,
                        url=url,
                        # srprop=snippet returns HTML fragments.
                        snippet=re.sub(r"<[^>]+>", "", str(item.get("snippet") or ""))[
                            :500
                        ],
                    )
                )
        return WebResearchReport(
            provider="wikipedia",
            query=query,
            answer_text="",
            findings=_dedupe(findings, self.config.max_results),
        )


class _SearxngProvider:
    """Emtedad search engine: planner agents per language (fa, en) write
    native queries in parallel; SearXNG answers them in parallel; results
    are ranked by source quality, relevance and agreement."""

    def __init__(
        self, config: ResearchConfig, transport: httpx.AsyncBaseTransport | None
    ) -> None:
        self.config = config
        self.transport = transport

    async def research(self, query: str, context: str) -> WebResearchReport:
        from app.knowledge.llm.factory import resolve_llm_provider
        from app.knowledge.llm.roles import AgentRole
        from app.search_engine.engine import SearchEngine
        from app.search_engine.models import SearchKind
        from app.search_engine.planner import QueryPlanner
        from app.search_engine.searxng import SearchBackendError, SearxngClient

        try:
            planner: QueryPlanner | None = QueryPlanner(
                resolve_llm_provider(role=AgentRole.SEARCH_PLANNER)
            )
        except Exception:  # noqa: BLE001 — plain search without planning
            planner = None
        engine = SearchEngine(
            SearxngClient(
                self.config.base_url,
                timeout_seconds=self.config.timeout_seconds,
                transport=self.transport,
            ),
            planner=planner,
        )
        queries = await engine.plan_queries(
            topic=query, thesis=context[:1500], per_language=3
        )
        for language_queries in queries.values():
            if query not in language_queries:
                language_queries.insert(0, query)
        try:
            hits = await engine.search(
                queries,
                kind=SearchKind.TEXT,
                topic=f"{query} {context[:300]}",
                limit=self.config.max_results * 3,
            )
        except SearchBackendError as exc:
            raise WebResearchError(str(exc)) from exc
        # Low-value categories are not ingested as research sources.
        useful = [h for h in hits if h.quality_weight >= 0.35]
        findings = [
            WebFinding(title=hit.title, url=hit.url, snippet=hit.snippet)
            for hit in useful
        ]
        return WebResearchReport(
            provider="searxng",
            query=query,
            answer_text="",
            findings=_dedupe(findings, self.config.max_results),
        )


def _dedupe(findings: list[WebFinding], limit: int) -> list[WebFinding]:
    seen: set[str] = set()
    unique: list[WebFinding] = []
    for finding in findings:
        key = finding.url.split("#")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique[:limit]
