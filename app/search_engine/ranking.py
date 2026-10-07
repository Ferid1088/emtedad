"""Cheap ranking: search position + source quality + relevance; URL dedupe."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.search_engine.models import SearchHit
from app.search_engine.quality import classify_domain

_WORD = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)
_TRACKING = re.compile(r"^(utm_|fbclid|gclid|ref$|ref_src|si$)")


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)]
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, query, ""))


def domain_of(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD.findall(text) if len(t) > 2}


def rank(hits: list[SearchHit], topic: str, limit: int) -> list[SearchHit]:
    """Merge duplicates (same canonical URL) and order by score."""

    topic_tokens = _tokens(topic)
    merged: dict[str, SearchHit] = {}
    for hit in hits:
        key = canonical_url(hit.url)
        existing = merged.get(key)
        if existing is None:
            merged[key] = hit
            continue
        # Found again by another query/language/engine: keep the best
        # position and remember every query that found it.
        existing.position = min(existing.position, hit.position)
        existing.found_by.extend(q for q in hit.found_by if q not in existing.found_by)
        existing.engines = tuple(sorted(set(existing.engines) | set(hit.engines)))
        if not existing.snippet and hit.snippet:
            existing.snippet = hit.snippet
    ranked: list[SearchHit] = []
    for hit in merged.values():
        hit.domain = domain_of(hit.url)
        hit.quality_category, hit.quality_weight = classify_domain(hit.domain)
        text_tokens = _tokens(f"{hit.title} {hit.snippet}")
        hit.relevance = (
            len(topic_tokens & text_tokens) / len(topic_tokens) if topic_tokens else 0.0
        )
        position_score = 1.0 / (1.0 + 0.15 * max(hit.position - 1, 0))
        agreement = min(len(hit.found_by), 3) / 3  # found by several queries
        hit.score = round(
            0.35 * hit.quality_weight
            + 0.3 * hit.relevance
            + 0.25 * position_score
            + 0.1 * agreement,
            4,
        )
        ranked.append(hit)
    ranked.sort(key=lambda h: h.score, reverse=True)
    return ranked[:limit]
