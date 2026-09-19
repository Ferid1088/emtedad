"""Source-backed Manasek extraction and structural parsing."""

from pathlib import Path

import pytest

from app.ritual.domain import GATE_ORDER, RitualPieceType
from app.ritual.extractor import PopplerRitualExtractor
from app.ritual.parser import parse_manasek

SOURCE = Path("docs/source_material/Manasek_V1.pdf")


@pytest.mark.source_pdf
def test_current_manasek_pdf_preserves_explicit_structure() -> None:
    extraction = PopplerRitualExtractor().extract(SOURCE)
    parsed = parse_manasek(extraction)

    assert extraction.page_count == 42
    assert len(extraction.passages) == 42
    assert len(parsed.rituals) == 43
    assert sum(item.piece_type is RitualPieceType.GATE for item in parsed.rituals) == 35
    assert (
        sum(item.piece_type is RitualPieceType.RETURN for item in parsed.rituals) == 7
    )
    assert sum(len(item.cues) for item in parsed.rituals) == 224
    assert all(item.music.original_prompt for item in parsed.rituals)
    assert all(
        not item.music.sonic_family.startswith("Source does not isolate")
        for item in parsed.rituals
    )
    assert all(
        not item.music.emotional_arc.startswith("Source does not isolate")
        for item in parsed.rituals
    )
    assert all(
        cue.start_seconds is None or cue.start_seconds >= 0
        for ritual in parsed.rituals
        for cue in ritual.cues
    )
    assert all(
        cue.end_seconds is None
        or (cue.start_seconds is not None and cue.end_seconds > cue.start_seconds)
        for ritual in parsed.rituals
        for cue in ritual.cues
    )
    assert [
        item.gate
        for item in parsed.rituals
        if item.stage_position == 1 and item.piece_type is RitualPieceType.GATE
    ] == list(GATE_ORDER)
    assert parsed.rituals[0].title == "فرود"
    assert parsed.rituals[-1].piece_type is RitualPieceType.COLLECTIVE
    assert parsed.rituals[-1].duration_seconds == 1440
