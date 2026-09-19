"""Deterministic safety-policy examples."""

import pytest

from app.ritual.safety import RitualSafetyValidator


@pytest.mark.parametrize(
    "text",
    [
        "Everyone must close their eyes.",
        "You need to scream to release the resistance.",
        "If you felt nothing, repeat until something happens.",
        "This proves your Bon.",
        "Your resistance means you are avoiding truth.",
        "Hold your breath until the peak.",
        "Do not leave the circle.",
        "This track uses a sacred frequency.",
    ],
)
def test_coercive_or_pseudoscientific_language_is_blocked(text: str) -> None:
    report = RitualSafetyValidator().validate_text(text)
    assert report.valid is False
    assert report.issue_count >= 1


@pytest.mark.parametrize(
    "text",
    [
        "If it is comfortable and safe, you may close your eyes.",
        "If intensity rises too much, open your eyes or stop.",
        "You do not need to interpret what happened.",
        "Nothing particular may happen, and that is valid.",
        "No sacred-frequency claims are allowed.",
    ],
)
def test_optional_noninterpretive_language_passes(text: str) -> None:
    report = RitualSafetyValidator().validate_text(text)
    assert report.valid is True
    assert report.issue_count == 0
