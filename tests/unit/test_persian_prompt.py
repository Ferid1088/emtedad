from app.content_engine.writing.prompts import (
    EMTEDAD_VOICE_CONTRACT,
    PERSIAN_VOICE_CONTRACT,
)


def test_persian_voice_contract_preserves_editorial_boundaries() -> None:
    assert "Return only the" in PERSIAN_VOICE_CONTRACT
    assert "finished Persian editorial draft" in PERSIAN_VOICE_CONTRACT
    assert "Never output source labels" in PERSIAN_VOICE_CONTRACT
    # The generic contract must not depend on the retired lesson canon.
    for forbidden in ("lesson", "Lesson", "Lesson Content Package", "canon"):
        assert forbidden not in PERSIAN_VOICE_CONTRACT


def test_emtedad_contract_preserves_ayin_boundaries() -> None:
    assert "پذیرش تسلیم نیست" in EMTEDAD_VOICE_CONTRACT
    assert "Never write that science proves Ayin" in EMTEDAD_VOICE_CONTRACT
    assert "بُن" in EMTEDAD_VOICE_CONTRACT
