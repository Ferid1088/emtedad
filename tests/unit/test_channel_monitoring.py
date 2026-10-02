import asyncio

import pytest
from youtube_transcript_api import IpBlocked, TranscriptsDisabled

from app.knowledge.adapters import youtube as youtube_module
from app.knowledge.adapters.youtube import (
    YouTubeAdapter,
    YouTubeAdapterError,
    YouTubeRateLimitedError,
    YouTubeTranscriptUnavailableError,
    parse_youtube_channel_locator,
)


def test_channel_locator_accepts_stable_forms() -> None:
    assert parse_youtube_channel_locator("https://www.youtube.com/@mokri").endswith(
        "@mokri"
    )
    for tab in ("videos", "shorts", "streams", "featured", "about"):
        assert (
            parse_youtube_channel_locator(f"https://www.youtube.com/@mokri/{tab}")
            == "https://www.youtube.com/@mokri"
        )
    assert parse_youtube_channel_locator(
        "https://www.youtube.com/channel/UC1234567890123456789012"
    ).endswith("UC1234567890123456789012")
    assert (
        parse_youtube_channel_locator(
            "https://www.youtube.com/channel/UC1234567890123456789012/videos"
        )
        == "https://www.youtube.com/channel/UC1234567890123456789012"
    )
    assert parse_youtube_channel_locator("UC1234567890123456789012").endswith(
        "UC1234567890123456789012"
    )


def test_channel_locator_rejects_video_or_other_hosts() -> None:
    with pytest.raises(ValueError):
        parse_youtube_channel_locator("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    with pytest.raises(ValueError):
        parse_youtube_channel_locator("https://example.com/@mokri")


def test_disabled_transcripts_map_to_dedicated_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Api:
        def list(self, video_id: str):
            raise TranscriptsDisabled(video_id)

    monkeypatch.setattr(youtube_module, "YouTubeTranscriptApi", lambda: _Api())
    with pytest.raises(YouTubeTranscriptUnavailableError):
        YouTubeAdapter._transcript("abcdefghijk")


def test_other_transcript_failures_stay_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Api:
        def list(self, video_id: str):
            raise RuntimeError("network")

    monkeypatch.setattr(youtube_module, "YouTubeTranscriptApi", lambda: _Api())
    with pytest.raises(YouTubeAdapterError) as excinfo:
        YouTubeAdapter._transcript("abcdefghijk")
    assert not isinstance(excinfo.value, YouTubeTranscriptUnavailableError)


def test_ip_blocked_maps_to_rate_limited_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Api:
        def list(self, video_id: str):
            raise IpBlocked(video_id)

    monkeypatch.setattr(youtube_module, "YouTubeTranscriptApi", lambda: _Api())
    with pytest.raises(YouTubeRateLimitedError):
        YouTubeAdapter._transcript("abcdefghijk")


def test_channel_video_list_falls_back_to_videos_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = YouTubeAdapter()
    calls: list[str] = []

    def fake_metadata(url: str, limit: int = 1):
        calls.append(url)
        if url.endswith("/videos"):
            return {
                "entries": [
                    {"id": "abcdefghijk", "title": "V", "upload_date": "20240101"}
                ]
            }
        return {"entries": [{"_type": "playlist", "id": "UCxxxxxxxxxxxxxxxxxxxxxx"}]}

    monkeypatch.setattr(adapter, "_channel_metadata", fake_metadata)
    videos = asyncio.run(
        adapter.list_channel_videos(
            "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx"
        )
    )
    assert [video.youtube_video_id for video in videos] == ["abcdefghijk"]
    assert calls[1].endswith("/videos")
