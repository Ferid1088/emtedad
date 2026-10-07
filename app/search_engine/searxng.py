"""Client for a self-hosted SearXNG metasearch instance (no API key)."""

import httpx

from app.search_engine.models import SearchHit, SearchKind


class SearchBackendError(RuntimeError):
    """The search backend is unreachable or answered with an error."""


_CATEGORY = {
    SearchKind.TEXT: "general",
    SearchKind.VIDEO: "videos",
    SearchKind.IMAGE: "images",
}


class SearxngClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds
        self.transport = transport

    async def search(
        self, query: str, *, language: str, kind: SearchKind, limit: int = 20
    ) -> list[SearchHit]:
        params = {
            "q": query,
            "format": "json",
            "language": language,
            "categories": _CATEGORY[kind],
            "safesearch": "1",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self.transport,
                headers={"User-Agent": "EmtedadResearch/1.0"},
            ) as client:
                response = await client.get(f"{self.base_url}/search", params=params)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchBackendError(
                f"Suchmaschine (SearXNG unter {self.base_url}) nicht erreichbar: "
                f"{type(exc).__name__}. Läuft der Container? "
                "→ docker compose up -d searxng"
            ) from exc
        hits: list[SearchHit] = []
        for position, item in enumerate(payload.get("results") or [], start=1):
            url = str(item.get("url") or "")
            if not url.startswith(("http://", "https://")):
                continue
            hits.append(
                SearchHit(
                    kind=kind,
                    title=str(item.get("title") or url)[:300],
                    url=url,
                    language=language,
                    snippet=str(item.get("content") or "")[:500],
                    engines=tuple(item.get("engines") or ()),
                    position=position,
                    thumbnail_url=str(
                        item.get("thumbnail_src") or item.get("thumbnail") or ""
                    ),
                    image_url=str(item.get("img_src") or ""),
                    published=str(item.get("publishedDate") or "")[:10],
                    found_by=[query],
                )
            )
            if len(hits) >= limit:
                break
        return hits
