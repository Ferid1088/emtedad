"""Specialized critics, native criteria and script-integrity gate."""

from app.content_engine.critics import (
    CRITIC_AGENT_ROLES,
    critic_instructions,
    critics_for,
    script_integrity,
)
from app.content_engine.domain import CriticRole
from app.lecture.domain import PublicationLanguage
from app.localization.native_prompts import native_critic_instructions


def test_every_critic_has_its_own_brief_and_model_role() -> None:
    texts = {critic_instructions(role, ()) for role in CriticRole}
    assert len(texts) == len(CriticRole)  # no two critics share a brief
    assert set(CRITIC_AGENT_ROLES) == set(CriticRole)


def test_persian_critic_judges_in_persian_and_only_persian_drafts() -> None:
    assert "آیا متن واقعاً طبیعی" in critic_instructions(CriticRole.PERSIAN_QUALITY, ())
    assert CriticRole.PERSIAN_QUALITY in critics_for("fa")
    assert CriticRole.PERSIAN_QUALITY not in critics_for("de")


def test_channel_checks_are_listed() -> None:
    text = critic_instructions(CriticRole.CHANNEL_SPECIFIC, ("NO_PREACHING",))
    assert "NO_PREACHING" in text


def test_native_criteria_are_written_in_the_target_language() -> None:
    assert "Bewerte den Text auf Deutsch" in native_critic_instructions(
        PublicationLanguage.DE
    )
    assert "قيّم النص بالعربية" in native_critic_instructions(PublicationLanguage.AR)
    assert "Judge the text in English" in native_critic_instructions(
        PublicationLanguage.EN
    )


def test_script_integrity_gate() -> None:
    persian = "این یک متن فارسی کاملاً طبیعی است که برای ویدیو نوشته شده است."
    assert script_integrity(persian, "fa").passed  # type: ignore[union-attr]
    mixed = persian + " This sentence is English and should fail the gate badly."
    result = script_integrity(mixed, "fa")
    assert result is not None and not result.passed
    assert script_integrity("Hello", "de") is None  # no gate for Latin scripts
