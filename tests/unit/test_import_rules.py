"""Transcript choice and failure classification for imports/processing."""

from dataclasses import dataclass

from app.channel_monitoring.import_worker import import_error_message
from app.knowledge.adapters.youtube import (
    YouTubeRateLimitedError,
    YouTubeTranscriptUnavailableError,
    YouTubeVideoInaccessibleError,
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
            "no transcript in the channel language (fa); available: de, en",
            available=("de", "en"),
        )
    )
    assert message == "Kein persisches Transkript — vorhanden nur: de, en"
    assert "drosselt" in import_error_message(YouTubeRateLimitedError("x"))


def test_unavailable_is_not_read_as_an_available_language_list() -> None:
    """Regression: "unavailable:" contains "available:".

    The message used to be parsed with a substring match, so a video that
    is simply unplayable was stored on the candidate as "vorhanden nur:
    VideoUnplayable" — an exception class name offered to the owner as a
    transcript language.
    """

    message = import_error_message(
        YouTubeTranscriptUnavailableError(
            "video transcript unavailable: VideoUnplayable"
        )
    )
    assert message == "Video hat kein abrufbares Transkript."


def test_setup_errors_do_not_burn_retry_attempts() -> None:
    for error in (
        "RoutingConfigurationError: role 'legacy_default' requested but "
        "llm_routing_enabled is off",
        "APIMasterMissingKeyError: APIMaster API key is not configured",
        "DevinCloudError: session failed",
    ):
        assert classify_failure(error) is FailureClass.CONFIGURATION
    assert classify_failure("schema validation failed") is FailureClass.FAILED


def test_members_only_video_is_not_offered_as_retryable() -> None:
    """Regression: a members-only video was stored as

    "Import fehlgeschlagen (YouTubeMcpError) — erneut versuchbar." — the
    reason was hidden and the retry promise was false, because no retry can
    ever reach a members-only video.
    """

    message = import_error_message(
        YouTubeVideoInaccessibleError(
            "get_video_info: Join this channel to get access to members-only content"
        )
    )
    assert "nur für Mitglieder" in message
    assert "erneut versuchbar" not in message


def test_unknown_import_failures_still_name_the_reason() -> None:
    message = import_error_message(RuntimeError("mcp session expired"))
    assert "mcp session expired" in message
    assert "erneut versuchbar" in message
