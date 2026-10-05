"""Owner file import: PDF and plain-text uploads become shared Sources.

The importer persists the same Source → SourceVersion → SourceSegment rows as
the YouTube path and then hands the source to the canonical processing
pipeline (structure → units → concepts → retrieval index).  Positions are
character offsets — non-timed sources have no seconds; provenance back to
pages travels through ``provider_metadata["segment_pages"]``.
"""

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.core.ayin.domain import CorpusZone
from app.core.exceptions import ApplicationError
from app.db.session import Database
from app.knowledge.domain import IngestionStatus, SourceType
from app.knowledge.models import (
    Source,
    SourceQuality,
    SourceSegment,
    SourceVersion,
)
from app.knowledge.normalization import normalize_external_text
from app.knowledge.structure.scheduler import schedule_structure_analysis
from app.knowledge.structure.service import SourceStructureService

ACQUISITION_TOOL = "owner-file-upload"
ACQUISITION_VERSION = "file-import-v1"
NORMALIZATION_VERSION = "external-text-v1"
PLATFORM = "upload"
MAX_BYTES = 20_000_000
_SEGMENT_TARGET = 2_400
_PDF_MAGIC = b"%PDF-"


class FileImportError(ApplicationError):
    code = "file_import_error"
    public_message = "The file could not be imported."
    status_code = 422


@dataclass(frozen=True)
class PageSegment:
    page: int
    text: str


def _pdf_pages(data: bytes) -> list[str]:
    if not data.startswith(_PDF_MAGIC):
        raise FileImportError("The file is not a valid PDF.")
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return [page.extract_text() or "" for page in reader.pages]
    except FileImportError:
        raise
    except Exception as exc:
        raise FileImportError(f"Could not read the PDF: {type(exc).__name__}") from exc


def _chunk(text: str, *, target: int = _SEGMENT_TARGET) -> list[str]:
    """Split text into paragraph-aligned chunks of at most ``target`` chars."""

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > target:
            chunks.append(current)
            current = ""
        if len(paragraph) > target:
            if current:
                chunks.append(current)
                current = ""
            for index in range(0, len(paragraph), target):
                chunks.append(paragraph[index : index + target])
            continue
        current = f"{current}\n\n{paragraph}".strip() if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def _segments_for(
    data: bytes, filename: str, source_type: SourceType
) -> tuple[list[PageSegment], int]:
    """Turn upload bytes into (page, text) segments; page 0 means no page."""

    if source_type is SourceType.PDF:
        pages = _pdf_pages(data)
        segments = [
            PageSegment(page=index + 1, text=chunk)
            for index, page in enumerate(pages)
            for chunk in _chunk(page)
        ]
        return segments, len(pages)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FileImportError("The file is not valid UTF-8 text.") from exc
    del filename
    return [PageSegment(page=0, text=chunk) for chunk in _chunk(text)], 0


async def import_file_resource(
    database: Database,
    *,
    filename: str,
    data: bytes,
    source_type: SourceType,
    title: str | None = None,
    creator: str | None = None,
    language: str = "en",
    schedule: bool = True,
) -> UUID:
    """Persist an uploaded file as a shared Source and queue processing.

    Identical uploads deduplicate on ``(platform, external_id)`` — importing
    the same bytes twice returns the existing source instead of duplicating.
    """

    if source_type not in {SourceType.PDF, SourceType.BOOK, SourceType.MANUAL_UPLOAD}:
        raise FileImportError("Unsupported upload type.")
    if not data:
        raise FileImportError("The uploaded file is empty.")
    if len(data) > MAX_BYTES:
        raise FileImportError("The file exceeds the 20 MB upload limit.")
    segments, page_count = _segments_for(data, filename, source_type)
    if not segments or not any(segment.text for segment in segments):
        raise FileImportError("No readable text could be extracted from the file.")

    external_id = hashlib.sha256(data).hexdigest()[:48]
    digest = hashlib.sha256(data).hexdigest()
    resolved_title = (title or "").strip() or filename.rsplit(".", 1)[0] or filename
    async with database.transaction() as session:
        existing = await session.scalar(
            select(Source.id).where(
                Source.platform == PLATFORM, Source.external_id == external_id
            )
        )
        if existing is not None:
            return existing
        source = Source(
            source_type=source_type,
            platform=PLATFORM,
            external_id=external_id,
            canonical_url=f"upload://{external_id}",
            title=resolved_title[:1024],
            description=creator or None,
            language=language or "en",
            raw_metadata={
                "filename": filename,
                "creator": creator or "",
                "pages": page_count,
            },
            ingestion_status=IngestionStatus.DISCOVERED,
        )
        session.add(source)
        await session.flush()
        session.add(
            SourceQuality(
                source_id=source.id,
                publication_type="owner_upload",
                peer_reviewed=None,
                primary_or_secondary="secondary",
                retraction_status=None,
                review_notes=(
                    "Owner-uploaded file; epistemic status is assigned per "
                    "knowledge unit, not per file."
                ),
                retrieval_weight=1.0,
            )
        )
        version = SourceVersion(
            source_id=source.id,
            content_hash=digest,
            transcript_hash=digest,
            corpus_zone=CorpusZone.EXTERNAL_PRIMARY,
            provider_metadata={
                "filename": filename,
                "creator": creator or "",
                "pages": page_count,
                "segment_pages": {
                    str(index + 1): segment.page
                    for index, segment in enumerate(segments)
                },
            },
            acquisition_tool=ACQUISITION_TOOL,
            acquisition_version=ACQUISITION_VERSION,
            normalization_version=NORMALIZATION_VERSION,
            acquired_at=datetime.now(UTC),
        )
        session.add(version)
        await session.flush()
        position = Decimal(0)
        for sequence, segment in enumerate(segments, start=1):
            end = position + Decimal(max(len(segment.text), 1))
            session.add(
                SourceSegment(
                    source_version_id=version.id,
                    sequence=sequence,
                    start_seconds=position,
                    end_seconds=end,
                    raw_text=segment.text,
                    normalized_text=normalize_external_text(segment.text),
                    language=source.language,
                    content_hash=hashlib.sha256(segment.text.encode()).hexdigest(),
                )
            )
            position = end
        source.ingestion_status = IngestionStatus.INGESTED
    await SourceStructureService(database).mark_ingested(source.id)
    if schedule:
        schedule_structure_analysis(database, source.id)
    return source.id


WEB_PLATFORM = "web"


async def import_web_resource(
    database: Database,
    *,
    url: str,
    title: str,
    text: str,
    provider: str,
    query: str | None = None,
    answer_text: str = "",
    channel_ids: tuple[UUID, ...] = (),
    language: str = "en",
    schedule: bool = True,
    publication_type: str = "web_research",
    retrieval_weight: float = 1.0,
    quality_notes: str | None = None,
) -> tuple[UUID, bool]:
    """Persist a fetched web page as a WEBPAGE source.

    Returns ``(source_id, created)`` — dedupe is on the canonical URL, so a
    re-discovered page reuses the existing source. The provider's synthesized
    answer is kept only in ``raw_metadata``; source segments contain the real
    fetched page text, never the synthesis.
    """

    if not url.startswith(("http://", "https://")):
        raise FileImportError("Web resources require an http(s) URL.")
    segments = [PageSegment(page=0, text=chunk) for chunk in _chunk(text)]
    if not segments:
        raise FileImportError("No readable text could be extracted from the page.")
    external_id = hashlib.sha256(url.encode()).hexdigest()[:48]
    digest = hashlib.sha256(text.encode()).hexdigest()
    async with database.transaction() as session:
        existing = await session.scalar(
            select(Source.id).where(
                Source.platform == WEB_PLATFORM, Source.external_id == external_id
            )
        )
        if existing is not None:
            source_id = existing
            created = False
        else:
            source = Source(
                source_type=SourceType.WEBPAGE,
                platform=WEB_PLATFORM,
                external_id=external_id,
                canonical_url=url[:1024],
                title=(title or url)[:1024],
                language=language or "en",
                raw_metadata={
                    "research_provider": provider,
                    "research_query": query or "",
                    "research_answer": answer_text[:4000],
                },
                ingestion_status=IngestionStatus.DISCOVERED,
            )
            session.add(source)
            await session.flush()
            session.add(
                SourceQuality(
                    source_id=source.id,
                    publication_type=publication_type,
                    peer_reviewed=None,
                    primary_or_secondary="secondary",
                    retraction_status=None,
                    review_notes=(
                        quality_notes
                        or (
                            "Fetched via owner-configured web research; "
                            "epistemic status is assigned per knowledge unit, "
                            "not per page."
                        )
                    ),
                    retrieval_weight=retrieval_weight,
                )
            )
            version = SourceVersion(
                source_id=source.id,
                content_hash=digest,
                transcript_hash=digest,
                corpus_zone=CorpusZone.EXTERNAL_PRIMARY,
                provider_metadata={
                    "fetched_url": url,
                    "research_provider": provider,
                    "segment_pages": {},
                },
                acquisition_tool=provider,
                acquisition_version="web-research-v1",
                normalization_version=NORMALIZATION_VERSION,
                acquired_at=datetime.now(UTC),
            )
            session.add(version)
            await session.flush()
            position = Decimal(0)
            for sequence, segment in enumerate(segments, start=1):
                end = position + Decimal(max(len(segment.text), 1))
                session.add(
                    SourceSegment(
                        source_version_id=version.id,
                        sequence=sequence,
                        start_seconds=position,
                        end_seconds=end,
                        raw_text=segment.text,
                        normalized_text=normalize_external_text(segment.text),
                        language=source.language,
                        content_hash=hashlib.sha256(segment.text.encode()).hexdigest(),
                    )
                )
                position = end
            source.ingestion_status = IngestionStatus.INGESTED
            await session.flush()
            source_id = source.id
            created = True
    if created:
        await SourceStructureService(database).mark_ingested(source_id)
        if schedule:
            schedule_structure_analysis(database, source_id)
    if channel_ids:
        from app.editorial_channels.service import EditorialChannelService

        channel_service = EditorialChannelService(database)
        for channel_id in channel_ids:
            await channel_service.assign_resource(channel_id, source_id)
    return source_id, created
