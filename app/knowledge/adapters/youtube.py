"""Generic YouTube metadata and timestamped-transcript adapter."""

import asyncio
import json
import re
import subprocess
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import YouTubeTranscriptApi

from app.knowledge.adapters.base import ExternalSourceSnapshot, TranscriptEntry
from app.knowledge.domain import SourceType

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class YouTubeAdapterError(RuntimeError):
    """Raised when provider metadata or transcript acquisition fails."""


def parse_youtube_video_id(locator: str) -> str:
    """Return a validated video ID from an ID or supported YouTube URL."""

    candidate = locator.strip()
    if _VIDEO_ID.fullmatch(candidate):
        return candidate
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if host in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/").split("/", 1)[0]
    elif host in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
    }:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        else:
            parts = parsed.path.strip("/").split("/")
            candidate = (
                parts[1]
                if len(parts) == 2
                and parts[0]
                in {
                    "embed",
                    "shorts",
                    "live",
                }
                else ""
            )
    else:
        candidate = ""
    if not _VIDEO_ID.fullmatch(candidate):
        raise ValueError("invalid YouTube video URL or ID")
    return candidate


class YouTubeAdapter:
    """Acquire YouTube metadata with yt-dlp and captions with the transcript API."""

    def __init__(
        self,
        *,
        metadata_timeout_seconds: int = 60,
        yt_dlp_executable: str = "yt-dlp",
    ) -> None:
        self._timeout = metadata_timeout_seconds
        self._executable = yt_dlp_executable

    async def acquire(self, locator: str) -> ExternalSourceSnapshot:
        video_id = parse_youtube_video_id(locator)
        metadata, transcript = await asyncio.gather(
            asyncio.to_thread(self._metadata, video_id),
            asyncio.to_thread(self._transcript, video_id),
        )
        entries, language_code, kind = transcript
        published_at = _upload_date(metadata.get("upload_date"))
        duration = metadata.get("duration")
        channel_id = _optional_string(metadata.get("channel_id"))
        channel_url = _optional_string(metadata.get("channel_url"))
        channel_title = _optional_string(metadata.get("channel"))
        creator_name = _optional_string(metadata.get("uploader")) or channel_title
        thumbnail = _optional_string(metadata.get("thumbnail"))
        kept_metadata: dict[str, object] = {
            key: value
            for key, value in metadata.items()
            if key
            in {
                "id",
                "webpage_url",
                "title",
                "description",
                "duration",
                "upload_date",
                "channel_id",
                "channel",
                "channel_url",
                "uploader",
                "uploader_id",
                "uploader_url",
                "thumbnail",
                "availability",
                "license",
            }
            and value is not None
        }
        return ExternalSourceSnapshot(
            source_type=SourceType.YOUTUBE_VIDEO,
            platform="youtube",
            external_id=video_id,
            canonical_url=f"https://www.youtube.com/watch?v={video_id}",
            title=str(metadata.get("title") or video_id),
            description=_optional_string(metadata.get("description")),
            language=language_code,
            published_at=published_at,
            duration_seconds=int(duration)
            if isinstance(duration, int | float)
            else None,
            channel_external_id=channel_id
            or _optional_string(metadata.get("uploader_id")),
            channel_title=channel_title,
            channel_url=channel_url or _optional_string(metadata.get("uploader_url")),
            creator_name=creator_name,
            transcript_kind=kind,
            metadata=kept_metadata,
            transcript=entries,
            thumbnail_url=thumbnail,
        )

    def _metadata(self, video_id: str) -> dict[str, object]:
        command = [
            self._executable,
            "--dump-single-json",
            "--skip-download",
            "--no-warnings",
            f"https://www.youtube.com/watch?v={video_id}",
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise YouTubeAdapterError(
                f"metadata acquisition failed: {type(exc).__name__}"
            ) from exc
        if result.returncode != 0:
            diagnostic = result.stderr.strip()[-1000:]
            raise YouTubeAdapterError(f"metadata acquisition failed: {diagnostic}")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise YouTubeAdapterError("yt-dlp returned invalid metadata JSON") from exc
        if not isinstance(value, dict):
            raise YouTubeAdapterError("yt-dlp metadata must be an object")
        return value

    @staticmethod
    def _transcript(
        video_id: str,
    ) -> tuple[tuple[TranscriptEntry, ...], str, str]:
        try:
            transcripts = YouTubeTranscriptApi().list(video_id)
            available = list(transcripts)
            if not available:
                raise YouTubeAdapterError("video has no transcript")
            preferred = next(
                (item for item in available if item.language_code.startswith("fa")),
                available[0],
            )
            fetched = preferred.fetch(preserve_formatting=True)
        except YouTubeAdapterError:
            raise
        except Exception as exc:
            raise YouTubeAdapterError(
                f"transcript acquisition failed: {type(exc).__name__}"
            ) from exc
        entries = tuple(
            TranscriptEntry(
                sequence=index,
                start_seconds=float(item.start),
                duration_seconds=max(float(item.duration), 0.001),
                text=item.text,
            )
            for index, item in enumerate(fetched, start=1)
            if item.text.strip()
        )
        if not entries:
            raise YouTubeAdapterError("video transcript is empty")
        language = preferred.language_code
        kind = "generated" if preferred.is_generated else "manual"
        return entries, language, kind


def _optional_string(value: object) -> str | None:
    return str(value) if isinstance(value, str) and value.strip() else None


def _upload_date(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return None
