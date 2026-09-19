"""Deterministic extraction checks against the repository Ayin PDF."""

from pathlib import Path

import pytest

from app.core.ayin.domain import ReviewReason
from app.core.ayin.extractor import PopplerPdfExtractor
from app.core.ayin.provenance import passage_set_hash

pytestmark = pytest.mark.source_pdf

SOURCE = Path("docs/source_material/Ayin_Emtedad_Baznevisi_Shodeh.pdf")


@pytest.fixture(scope="module")
def extraction():  # type: ignore[no-untyped-def]
    return PopplerPdfExtractor().extract(SOURCE)


def test_exact_page_contract_and_deterministic_sequence(extraction) -> None:  # type: ignore[no-untyped-def]
    assert extraction.page_count == 146
    assert [item.sequence for item in extraction.passages] == list(
        range(1, len(extraction.passages) + 1)
    )
    assert [item.page_number for item in extraction.passages] == sorted(
        item.page_number for item in extraction.passages
    )


def test_raw_and_normalized_text_remain_separate(extraction) -> None:  # type: ignore[no-untyped-def]
    passage = next(
        item
        for item in extraction.passages
        if item.page_number == 132 and item.normalized_text.startswith("امتداد :")
    )
    assert "\u202b" in passage.raw_text
    assert "\u202b" not in passage.normalized_text
    assert passage.raw_text != passage.normalized_text


def test_page_provenance_and_heading_hierarchy_are_retained(extraction) -> None:  # type: ignore[no-untyped-def]
    passage = next(
        item
        for item in extraction.passages
        if item.page_number == 13 and item.normalized_text == "امتداد چیست؟"
    )
    assert passage.printed_page_label == "13"
    assert passage.paragraph_index > 0
    assert passage.heading_path[0].startswith("بخش یکم")
    assert passage.heading_path[1].startswith("فصل - ۱")
    assert passage.heading_path[2] == "امتداد چیست؟"


def test_repeated_extraction_has_identical_passage_hashes(extraction) -> None:  # type: ignore[no-untyped-def]
    repeated = PopplerPdfExtractor().extract(SOURCE)
    assert [item.content_hash for item in repeated.passages] == [
        item.content_hash for item in extraction.passages
    ]
    assert passage_set_hash(repeated.passages) == passage_set_hash(extraction.passages)


def test_suspicious_embedded_font_output_is_flagged(extraction) -> None:  # type: ignore[no-untyped-def]
    flagged = [item for item in extraction.passages if item.needs_review]
    assert flagged
    assert any(item.page_number == 5 for item in flagged)
    assert all(
        ReviewReason.CHARACTER_CORRUPTION in item.review_reasons for item in flagged
    )
