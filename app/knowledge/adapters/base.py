"""Source-adapter boundary independent of provider persistence."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.knowledge.domain import SourceType


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    sequence: int
    start_seconds: float
    duration_seconds: float
    text: str


@dataclass(frozen=True, slots=True)
class ExternalSourceSnapshot:
    source_type: SourceType
    platform: str
    external_id: str
    canonical_url: str
    title: str
    description: str | None
    language: str
    published_at: datetime | None
    duration_seconds: int | None
    channel_external_id: str | None
    channel_title: str | None
    channel_url: str | None
    creator_name: str | None
    transcript_kind: str
    metadata: dict[str, object]
    transcript: tuple[TranscriptEntry, ...]
    thumbnail_url: str | None


class SourceAdapter(Protocol):
    async def acquire(self, locator: str) -> ExternalSourceSnapshot:
        """Acquire one immutable provider snapshot."""
