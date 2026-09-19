"""Rights-aware media acquisition, validation, rendering, and SHA deduplication."""

import asyncio
import warnings
from dataclasses import dataclass
from io import BytesIO
from uuid import UUID

import httpx
from sqlalchemy import or_, select

from app.db.session import Database
from app.knowledge.domain import MediaStatus, MediaType
from app.knowledge.models import (
    MediaAsset,
    SourceMediaAsset,
    WorkMediaAsset,
)
from app.ops.assets.repository import AssetRepository
from app.storage.base import ObjectStore

_PDF_MAGIC = b"%PDF-"


class MediaValidationError(RuntimeError):
    """Raised when downloaded bytes do not match the permitted media type."""


@dataclass(frozen=True, slots=True)
class DownloadedMedia:
    data: bytes
    mime_type: str
    width: int | None
    height: int | None


def validate_and_render_pdf(data: bytes) -> bytes:
    """Validate PDF magic/parser integrity and render only the first page."""

    if not data.startswith(_PDF_MAGIC):
        raise MediaValidationError("invalid PDF magic bytes")
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            import pymupdf

        document = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
        if document.page_count < 1:
            raise MediaValidationError("PDF has no pages")
        pixmap = document.load_page(0).get_pixmap(  # type: ignore[no-untyped-call]
            matrix=pymupdf.Matrix(1.5, 1.5)  # type: ignore[no-untyped-call]
        )
        rendered: bytes = pixmap.tobytes("png")
        return rendered
    except MediaValidationError:
        raise
    except Exception as exc:
        raise MediaValidationError(f"invalid PDF: {type(exc).__name__}") from exc


class MediaService:
    def __init__(
        self,
        database: Database,
        store: ObjectStore,
        *,
        client: httpx.AsyncClient | None = None,
        max_bytes: int = 25_000_000,
    ) -> None:
        self._database = database
        self._store = store
        self._client = client
        self._max_bytes = max_bytes

    async def source_thumbnail(
        self, source_id: UUID, source_url: str, *, attribution: str | None
    ) -> MediaAsset:
        try:
            downloaded = await self._download(source_url, expect_pdf=False)
        except Exception:
            return await self._record_source_failure(
                source_id, source_url, MediaType.THUMBNAIL, MediaStatus.FAILED
            )
        return await self._store_source(
            source_id,
            source_url,
            MediaType.THUMBNAIL,
            downloaded,
            attribution=attribution,
        )

    async def work_pdf(
        self, work_id: UUID, source_url: str
    ) -> tuple[MediaAsset, MediaAsset | None]:
        try:
            downloaded = await self._download(source_url, expect_pdf=True)
            first_page = await asyncio.to_thread(
                validate_and_render_pdf, downloaded.data
            )
        except Exception:
            failure = await self._record_work_failure(
                work_id, source_url, MediaType.PAPER_PDF, MediaStatus.NO_ACCESSIBLE_PDF
            )
            return failure, None
        pdf = await self._store_work(
            work_id, source_url, MediaType.PAPER_PDF, downloaded
        )
        rendered = DownloadedMedia(
            data=first_page,
            mime_type="image/png",
            width=None,
            height=None,
        )
        first = await self._store_work(
            work_id,
            source_url + "#first-page",
            MediaType.FIRST_PAGE,
            rendered,
        )
        return pdf, first

    async def _download(self, url: str, *, expect_pdf: bool) -> DownloadedMedia:
        if self._client is not None:
            response = await self._client.get(url, follow_redirects=True)
        else:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(url)
        response.raise_for_status()
        data = response.content
        if len(data) > self._max_bytes:
            raise MediaValidationError("media exceeds configured byte limit")
        mime = response.headers.get("content-type", "application/octet-stream").split(
            ";", 1
        )[0]
        if expect_pdf and (
            mime != "application/pdf" or not data.startswith(_PDF_MAGIC)
        ):
            raise MediaValidationError("response is not a verified PDF")
        if not expect_pdf and not mime.startswith("image/"):
            raise MediaValidationError("response is not an image")
        return DownloadedMedia(data=data, mime_type=mime, width=None, height=None)

    async def _store_source(
        self,
        source_id: UUID,
        url: str,
        media_type: MediaType,
        media: DownloadedMedia,
        *,
        attribution: str | None,
    ) -> MediaAsset:
        async with self._database.transaction() as session:
            asset = await self._store_media(
                session, url, media_type, media, attribution=attribution
            )
            if await session.get(SourceMediaAsset, (source_id, asset.id)) is None:
                session.add(
                    SourceMediaAsset(source_id=source_id, media_asset_id=asset.id)
                )
            return asset

    async def _store_work(
        self,
        work_id: UUID,
        url: str,
        media_type: MediaType,
        media: DownloadedMedia,
    ) -> MediaAsset:
        async with self._database.transaction() as session:
            asset = await self._store_media(session, url, media_type, media)
            if await session.get(WorkMediaAsset, (work_id, asset.id)) is None:
                session.add(WorkMediaAsset(work_id=work_id, media_asset_id=asset.id))
            return asset

    async def _store_media(
        self,
        session: object,
        url: str,
        media_type: MediaType,
        media: DownloadedMedia,
        *,
        attribution: str | None = None,
    ) -> MediaAsset:
        from sqlalchemy.ext.asyncio import AsyncSession

        assert isinstance(session, AsyncSession)
        stored = await asyncio.to_thread(self._store.put_stream, BytesIO(media.data))
        object_asset, _ = await AssetRepository(session).get_or_create(
            stored,
            media_type=media.mime_type,
            original_filename=url.rsplit("/", 1)[-1] or "external-media",
        )
        existing = await session.scalar(
            select(MediaAsset).where(
                MediaAsset.media_type == media_type,
                or_(
                    MediaAsset.object_asset_id == object_asset.id,
                    MediaAsset.source_url == url,
                ),
            )
        )
        if existing is not None:
            return existing
        asset = MediaAsset(
            object_asset_id=object_asset.id,
            media_type=media_type,
            source_url=url,
            width=media.width,
            height=media.height,
            license=None,
            attribution=attribution,
            rights_status="unknown",
            status=MediaStatus.AVAILABLE,
        )
        session.add(asset)
        await session.flush()
        return asset

    async def _record_source_failure(
        self, source_id: UUID, url: str, media_type: MediaType, status: MediaStatus
    ) -> MediaAsset:
        async with self._database.transaction() as session:
            asset = await self._failure(session, url, media_type, status)
            if await session.get(SourceMediaAsset, (source_id, asset.id)) is None:
                session.add(
                    SourceMediaAsset(source_id=source_id, media_asset_id=asset.id)
                )
            return asset

    async def _record_work_failure(
        self, work_id: UUID, url: str, media_type: MediaType, status: MediaStatus
    ) -> MediaAsset:
        async with self._database.transaction() as session:
            asset = await self._failure(session, url, media_type, status)
            if await session.get(WorkMediaAsset, (work_id, asset.id)) is None:
                session.add(WorkMediaAsset(work_id=work_id, media_asset_id=asset.id))
            return asset

    @staticmethod
    async def _failure(
        session: object, url: str, media_type: MediaType, status: MediaStatus
    ) -> MediaAsset:
        from sqlalchemy.ext.asyncio import AsyncSession

        assert isinstance(session, AsyncSession)
        existing = await session.scalar(
            select(MediaAsset).where(
                MediaAsset.source_url == url, MediaAsset.media_type == media_type
            )
        )
        if existing is not None:
            return existing
        asset = MediaAsset(
            object_asset_id=None,
            media_type=media_type,
            source_url=url,
            license=None,
            attribution=None,
            rights_status="unknown",
            status=status,
        )
        session.add(asset)
        await session.flush()
        return asset
