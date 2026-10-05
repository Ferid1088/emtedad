"""Generation-contract validation: pre-review, deterministic, bounded."""

from app.content_engine.writing.generation import (
    GenerationCheck,
    validate_generation,
)


def _paras(n: int, words: int = 30) -> str:
    return "\n\n".join(f"پاراگراف {i} " + "کلمه " * words for i in range(n))


def test_in_band_draft_passes() -> None:
    report = validate_generation(
        _paras(8, 380),  # 8 × 382 = 3056 words ≈ 27.8 min at 110 wpm
        language="fa",
        target_minutes=27.5,
        wpm=110,
        section_count=8,
        min_ratio=0.85,
        max_ratio=1.15,
    )
    assert report.passed
    assert report.word_count == 8 * 382
    assert report.duration_minutes == report.word_count / 110


def test_short_first_draft_fails_duration() -> None:
    report = validate_generation(
        _paras(8, 200),  # ~1600 words ≈ 14.5min — under the 23.4min floor
        language="fa",
        target_minutes=27.5,
        wpm=110,
        section_count=8,
        min_ratio=0.85,
        max_ratio=1.15,
    )
    assert not report.passed
    assert any(c.code == "DURATION_BELOW_GENERATION_BAND" for c in report.checks)


def test_overlong_draft_fails_duration() -> None:
    report = validate_generation(
        _paras(8, 500),  # ~4000 words ≈ 36min — above the ceiling
        language="fa",
        target_minutes=27.5,
        wpm=110,
        section_count=8,
        min_ratio=0.85,
        max_ratio=1.15,
    )
    assert not report.passed
    assert any(c.code == "DURATION_ABOVE_GENERATION_BAND" for c in report.checks)


def test_encoding_corruption_fails_generation() -> None:
    report = validate_generation(
        _paras(8, 380) + "\ufffd متن خراب",
        language="fa",
        target_minutes=27.5,
        wpm=110,
        section_count=8,
        min_ratio=0.85,
        max_ratio=1.15,
    )
    assert not report.passed
    assert any(c.code == "ENCODING_CORRUPTION" for c in report.checks)


def test_collapsed_structure_fails() -> None:
    report = validate_generation(
        "پاراگراف تنها " + "کلمه " * 3000,
        language="fa",
        target_minutes=27.5,
        wpm=110,
        section_count=8,
        min_ratio=0.85,
        max_ratio=1.15,
    )
    assert not report.passed
    assert any(c.code == "NARRATIVE_STRUCTURE_COLLAPSED" for c in report.checks)


def test_persian_quality_blockers_surface_in_generation() -> None:
    report = validate_generation(
        _paras(8, 380) + "\n\nThe external source provides evidence.",
        language="fa",
        target_minutes=27.5,
        wpm=110,
        section_count=8,
        min_ratio=0.85,
        max_ratio=1.15,
    )
    assert not report.passed
    assert any(c.code == "INTERNAL_SCAFFOLDING_LEAKAGE" for c in report.checks)


def test_report_payload_is_json_safe() -> None:
    report = validate_generation(
        _paras(8, 100),
        language="fa",
        target_minutes=27.5,
        wpm=110,
        section_count=8,
        min_ratio=0.85,
        max_ratio=1.15,
    )
    payload = report.payload()
    assert payload["passed"] is False
    assert "DURATION_BELOW_GENERATION_BAND" in payload["failed_checks"]
    assert isinstance(payload["word_count"], int)


def test_non_persian_language_skips_fa_validator() -> None:
    report = validate_generation(
        "\n\n".join(f"Section {i} " + "word " * 480 for i in range(8)),
        language="en",
        target_minutes=27.5,
        wpm=140,
        section_count=8,
        min_ratio=0.85,
        max_ratio=1.15,
    )
    assert report.passed
    assert not any(
        isinstance(c, GenerationCheck) and "PERSIAN" in c.code for c in report.checks
    )
