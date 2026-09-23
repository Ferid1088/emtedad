import pytest

from app.knowledge.adapters.youtube import parse_youtube_channel_locator


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
