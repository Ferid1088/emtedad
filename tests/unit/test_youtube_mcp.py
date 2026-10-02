"""Unit tests for the YouTube MCP transport and adapter — no live calls."""

import json
from typing import Any

import pytest

from app.core.config import Environment, Settings
from app.knowledge.adapters import youtube_mcp
from app.knowledge.adapters.youtube import (
    YouTubeRateLimitedError,
    YouTubeTranscriptUnavailableError,
)
from app.knowledge.adapters.youtube_mcp import (
    YouTubeMcpAdapter,
    YouTubeMcpClient,
    YouTubeMcpError,
    YouTubeMcpUnavailableError,
    resolve_youtube_adapter,
)


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = dict(
        environment=Environment.DEVELOPMENT,
        database_url="postgresql+psycopg://localhost/test",
        storage_root="/tmp",
    )
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


class _FakeResponse:
    def __init__(
        self,
        status: int,
        body: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status
        self.text = body
        self.headers = headers or {}

    def json(self) -> Any:
        return json.loads(self.text)


class _FakeAsyncClient:
    """Scripted stand-in for httpx.AsyncClient."""

    scripted: list[Any] = []
    calls: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, url: str, json: Any = None, headers: Any = None) -> Any:
        type(self).calls.append({"url": url, "json": json, "headers": headers})
        outcome = type(self).scripted.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _sse(payload: dict[str, Any], session: str = "sess") -> _FakeResponse:
    return _FakeResponse(
        200,
        f"data: {json.dumps(payload)}\n\n",
        {"mcp-session-id": session, "content-type": "text/event-stream"},
    )


def _tool_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {
        "jsonrpc": "2.0",
        "id": "call",
        "result": {
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
            "structuredContent": {"result": text},
        },
    }


def _script(*outcomes: Any) -> None:
    _FakeAsyncClient.scripted = [
        _sse({"jsonrpc": "2.0", "id": "init", "result": {}}),
        _FakeResponse(202, ""),
        *outcomes,
    ]
    _FakeAsyncClient.calls = []


@pytest.fixture(autouse=True)
def _patch_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(youtube_mcp.httpx, "AsyncClient", _FakeAsyncClient)


@pytest.mark.asyncio
async def test_tool_discovery_lists_real_tools() -> None:
    _script(
        _sse(
            {
                "jsonrpc": "2.0",
                "id": "call",
                "result": {"tools": [{"name": "get_transcript"}]},
            }
        )
    )
    client = YouTubeMcpClient("http://127.0.0.1:8790")
    assert await client.list_tools() == ["get_transcript"]
    methods = [call["json"]["method"] for call in _FakeAsyncClient.calls]
    assert methods[0] == "initialize"
    assert "notifications/initialized" in methods
    assert methods[-1] == "tools/list"


@pytest.mark.asyncio
async def test_transcript_mapping_preserves_timestamps() -> None:
    _script(
        _sse(
            _tool_result(
                [
                    {"text": "salam", "timestamp": "0:00", "start_seconds": 0.0},
                    {"text": "chetori", "timestamp": "0:05", "start_seconds": 5.2},
                    {"text": "end", "timestamp": "0:10", "start_seconds": 10.0},
                ]
            )
        )
    )
    client = YouTubeMcpClient("http://x")
    transcript = await client.get_transcript(
        "https://youtube.com/watch?v=dQw4w9WgXcQ", language="fa"
    )
    assert transcript.video_id == "dQw4w9WgXcQ"
    assert transcript.language == "fa"
    assert [s.start_seconds for s in transcript.segments] == [0.0, 5.2, 10.0]
    # durations derived from consecutive starts
    assert transcript.segments[0].duration_seconds == 5.2
    assert transcript.segments[1].duration_seconds == 4.8
    assert transcript.segments[2].duration_seconds is None
    assert transcript.full_text == "salam chetori end"


@pytest.mark.asyncio
async def test_empty_transcript_raises_unavailable() -> None:
    _script(_sse(_tool_result([])))
    client = YouTubeMcpClient("http://x")
    with pytest.raises(YouTubeTranscriptUnavailableError):
        await client.get_transcript("https://youtube.com/watch?v=dQw4w9WgXcQ")


@pytest.mark.asyncio
async def test_ip_block_maps_to_rate_limit() -> None:
    _script(
        _sse(
            _tool_result(
                {
                    "error": "YouTube is temporarily blocking transcript "
                    "requests from your IP."
                }
            )
        )
    )
    client = YouTubeMcpClient("http://x")
    with pytest.raises(YouTubeRateLimitedError):
        await client.get_transcript("https://youtube.com/watch?v=dQw4w9WgXcQ")


@pytest.mark.asyncio
async def test_no_transcript_maps_to_unavailable() -> None:
    _script(
        _sse(
            _tool_result(
                {"error": "No transcript available for this video."}
            )
        )
    )
    client = YouTubeMcpClient("http://x")
    with pytest.raises(YouTubeTranscriptUnavailableError):
        await client.get_transcript("https://youtube.com/watch?v=dQw4w9WgXcQ")


@pytest.mark.asyncio
async def test_unreachable_server_raises_unavailable() -> None:
    import httpx

    _FakeAsyncClient.scripted = [httpx.ConnectError("refused")]
    _FakeAsyncClient.calls = []
    client = YouTubeMcpClient("http://127.0.0.1:1")
    with pytest.raises(YouTubeMcpUnavailableError):
        await client.list_tools()


@pytest.mark.asyncio
async def test_timeout_raises_unavailable() -> None:
    import httpx

    _FakeAsyncClient.scripted = [httpx.ReadTimeout("slow")]
    _FakeAsyncClient.calls = []
    client = YouTubeMcpClient("http://x")
    with pytest.raises(YouTubeMcpUnavailableError):
        await client.list_tools()


@pytest.mark.asyncio
async def test_tool_error_flag_raises() -> None:
    _script(
        _sse(_tool_result("boom", is_error=True))
    )
    client = YouTubeMcpClient("http://x")
    with pytest.raises(YouTubeMcpError, match="boom"):
        await client.get_video_info("https://youtube.com/watch?v=dQw4w9WgXcQ")


def test_resolve_adapter_defaults_to_direct() -> None:
    adapter = resolve_youtube_adapter(_settings(youtube_mcp_enabled=False))
    assert type(adapter).__name__ == "YouTubeAdapter"


def test_resolve_adapter_uses_mcp_when_enabled() -> None:
    adapter = resolve_youtube_adapter(_settings(youtube_mcp_enabled=True))
    assert isinstance(adapter, YouTubeMcpAdapter)


@pytest.mark.asyncio
async def test_adapter_acquire_maps_snapshot() -> None:
    info = {
        "id": "dQw4w9WgXcQ",
        "title": "Talk",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "channel": "Chan",
        "channel_url": "https://www.youtube.com/channel/UCx",
        "duration_seconds": 120,
        "upload_date": "20260101",
        "description": "desc",
    }
    segments = [
        {"text": "one", "start_seconds": 0.0},
        {"text": "two", "start_seconds": 3.0},
    ]
    _script(_sse(_tool_result(info)), _sse(_tool_result(segments)))
    adapter = YouTubeMcpAdapter(YouTubeMcpClient("http://x"))
    snapshot = await adapter.acquire("https://youtu.be/dQw4w9WgXcQ")
    assert snapshot.external_id == "dQw4w9WgXcQ"
    assert snapshot.title == "Talk"
    assert snapshot.language == "fa"
    assert snapshot.transcript_kind == "unknown"
    assert [e.start_seconds for e in snapshot.transcript] == [0.0, 3.0]
    assert snapshot.transcript[0].duration_seconds == 3.0
    assert snapshot.published_at is not None


@pytest.mark.asyncio
async def test_adapter_list_channel_videos() -> None:
    videos = [
        {
            "id": "dQw4w9WgXcQ",
            "title": "V",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "duration_seconds": 60,
        }
    ]
    _script(_sse(_tool_result(videos)))
    adapter = YouTubeMcpAdapter(YouTubeMcpClient("http://x"))
    result = await adapter.list_channel_videos(
        "https://www.youtube.com/@chan"
    )
    assert result[0].youtube_video_id == "dQw4w9WgXcQ"
    assert result[0].duration_seconds == 60


@pytest.mark.asyncio
async def test_adapter_resolve_channel() -> None:
    _script(
        _sse(
            _tool_result(
                {
                    "id": "UCabc123def456ghi789jkl",
                    "name": "Chan",
                    "url": "https://www.youtube.com/channel/UCabc123def456ghi789jkl",
                }
            )
        )
    )
    adapter = YouTubeMcpAdapter(YouTubeMcpClient("http://x"))
    snapshot = await adapter.resolve_channel("https://www.youtube.com/@chan")
    assert snapshot.external_channel_id == "UCabc123def456ghi789jkl"
    assert snapshot.name == "Chan"
    assert snapshot.handle == "@chan"


@pytest.mark.asyncio
async def test_invalid_video_id_rejected() -> None:
    client = YouTubeMcpClient("http://x")
    with pytest.raises(ValueError, match="invalid"):
        await client.get_transcript("https://example.com/not-youtube")


def test_settings_have_mcp_fields() -> None:
    settings = _settings()
    assert settings.youtube_mcp_enabled is False
    assert settings.youtube_mcp_url == "http://127.0.0.1:8790"
    assert settings.youtube_mcp_timeout_seconds == 60
