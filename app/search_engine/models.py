"""Search vocabulary shared by the engine, the Studio page and ingestion."""

from dataclasses import dataclass, field
from enum import StrEnum


class SearchKind(StrEnum):
    TEXT = "text"
    VIDEO = "video"
    IMAGE = "image"


SEARCH_LANGUAGES: tuple[str, ...] = ("fa", "en")


@dataclass
class SearchHit:
    kind: SearchKind
    title: str
    url: str
    language: str
    snippet: str = ""
    engines: tuple[str, ...] = ()
    position: int = 0  # 1-based rank inside its own result list
    thumbnail_url: str = ""
    image_url: str = ""
    published: str = ""
    duration_seconds: int | None = None
    # Filled by ranking:
    domain: str = ""
    quality_category: str = ""
    quality_weight: float = 0.0
    relevance: float = 0.0
    score: float = 0.0
    found_by: list[str] = field(default_factory=list)  # queries that found it
