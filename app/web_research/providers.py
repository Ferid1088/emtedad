"""Provider-agnostic web research clients.

Three adapters share one protocol:

- ``openrouter``: chat-completions endpoint (OpenRouter or any compatible
  API). The configured model should have web access (e.g. OpenRouter's
  ``:online`` plugin); URL citations are read from message annotations.
- ``tavily``: a Tavily-compatible ``POST /search`` API returning
  ``{answer, results: [{title, url, content}]}``.
- ``custom``: POSTs ``{"query": ...}`` to the configured base URL and parses
  common result shapes (``results``/``items``/``data`` lists with
  ``url``/``link``/``href`` entries).

All parameters — provider, base URL, model, API key, result count, timeout —
come from owner settings, never from code constants.
"""

from typing import Any, Protocol

import httpx

from app.web_research.domain import WebFinding, WebResearchReport


class WebResearchError(RuntimeError):
    """Raised for transport, auth, or response-shape failures."""


class ResearchConfig:
    """Resolved settings for one research call."""

    def __init__(self, effective: dict[str, Any]) -> None:
        self.provider = str(effective.get("web_research_provider") or "openrouter")
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
    if config.provider == "tavily":
        return _TavilyProvider(config, transport)
    if config.provider == "custom":
        return _CustomProvider(config, transport)
    return _OpenRouterProvider(config, transport)


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


class _OpenRouterProvider:
    def __init__(
        self, config: ResearchConfig, transport: httpx.AsyncBaseTransport | None
    ) -> None:
        self.config = config
        self.transport = transport

    async def research(self, query: str, context: str) -> WebResearchReport:
        body: dict[str, Any] = {
            "model": self.config.model or "openai/gpt-4o-mini:online",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Research the web for the user's question. Answer with "
                        "concrete findings and always cite source URLs."
                    ),
                },
                {
                    "role": "user",
                    "content": f"{query}\n\nContext: {context}" if context else query,
                },
            ],
        }
        try:
            async with _client(self.config, self.transport) as client:
                response = await client.post(
                    f"{self.config.base_url}/chat/completions", json=body
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise WebResearchError(f"openrouter request failed: {exc}") from exc
        message = (payload.get("choices") or [{}])[0].get("message") or {}
        answer = str(message.get("content") or "")
        findings: list[WebFinding] = []
        for annotation in message.get("annotations") or []:
            citation = annotation.get("url_citation") or {}
            url = citation.get("url")
            if url:
                findings.append(
                    WebFinding(
                        title=str(citation.get("title") or ""),
                        url=str(url),
                        snippet=str(citation.get("content") or "")[:500],
                    )
                )
        return WebResearchReport(
            provider="openrouter",
            query=query,
            answer_text=answer,
            findings=_dedupe(findings, self.config.max_results),
        )


class _TavilyProvider:
    def __init__(
        self, config: ResearchConfig, transport: httpx.AsyncBaseTransport | None
    ) -> None:
        self.config = config
        self.transport = transport

    async def research(self, query: str, context: str) -> WebResearchReport:
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
