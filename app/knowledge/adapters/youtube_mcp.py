"""YouTube access through a local MCP server (streamable-http transport).

The ``YouTubeMcpAdapter`` implements the same ``SourceAdapter`` contract as
``YouTubeAdapter`` — metadata and transcripts flow through the MCP server
instead of direct yt-dlp/youtube-transcript-api calls, and everything lands
in the existing ingestion pipeline unchanged.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.knowledge.adapters.base import (
    ChannelSnapshot,
    ChannelVideoSnapshot,
    ExternalSourceSnapshot,
    TranscriptEntry,
)
from app.knowledge.adapters.youtube import (
    YouTubeAdapter,
    YouTubeAdapterError,
    YouTubeRateLimitedError,
    YouTubeTranscriptUnavailableError,
    parse_youtube_channel_locator,
    parse_youtube_video_id,
)
from app.knowledge.domain import SourceType

logger = logging.getLogger(__name__)


class YouTubeMcpError(YouTubeAdapterError):
    """Raised when the MCP transport or a tool call fails."""


class YouTubeMcpUnavailableError(YouTubeMcpError):
    """Raised when the MCP server is unreachable — check the service."""


class YouTubeVideo(BaseModel):
    video_id: str
    title: str
    url: str
    channel: str | None = None
    channel_url: str | None = None
    published_at: datetime | None = None
    duration_seconds: int | None = None
    views: int | None = None


class YouTubeChannelInfo(BaseModel):
    channel_id: str
    name: str
    url: str
    subscribers: int | None = None
    description: str | None = None
    video_count: int | None = None


class YouTubeTranscriptSegment(BaseModel):
    text: str
    start_seconds: float
    duration_seconds: float | None = None


class YouTubeTranscript(BaseModel):
    video_id: str
    language: str
    segments: list[YouTubeTranscriptSegment]
    full_text: str = ""

    @property
    def entry_count(self) -> int:
        return len(self.segments)


class YouTubeMcpClient:
    """Minimal JSON-RPC client for a streamable-http MCP endpoint."""

    def __init__(self, url: str, *, timeout_seconds: float = 30) -> None:
        self._url = url.rstrip("/")
        self._timeout = timeout_seconds
        self._session_id: str | None = None
        self._lock = asyncio.Lock()

    async def _request(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
        *,
        notification: bool = False,
    ) -> dict[str, Any] | None:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        try:
            response = await client.post(
                f"{self._url}/mcp", json=payload, headers=headers
            )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise YouTubeMcpUnavailableError(
                f"youtube mcp unreachable: {type(exc).__name__}"
            ) from exc
        if response.status_code == 404 and self._session_id:
            self._session_id = None
            raise YouTubeMcpUnavailableError("mcp session expired")
        if response.status_code >= 400:
            raise YouTubeMcpError(f"mcp http error: {response.status_code}")
        session_header = response.headers.get("mcp-session-id")
        if session_header:
            self._session_id = session_header
        if notification or response.status_code == 202:
            return None
        return _parse_response_body(response)

    async def _call(
        self, payload: dict[str, Any], *, notification: bool = False
    ) -> dict[str, Any] | None:
        async with (
            self._lock,
            httpx.AsyncClient(timeout=self._timeout) as client,
        ):
            try:
                return await self._request(
                    client, payload, notification=notification
                )
            except YouTubeMcpUnavailableError:
                if self._session_id is not None:
                    raise
                await self._initialize(client)
                return await self._request(
                    client, payload, notification=notification
                )

    async def _initialize(self, client: httpx.AsyncClient) -> None:
        result = await self._request(
            client,
            {
                "jsonrpc": "2.0",
                "id": "init",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "emtedad", "version": "0.1"},
                },
            },
        )
        if not isinstance(result, dict) or "result" not in result:
            raise YouTubeMcpError("mcp initialize failed")
        await self._request(
            client,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            notification=True,
        )

    async def _rpc(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if self._session_id is None:
            async with (
                self._lock,
                httpx.AsyncClient(timeout=self._timeout) as client,
            ):
                if self._session_id is None:
                    await self._initialize(client)
        response = await self._call(
            {
                "jsonrpc": "2.0",
                "id": "call",
                "method": method,
                "params": params or {},
            }
        )
        if not isinstance(response, dict):
            raise YouTubeMcpError("mcp returned no response")
        if "error" in response:
            detail = response["error"]
            raise YouTubeMcpError(f"mcp rpc error: {detail}")
        return response

    async def _tool(self, name: str, arguments: dict[str, Any]) -> Any:
        response = await self._rpc(
            "tools/call", {"name": name, "arguments": arguments}
        )
        result = response.get("result")
        if not isinstance(result, dict):
            raise YouTubeMcpError(f"mcp tool {name} returned malformed result")
        text = _content_text(result)
        if result.get("isError"):
            _raise_tool_error(name, text or "tool call failed")
        payload: Any = None
        structured = result.get("structuredContent")
        if isinstance(structured, dict) and "result" in structured:
            payload = structured["result"]
        elif text:
            payload = text
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                if '"error"' in payload:
                    _raise_tool_error(name, payload[:300])
                return payload
        if isinstance(payload, dict) and "error" in payload:
            _raise_tool_error(name, str(payload["error"]))
        return payload

    async def list_tools(self) -> list[str]:
        response = await self._rpc("tools/list")
        tools = response.get("result", {}).get("tools", [])
        return [str(tool.get("name")) for tool in tools]

    async def health(self) -> bool:
        try:
            return bool(await self.list_tools())
        except YouTubeAdapterError:
            return False

    async def get_video_info(self, video_url: str) -> dict[str, Any]:
        payload = await self._tool(
            "get_video_info", {"video_url": video_url}
        )
        if not isinstance(payload, dict):
            raise YouTubeMcpError("get_video_info returned no object")
        return payload

    async def get_channel_info(self, channel: str) -> YouTubeChannelInfo:
        payload = await self._tool("get_channel_info", {"channel": channel})
        if not isinstance(payload, dict):
            raise YouTubeMcpError("get_channel_info returned no object")
        channel_id = _str(payload.get("id"))
        if channel_id is None:
            raise YouTubeMcpError("get_channel_info returned no channel id")
        return YouTubeChannelInfo(
            channel_id=channel_id,
            name=_str(payload.get("name")) or channel_id,
            url=_str(payload.get("url")) or "",
            subscribers=_int(payload.get("subscribers")),
            description=_str(payload.get("description")),
            video_count=_int(payload.get("video_count")),
        )

    async def get_channel_videos(
        self, channel: str, *, limit: int = 20, sort: str = "date"
    ) -> list[YouTubeVideo]:
        payload = await self._tool(
            "get_channel_videos",
            {"channel": channel, "limit": limit, "sort": sort},
        )
        if not isinstance(payload, list):
            raise YouTubeMcpError("get_channel_videos returned no list")
        videos: list[YouTubeVideo] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            video_id = _str(item.get("id"))
            if video_id is None:
                continue
            videos.append(
                YouTubeVideo(
                    video_id=video_id,
                    title=_str(item.get("title")) or video_id,
                    url=_str(item.get("url"))
                    or f"https://www.youtube.com/watch?v={video_id}",
                    channel=_str(item.get("channel")) or None,
                    channel_url=_str(item.get("channel_url")),
                    published_at=_upload_date(item.get("upload_date")),
                    duration_seconds=_int(item.get("duration_seconds")),
                    views=_int(item.get("views")),
                )
            )
        return videos

    async def get_transcript(
        self, video_url: str, *, language: str = "fa"
    ) -> YouTubeTranscript:
        video_id = parse_youtube_video_id(video_url)
        payload = await self._tool(
            "get_transcript", {"video_url": video_url, "language": language}
        )
        if not isinstance(payload, list):
            raise YouTubeMcpError("get_transcript returned no segment list")
        raw = [
            item
            for item in payload
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
        if not raw:
            raise YouTubeTranscriptUnavailableError("video transcript is empty")
        segments: list[YouTubeTranscriptSegment] = []
        starts = [
            float(item.get("start_seconds") or item.get("start") or 0.0)
            for item in raw
        ]
        for index, item in enumerate(raw):
            start = starts[index]
            duration = (
                float(item["duration"])
                if isinstance(item.get("duration"), int | float)
                else (
                    round(starts[index + 1] - start, 3)
                    if index + 1 < len(starts)
                    else None
                )
            )
            segments.append(
                YouTubeTranscriptSegment(
                    text=str(item["text"]),
                    start_seconds=start,
                    duration_seconds=duration,
                )
            )
        return YouTubeTranscript(
            video_id=video_id,
            language=language,
            segments=segments,
            full_text=" ".join(segment.text for segment in segments),
        )

    async def search_transcript(
        self, video_url: str, query: str, *, language: str = "fa"
    ) -> list[dict[str, Any]]:
        payload = await self._tool(
            "search_transcript",
            {"video_url": video_url, "query": query, "language": language},
        )
        return payload if isinstance(payload, list) else []


class YouTubeMcpAdapter:
    """``SourceAdapter`` implementation backed by the YouTube MCP server."""

    def __init__(self, client: YouTubeMcpClient | None = None) -> None:
        if client is None:
            settings = get_settings()
            client = YouTubeMcpClient(
                settings.youtube_mcp_url,
                timeout_seconds=settings.youtube_mcp_timeout_seconds,
            )
        self._client = client

    async def acquire(self, locator: str) -> ExternalSourceSnapshot:
        video_id = parse_youtube_video_id(locator)
        url = f"https://www.youtube.com/watch?v={video_id}"
        metadata, transcript = await asyncio.gather(
            self._client.get_video_info(url),
            self._client.get_transcript(url, language="fa"),
        )
        entries = tuple(
            TranscriptEntry(
                sequence=index,
                start_seconds=segment.start_seconds,
                duration_seconds=max(segment.duration_seconds or 0.001, 0.001),
                text=segment.text,
            )
            for index, segment in enumerate(transcript.segments, start=1)
        )
        if not entries:
            raise YouTubeTranscriptUnavailableError("video transcript is empty")
        return ExternalSourceSnapshot(
            source_type=SourceType.YOUTUBE_VIDEO,
            platform="youtube",
            external_id=video_id,
            canonical_url=url,
            title=_str(metadata.get("title")) or video_id,
            description=_str(metadata.get("description")),
            language=transcript.language,
            published_at=_upload_date(metadata.get("upload_date")),
            duration_seconds=_int(metadata.get("duration_seconds")),
            channel_external_id=_str(metadata.get("channel_id")),
            channel_title=_str(metadata.get("channel")),
            channel_url=_str(metadata.get("channel_url")),
            creator_name=_str(metadata.get("channel")),
            transcript_kind="unknown",
            metadata={
                key: metadata[key]
                for key in ("id", "url", "title", "duration_seconds",
                            "upload_date", "views", "likes", "tags")
                if metadata.get(key) is not None
            } | {"transport": "youtube-mcp"},
            transcript=entries,
            thumbnail_url=None,
        )

    async def resolve_channel(self, locator: str) -> ChannelSnapshot:
        url = parse_youtube_channel_locator(locator)
        info = await self._client.get_channel_info(url)
        handle = None
        if "@" in url:
            handle = url.rsplit("/", 1)[-1]
        return ChannelSnapshot(info.channel_id, info.name, info.url or url, handle)

    async def list_channel_videos(
        self, locator: str
    ) -> tuple[ChannelVideoSnapshot, ...]:
        url = parse_youtube_channel_locator(locator)
        videos = await self._client.get_channel_videos(url, limit=100)
        return tuple(
            ChannelVideoSnapshot(
                youtube_video_id=video.video_id,
                title=video.title,
                published_at=video.published_at,
                thumbnail_url=None,
                duration_seconds=video.duration_seconds,
            )
            for video in videos
        )


def resolve_youtube_adapter(
    settings: Settings | None = None,
) -> YouTubeAdapter | YouTubeMcpAdapter:
    """Return the configured YouTube transport — MCP when enabled."""

    resolved = settings or get_settings()
    if resolved.youtube_mcp_enabled:
        return YouTubeMcpAdapter(
            YouTubeMcpClient(
                resolved.youtube_mcp_url,
                timeout_seconds=resolved.youtube_mcp_timeout_seconds,
            )
        )
    return YouTubeAdapter()


def _parse_response_body(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        result: dict[str, Any] | None = None
        for line in response.text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            try:
                result = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
        if result is None:
            raise YouTubeMcpError("mcp sse stream contained no json")
        return result
    try:
        value = response.json()
    except json.JSONDecodeError as exc:
        raise YouTubeMcpError("mcp returned non-json response") from exc
    if not isinstance(value, dict):
        raise YouTubeMcpError("mcp response must be a json object")
    return value


def _content_text(result: dict[str, Any]) -> str:
    for item in result.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            return str(item.get("text") or "")
    return ""


def _raise_tool_error(name: str, message: str) -> None:
    text = message.lower()
    if "blocking" in text or "rate" in text or "429" in text:
        raise YouTubeRateLimitedError(f"{name}: {message}")
    if "no transcript" in text or "disabled" in text or "unavailable" in text:
        raise YouTubeTranscriptUnavailableError(f"{name}: {message}")
    raise YouTubeMcpError(f"{name}: {message}")


def _str(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and value.strip() else None


def _int(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) else None


def _upload_date(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return None
