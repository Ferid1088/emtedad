"""Transcript choice and failure classification for imports/processing."""

from dataclasses import dataclass

from app.channel_monitoring.import_worker import import_error_message
from app.knowledge.adapters.youtube import (
    YouTubeRateLimitedError,
    YouTubeTranscriptUnavailableError,
    choose_transcript,
)
from app.knowledge.structure.domain import FailureClass, classify_failure


@dataclass
class _T:
    language_code: str
    is_generated: bool


def test_manual_persian_beats_generated_persian() -> None:
    items = [_T("en", False), _T("fa", True), _T("fa", False)]
    chosen = choose_transcript(items, ("fa",))
    assert chosen is items[2]


def test_generated_persian_is_used_when_no_manual_exists() -> None:
    items = [_T("en", False), _T("fa", True)]
    assert choose_transcript(items, ("fa",)) is items[1]


def test_other_languages_are_never_taken_silently() -> None:
    assert choose_transcript([_T("en", False), _T("de", True)], ("fa",)) is None


def test_import_errors_are_readable() -> None:
    message = import_error_message(
        YouTubeTranscriptUnavailableError(
            "no transcript in the channel language (fa); available: de, en"
        )
    )
    assert message == "Kein persisches Transkript — vorhanden nur: de, en"
    assert "drosselt" in import_error_message(YouTubeRateLimitedError("x"))


def test_setup_errors_do_not_burn_retry_attempts() -> None:
    for error in (
        "RoutingConfigurationError: role 'legacy_default' requested but "
        "llm_routing_enabled is off",
        "APIMasterMissingKeyError: APIMaster API key is not configured",
        "DevinCloudError: session failed",
    ):
        assert classify_failure(error) is FailureClass.CONFIGURATION
    assert classify_failure("schema validation failed") is FailureClass.FAILED
