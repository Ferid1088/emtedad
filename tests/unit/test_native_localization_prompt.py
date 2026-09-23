from app.lecture.domain import PublicationLanguage
from app.localization.prompts import native_realization_instruction


def test_localization_requires_native_rewriting() -> None:
    prompt = native_realization_instruction(PublicationLanguage.DE)

    assert "Do NOT preserve Persian sentence structure" in prompt
    assert "Reconstruct the prose natively" in prompt
    assert "Transfer meaning" in prompt


def test_persian_prompt_forbids_sentence_by_sentence_translation() -> None:
    prompt = native_realization_instruction(PublicationLanguage.FA)

    assert "originally Persian" in prompt
    assert "sentence-by-sentence" in prompt
