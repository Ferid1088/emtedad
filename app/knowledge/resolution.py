"""Provider adapters and ambiguity-preserving reference resolution."""

from dataclasses import dataclass
from typing import Protocol

import httpx
from rapidfuzz.fuzz import token_set_ratio

from app.knowledge.domain import EntityType, ResolutionProvider
from app.knowledge.normalization import normalize_external_text


@dataclass(frozen=True, slots=True)
class ProviderCandidate:
    provider: ResolutionProvider
    candidate_key: str
    entity_type: EntityType
    name: str
    identifiers: dict[str, str]
    url: str | None
    metadata: dict[str, object]
    provider_score: float | None = None


class ReferenceResolver(Protocol):
    provider: ResolutionProvider

    async def search(
        self, query: str, entity_type: EntityType
    ) -> list[ProviderCandidate]:
        """Return provider candidates without choosing a canonical identity."""


class _HttpResolver:
    provider: ResolutionProvider

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def _get(self, url: str, params: dict[str, str | int]) -> dict[str, object]:
        if self._client is not None:
            response = await self._client.get(url, params=params)
        else:
            async with httpx.AsyncClient(
                timeout=20, follow_redirects=True, headers={"User-Agent": "Emtedad/0.1"}
            ) as client:
                response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("resolver response must be an object")
        return payload


class CrossrefResolver(_HttpResolver):
    provider = ResolutionProvider.CROSSREF

    async def search(
        self, query: str, entity_type: EntityType
    ) -> list[ProviderCandidate]:
        if entity_type is not EntityType.WORK:
            return []
        payload = await self._get(
            "https://api.crossref.org/works",
            {"query.bibliographic": query, "rows": 5},
        )
        message = payload.get("message")
        items = message.get("items", []) if isinstance(message, dict) else []
        output: list[ProviderCandidate] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            titles = item.get("title")
            title = titles[0] if isinstance(titles, list) and titles else None
            doi = item.get("DOI")
            if not isinstance(title, str) or not isinstance(doi, str):
                continue
            output.append(
                ProviderCandidate(
                    provider=self.provider,
                    candidate_key=doi.casefold(),
                    entity_type=EntityType.WORK,
                    name=title,
                    identifiers={"doi": doi},
                    url=f"https://doi.org/{doi}",
                    metadata={
                        key: item[key]
                        for key in ("author", "published", "publisher", "type")
                        if key in item
                    },
                    provider_score=float(item.get("score", 0))
                    if isinstance(item.get("score"), int | float)
                    else None,
                )
            )
        return output


class OpenAlexResolver(_HttpResolver):
    provider = ResolutionProvider.OPENALEX

    async def search(
        self, query: str, entity_type: EntityType
    ) -> list[ProviderCandidate]:
        endpoint = {
            EntityType.WORK: "works",
            EntityType.PERSON: "authors",
            EntityType.ORGANIZATION: "institutions",
            EntityType.CONCEPT: "topics",
        }[entity_type]
        payload = await self._get(
            f"https://api.openalex.org/{endpoint}", {"search": query, "per-page": 5}
        )
        results = payload.get("results", [])
        output: list[ProviderCandidate] = []
        for item in results if isinstance(results, list) else []:
            if not isinstance(item, dict):
                continue
            key = item.get("id")
            name = item.get("display_name") or item.get("title")
            if not isinstance(key, str) or not isinstance(name, str):
                continue
            identifiers = {"openalex": key.rsplit("/", 1)[-1]}
            doi = item.get("doi")
            orcid = item.get("orcid")
            if isinstance(doi, str):
                identifiers["doi"] = doi.removeprefix("https://doi.org/")
            if isinstance(orcid, str):
                identifiers["orcid"] = orcid.rsplit("/", 1)[-1]
            output.append(
                ProviderCandidate(
                    provider=self.provider,
                    candidate_key=key,
                    entity_type=entity_type,
                    name=name,
                    identifiers=identifiers,
                    url=key,
                    metadata={
                        field: item[field]
                        for field in ("publication_year", "authorships", "type")
                        if field in item
                    },
                    provider_score=float(item.get("relevance_score", 0))
                    if isinstance(item.get("relevance_score"), int | float)
                    else None,
                )
            )
        return output


class OpenLibraryResolver(_HttpResolver):
    provider = ResolutionProvider.OPENLIBRARY

    async def search(
        self, query: str, entity_type: EntityType
    ) -> list[ProviderCandidate]:
        if entity_type is not EntityType.WORK:
            return []
        params: dict[str, str | int] = {"q": query, "limit": 5}
        payload = await self._get("https://openlibrary.org/search.json", params)
        docs = payload.get("docs", [])
        output: list[ProviderCandidate] = []
        for item in docs if isinstance(docs, list) else []:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            title = item.get("title")
            if not isinstance(key, str) or not isinstance(title, str):
                continue
            identifiers: dict[str, str] = {"openlibrary": key}
            isbn = item.get("isbn")
            if isinstance(isbn, list) and isbn and isinstance(isbn[0], str):
                identifiers["isbn"] = isbn[0]
            output.append(
                ProviderCandidate(
                    provider=self.provider,
                    candidate_key=key,
                    entity_type=EntityType.WORK,
                    name=title,
                    identifiers=identifiers,
                    url=f"https://openlibrary.org{key}",
                    metadata={
                        field: item[field]
                        for field in ("author_name", "first_publish_year")
                        if field in item
                    },
                )
            )
        return output


class WikidataResolver(_HttpResolver):
    provider = ResolutionProvider.WIKIDATA

    async def search(
        self, query: str, entity_type: EntityType
    ) -> list[ProviderCandidate]:
        payload = await self._get(
            "https://www.wikidata.org/w/api.php",
            {
                "action": "wbsearchentities",
                "format": "json",
                "language": "en",
                "uselang": "en",
                "limit": 5,
                "search": query,
            },
        )
        items = payload.get("search", [])
        output: list[ProviderCandidate] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            key = item.get("id")
            name = item.get("label")
            if not isinstance(key, str) or not isinstance(name, str):
                continue
            output.append(
                ProviderCandidate(
                    provider=self.provider,
                    candidate_key=key,
                    entity_type=entity_type,
                    name=name,
                    identifiers={"wikidata": key},
                    url=item.get("concepturi")
                    if isinstance(item.get("concepturi"), str)
                    else None,
                    metadata={
                        "description": item.get("description"),
                        "match": item.get("match"),
                    },
                )
            )
        return output


def candidate_score(query: str, candidate: ProviderCandidate) -> float:
    """Return a deterministic 0–100 surface/context similarity score."""

    return float(
        token_set_ratio(
            normalize_external_text(query).casefold(),
            normalize_external_text(candidate.name).casefold(),
        )
    )
