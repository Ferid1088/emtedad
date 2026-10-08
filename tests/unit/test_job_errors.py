"""Background jobs must hand the owner a readable German message.

A Studio action runs in the background (app/web/jobs.py); whatever it
raises is shown in the workspace, so every failure the owner can actually
hit needs a message that says what happened and what to do — never a bare
exception name or an English provider string.
"""

from app.knowledge.adapters.youtube import (
    YouTubeAdapterError,
    YouTubeRateLimitedError,
    YouTubeTranscriptUnavailableError,
)
from app.knowledge.llm.apimaster import APIMasterMissingKeyError
from app.web.jobs import friendly_error


def test_youtube_rate_limit_is_german_and_names_the_next_step() -> None:
    # Seen live: importing a video from /studio/research while YouTube
    # throttled this IP produced the raw English adapter message behind
    # "Unerwarteter Fehler (YouTubeRateLimitedError)".
    message = friendly_error(
        YouTubeRateLimitedError("transcript endpoint rate-limited: IpBlocked")
    )
    assert "Unerwarteter Fehler" not in message
    assert "YouTube drosselt" in message
    assert "erneut starten" in message


def test_missing_transcript_language_lists_what_youtube_offers() -> None:
    message = friendly_error(
        YouTubeTranscriptUnavailableError(
            "no transcript in the channel language (fa); available: en, tr",
            available=("en", "tr"),
        )
    )
    assert message == "Kein persisches Transkript — vorhanden nur: en, tr"


def test_unavailable_is_not_mistaken_for_an_available_language_list() -> None:
    """Regression: "unavailable:" contains "available:".

    The old substring match turned "video transcript unavailable:
    VideoUnplayable" into "vorhanden nur: VideoUnplayable" — an exception
    class name presented to the owner as a transcript language.
    """

    message = friendly_error(
        YouTubeTranscriptUnavailableError(
            "video transcript unavailable: VideoUnplayable"
        )
    )
    assert message == "Dieses Video hat kein abrufbares Transkript."


def test_other_youtube_failures_stay_readable() -> None:
    message = friendly_error(YouTubeAdapterError("metadata request failed"))
    assert message.startswith("YouTube-Import fehlgeschlagen:")
    assert "Unerwarteter Fehler" not in message


def test_apimaster_missing_key_still_wins() -> None:
    # Guard the ordering: the APIMaster branch must keep running first.
    assert "APIMaster-API-Key" in friendly_error(APIMasterMissingKeyError())
