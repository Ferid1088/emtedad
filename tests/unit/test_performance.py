from app.lecture.domain import PublicationLanguage
from app.localization.performance import (
    ElevenLabsCapabilityProfile,
    NativeLanguageReviewer,
    PerformanceDirector,
    PerformanceQualityValidator,
)
from app.localization.pronunciation import (
    ArabicDiacritizer,
    PersianPronunciationAnnotator,
    pronunciation_preserves_text,
)


def test_persian_voice_preparation_adds_selective_ezafe_without_rewriting_display() -> (
    None
):
    display = "آیین امتداد در راه زندگی معنا می‌گیرد."
    prepared = PersianPronunciationAnnotator().annotate(display, [])

    assert prepared.display_text == display
    assert "آیینِ امتداد" in prepared.voice_text
    assert "راهِ زندگی" in prepared.voice_text
    assert pronunciation_preserves_text(display, prepared.voice_text)
    # Ordinary prose is not fully vocalized.
    assert prepared.voice_text.count("َ") + prepared.voice_text.count("ِ") < 8


def test_performance_director_is_sparse_and_does_not_change_text() -> None:
    voice = "این یک مکث است.\n\nپرسش هنوز باز است."
    result = PerformanceDirector().prepare(
        PublicationLanguage.FA,
        voice,
        tags_by_paragraph={1: "thoughtful"},
    )

    assert result.elevenlabs_performance_text.startswith("این یک مکث است.")
    assert "[thoughtful] پرسش هنوز باز است." in result.elevenlabs_performance_text
    assert not [item for item in result.findings if item.blocking]
    assert pronunciation_preserves_text(
        voice,
        result.elevenlabs_performance_text.replace("[thoughtful] ", ""),
    )


def test_arabic_voice_preparation_uses_selective_tashkil() -> None:
    display = "امتداد ومناسك"
    prepared = ArabicDiacritizer().annotate(display, [])

    assert prepared.display_text == display
    assert "اِمْتِداد" in prepared.voice_text
    assert "مَناسِك" in prepared.voice_text
    assert pronunciation_preserves_text(display, prepared.voice_text)


def test_performance_validator_rejects_ssml_and_excessive_tags() -> None:
    voice = " ".join(["واژه"] * 20)
    performance = " ".join(["[thoughtful] واژه"] * 20)
    findings = PerformanceQualityValidator().validate(
        voice,
        performance + '<break time="1s"/>',
        ElevenLabsCapabilityProfile.eleven_v3(),
    )
    codes = {item.code for item in findings}
    assert "SSML_NOT_ALLOWED" in codes
    assert "EXCESSIVE_TAG_DENSITY" in codes


def test_native_review_blocks_internal_scaffolding() -> None:
    review = NativeLanguageReviewer().review(
        PublicationLanguage.DE,
        "The Semantic Master provides the source chunk.",
    )
    assert not review.passed
    assert any(item.code == "INTERNAL_SCAFFOLDING" for item in review.findings)
