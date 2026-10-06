"""Deterministic native-quality gate tests."""

from app.lecture.domain import PublicationLanguage
from app.localization.native_quality import validate_target_script


def _codes(findings) -> set[str]:
    return {f.code for f in findings}


def test_replacement_character_is_blocking() -> None:
    findings, _, _ = validate_target_script(
        "Ein Text mit \ufffd Fehler.",
        PublicationLanguage.DE,
        min_minutes=0.0,
        max_minutes=60.0,
        wpm=130,
    )
    assert "ENCODING_CORRUPTION" in _codes(findings)


def test_zwnj_allowed_for_persian_and_arabic_only() -> None:
    fa, _, _ = validate_target_script(
        "می\u200cخواهم این متن فارسی باشد " * 50,
        PublicationLanguage.FA,
        min_minutes=0.0,
        max_minutes=60.0,
        wpm=110,
    )
    assert "CONTROL_CHARS" not in _codes(fa)
    de, _, _ = validate_target_script(
        "Ein deutscher Text\u200c mit verstecktem Zeichen.",
        PublicationLanguage.DE,
        min_minutes=0.0,
        max_minutes=60.0,
        wpm=130,
    )
    assert "CONTROL_CHARS" in _codes(de)


def test_wrong_script_detected() -> None:
    findings, _, _ = validate_target_script(
        "این متن کاملاً فارسی است و نباید به عنوان آلمانی پذیرفته شود " * 10,
        PublicationLanguage.DE,
        min_minutes=0.0,
        max_minutes=60.0,
        wpm=130,
    )
    assert "WRONG_SCRIPT" in _codes(findings)


def test_duration_bounds() -> None:
    short, words, minutes = validate_target_script(
        "Kurzer Text.",
        PublicationLanguage.DE,
        min_minutes=25.0,
        max_minutes=30.0,
        wpm=130,
    )
    assert "DURATION_TOO_SHORT" in _codes(short)
    long, _, _ = validate_target_script(
        "wort " * 5000,
        PublicationLanguage.DE,
        min_minutes=25.0,
        max_minutes=30.0,
        wpm=130,
    )
    assert "DURATION_TOO_LONG" in _codes(long)
    ok, words, minutes = validate_target_script(
        "Wort " * 3500,
        PublicationLanguage.DE,
        min_minutes=25.0,
        max_minutes=30.0,
        wpm=130,
    )
    assert not _codes(ok)
    assert 25.0 <= minutes <= 30.0


def test_internal_pipeline_phrases_leak_is_blocked() -> None:
    findings, _, _ = validate_target_script(
        "Diese Passage nennt Semantic Master in der Prosa. " + "Text " * 100,
        PublicationLanguage.DE,
        min_minutes=0.0,
        max_minutes=60.0,
        wpm=130,
    )
    assert "INTERNAL_LEAKAGE" in _codes(findings)
