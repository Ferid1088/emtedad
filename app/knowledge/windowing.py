"""Deterministic overlapping extraction windows over immutable segments."""

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class WindowSegment:
    id: UUID
    sequence: int
    start_seconds: Decimal
    end_seconds: Decimal
    normalized_text: str


@dataclass(frozen=True, slots=True)
class BuiltWindow:
    sequence: int
    segments: tuple[WindowSegment, ...]
    text: str
    content_hash: str


def build_windows(
    segments: list[WindowSegment], *, window_size: int = 50, overlap: int = 8
) -> list[BuiltWindow]:
    """Build stable windows while retaining every source segment identity."""

    if window_size <= 0 or overlap < 0 or overlap >= window_size:
        raise ValueError("window_size must be positive and overlap smaller")
    if not segments:
        return []
    step = window_size - overlap
    windows: list[BuiltWindow] = []
    for start in range(0, len(segments), step):
        items = tuple(segments[start : start + window_size])
        if not items:
            break
        text = "\n".join(
            f"[{item.sequence}|{item.start_seconds}-{item.end_seconds}] "
            f"{item.normalized_text}"
            for item in items
        )
        digest = hashlib.sha256(text.encode()).hexdigest()
        windows.append(
            BuiltWindow(
                sequence=len(windows) + 1,
                segments=items,
                text=text,
                content_hash=digest,
            )
        )
        if start + window_size >= len(segments):
            break
    return windows
