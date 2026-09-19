"""Transactional external-source import with independent cached window jobs."""

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.ayin.domain import CorpusZone
from app.core.ayin.provenance import configuration_hash
from app.db.session import Database
from app.knowledge.adapters.base import ExternalSourceSnapshot, SourceAdapter
from app.knowledge.domain import (
    EntityType,
    IngestionStatus,
    KnowledgeReviewStatus,
    LabelKind,
    ResolutionStatus,
    ReviewReason,
    RunStatus,
    VerificationStatus,
    WindowStatus,
    WorkType,
)
from app.knowledge.extraction_schema import WindowExtraction
from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.knowledge.media import MediaService
from app.knowledge.models import (
    Channel,
    ChannelCreator,
    Creator,
    EntityLabel,
    ExternalClaim,
    ExternalConcept,
    ExtractionRun,
    ExtractionWindow,
    ExtractionWindowSegment,
    Mention,
    Organization,
    Person,
    ReviewFlag,
    Source,
    SourceQuality,
    SourceSegment,
    SourceVersion,
    WindowResult,
    Work,
)
from app.knowledge.normalization import normalize_external_text
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.windowing import WindowSegment, build_windows
from app.ops.assets.models import utc_now
from app.ops.logging import get_logger

TASK = "external-knowledge-extraction"
PROMPT_VERSION = "external-knowledge-v1"
INGESTER_VERSION = "youtube-v1"
NORMALIZATION_VERSION = "external-text-v1"

EXTRACTION_INSTRUCTIONS = """Extract only information explicitly present in the source
window. Return people, works, organizations, or named concepts as mentions and explicit
substantive speaker/source claims. Use the exact surface text and the segment sequence
shown in brackets. Do not invent DOI, ISBN, journal, publisher, publication year,
volume, issue, pages, OpenAlex ID, Wikidata ID, ORCID, or any other bibliographic
metadata. If
identity or title is uncertain, preserve the surface form as a candidate. Do not relate
anything to Ayin."""


class ExternalIngestionError(RuntimeError):
    """Raised when source identity or immutable provenance cannot be preserved."""


@dataclass(frozen=True, slots=True)
class ExternalImportResult:
    source_id: UUID
    source_version_id: UUID
    extraction_run_id: UUID
    source_created: bool
    source_version_created: bool
    segment_count: int
    window_count: int
    cache_hits: int
    cache_misses: int
    failed_windows: int
    mention_count: int
    claim_count: int
    people_count: int
    work_count: int
    organization_count: int
    concept_count: int
    review_count: int


class ExternalKnowledgeImporter:
    """Ingest one source snapshot and retry only failed extraction windows."""

    def __init__(
        self,
        database: Database,
        adapter: SourceAdapter,
        provider: LLMProvider,
        *,
        model: str = "configured-default",
        window_size: int = 50,
        overlap: int = 8,
        prompt_version: str = PROMPT_VERSION,
        timeout_seconds: int = 180,
        media_service: MediaService | None = None,
    ) -> None:
        if window_size <= 0 or overlap < 0 or overlap >= window_size:
            raise ValueError("invalid extraction window configuration")
        self._database = database
        self._adapter = adapter
        self._provider = provider
        self._model = model
        self._window_size = window_size
        self._overlap = overlap
        self._prompt_version = prompt_version
        self._timeout = timeout_seconds
        self._media = media_service
        self._log = get_logger(__name__)

    async def ingest(self, locator: str) -> ExternalImportResult:
        snapshot = await self._adapter.acquire(locator)
        content_hash, transcript_hash = _snapshot_hashes(snapshot)
        (
            source_id,
            version_id,
            run_id,
            source_created,
            version_created,
        ) = await self._persist_source(snapshot, content_hash, transcript_hash)
        window_ids = await self._ensure_windows(version_id, snapshot.language)
        cache_hits = 0
        cache_misses = 0
        failed = 0
        for window_id in window_ids:
            cached = await self._successful_result(run_id, window_id)
            if cached:
                cache_hits += 1
                self._log.info(
                    "knowledge_window_cache",
                    source_id=str(source_id),
                    source_version=str(version_id),
                    extraction_run=str(run_id),
                    window_id=str(window_id),
                    cache="hit",
                )
                continue
            cache_misses += 1
            if not await self._extract_window(version_id, run_id, window_id):
                failed += 1
        await self._finish_run(source_id, run_id, failed)
        if self._media is not None and snapshot.thumbnail_url is not None:
            await self._media.source_thumbnail(
                source_id,
                snapshot.thumbnail_url,
                attribution=snapshot.creator_name or snapshot.channel_title,
            )
        return await self._result(
            source_id,
            version_id,
            run_id,
            source_created=source_created,
            source_version_created=version_created,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            failed_windows=failed,
        )

    async def _persist_source(
        self, snapshot: ExternalSourceSnapshot, content_hash: str, transcript_hash: str
    ) -> tuple[UUID, UUID, UUID, bool, bool]:
        async with self._database.transaction() as session:
            repository = KnowledgeRepository(session)
            channel = await self._channel(session, repository, snapshot)
            source = await repository.source(snapshot.platform, snapshot.external_id)
            source_created = source is None
            if source is None:
                source = Source(
                    source_type=snapshot.source_type,
                    platform=snapshot.platform,
                    external_id=snapshot.external_id,
                    channel_id=channel.id if channel else None,
                    canonical_url=snapshot.canonical_url,
                    title=snapshot.title,
                    description=snapshot.description,
                    language=snapshot.language,
                    published_at=snapshot.published_at,
                    duration_seconds=snapshot.duration_seconds,
                    raw_metadata=snapshot.metadata,
                    ingestion_status=IngestionStatus.DISCOVERED,
                )
                session.add(source)
                await session.flush()
                session.add(
                    SourceQuality(
                        source_id=source.id,
                        publication_type="online_lecture",
                        peer_reviewed=None,
                        primary_or_secondary="secondary",
                        retraction_status=None,
                        review_notes=(
                            "YouTube source is useful for attribution and reference "
                            "discovery; it is not automatically scientific evidence."
                        ),
                        retrieval_weight=1.0,
                    )
                )
            version = await repository.source_version(source.id, content_hash)
            version_created = version is None
            if version is None:
                version = SourceVersion(
                    source_id=source.id,
                    content_hash=content_hash,
                    transcript_hash=transcript_hash,
                    corpus_zone=CorpusZone.EXTERNAL_PRIMARY,
                    provider_metadata={
                        "source": snapshot.metadata,
                        "transcript_kind": snapshot.transcript_kind,
                        "provider": snapshot.platform,
                    },
                    acquisition_tool="yt-dlp+youtube-transcript-api",
                    acquisition_version=INGESTER_VERSION,
                    normalization_version=NORMALIZATION_VERSION,
                    acquired_at=datetime.now(UTC),
                )
                session.add(version)
                await session.flush()
                session.add_all(
                    [
                        SourceSegment(
                            source_version_id=version.id,
                            sequence=entry.sequence,
                            start_seconds=Decimal(str(entry.start_seconds)),
                            end_seconds=Decimal(
                                str(entry.start_seconds + entry.duration_seconds)
                            ),
                            raw_text=entry.text,
                            normalized_text=normalize_external_text(entry.text),
                            language=snapshot.language,
                            content_hash=hashlib.sha256(
                                entry.text.encode()
                            ).hexdigest(),
                        )
                        for entry in snapshot.transcript
                    ]
                )
                source.ingestion_status = IngestionStatus.INGESTED
            configuration: dict[str, object] = {
                "window_size": self._window_size,
                "overlap": self._overlap,
                "schema": "WindowExtraction-v1",
            }
            config_hash = configuration_hash(configuration)
            run = await repository.run(
                version.id,
                task=TASK,
                provider=self._provider.name,
                model=self._model,
                prompt_version=self._prompt_version,
                configuration_hash=config_hash,
            )
            if run is None:
                run = ExtractionRun(
                    source_version_id=version.id,
                    task=TASK,
                    provider=self._provider.name,
                    model=self._model,
                    prompt_version=self._prompt_version,
                    configuration=configuration,
                    configuration_hash=config_hash,
                    window_size=self._window_size,
                    overlap=self._overlap,
                    status=RunStatus.PENDING,
                )
                session.add(run)
                await session.flush()
            return source.id, version.id, run.id, source_created, version_created

    async def _channel(
        self,
        session: AsyncSession,
        repository: KnowledgeRepository,
        snapshot: ExternalSourceSnapshot,
    ) -> Channel | None:
        if snapshot.channel_external_id is None:
            return None
        channel = await repository.channel(
            snapshot.platform, snapshot.channel_external_id
        )
        if channel is None:
            channel = Channel(
                platform=snapshot.platform,
                external_id=snapshot.channel_external_id,
                title=snapshot.channel_title or snapshot.channel_external_id,
                canonical_url=snapshot.channel_url or snapshot.canonical_url,
                metadata_json={},
            )
            session.add(channel)
            await session.flush()
        if snapshot.creator_name:
            creator = await repository.creator(snapshot.creator_name)
            if creator is None:
                creator = Creator(
                    canonical_name=snapshot.creator_name,
                    metadata_json={},
                    status="unreviewed",
                )
                session.add(creator)
                await session.flush()
            existing = await session.get(ChannelCreator, (channel.id, creator.id))
            if existing is None:
                session.add(
                    ChannelCreator(channel_id=channel.id, creator_id=creator.id)
                )
        return channel

    async def _ensure_windows(
        self, source_version_id: UUID, language: str
    ) -> list[UUID]:
        async with self._database.transaction() as session:
            segments = list(
                await session.scalars(
                    select(SourceSegment)
                    .where(SourceSegment.source_version_id == source_version_id)
                    .order_by(SourceSegment.sequence)
                )
            )
            built = build_windows(
                [
                    WindowSegment(
                        id=item.id,
                        sequence=item.sequence,
                        start_seconds=item.start_seconds,
                        end_seconds=item.end_seconds,
                        normalized_text=item.normalized_text,
                    )
                    for item in segments
                ],
                window_size=self._window_size,
                overlap=self._overlap,
            )
            repository = KnowledgeRepository(session)
            ids: list[UUID] = []
            for item in built:
                window = await repository.window(
                    source_version_id,
                    item.sequence,
                    self._window_size,
                    self._overlap,
                )
                if window is None:
                    window = ExtractionWindow(
                        source_version_id=source_version_id,
                        sequence=item.sequence,
                        window_size=self._window_size,
                        overlap=self._overlap,
                        start_seconds=item.segments[0].start_seconds,
                        end_seconds=item.segments[-1].end_seconds,
                        language=language,
                        content_hash=item.content_hash,
                        text=item.text,
                    )
                    session.add(window)
                    await session.flush()
                    session.add_all(
                        [
                            ExtractionWindowSegment(
                                window_id=window.id,
                                source_segment_id=segment.id,
                                source_version_id=source_version_id,
                                sequence_in_window=index,
                            )
                            for index, segment in enumerate(item.segments, start=1)
                        ]
                    )
                elif window.content_hash != item.content_hash:
                    raise ExternalIngestionError(
                        "identical window identity produced different content"
                    )
                ids.append(window.id)
            return ids

    async def _successful_result(self, run_id: UUID, window_id: UUID) -> bool:
        async with self._database.transaction() as session:
            result = await KnowledgeRepository(session).result(run_id, window_id)
            return result is not None and result.status is WindowStatus.SUCCEEDED

    async def _extract_window(
        self, source_version_id: UUID, run_id: UUID, window_id: UUID
    ) -> bool:
        async with self._database.transaction() as session:
            window = await session.get(ExtractionWindow, window_id)
            if window is None:
                raise ExternalIngestionError("extraction window disappeared")
            request = StructuredExtractionRequest(
                task=TASK,
                prompt_version=self._prompt_version,
                model=self._model,
                instructions=EXTRACTION_INSTRUCTIONS,
                input_text=window.text,
                output_model=WindowExtraction,
                timeout_seconds=self._timeout,
            )
            window_sequence = window.sequence
        started = time.monotonic()
        try:
            output = await self._provider.extract(request)
            parsed = WindowExtraction.model_validate(output.model_dump())
            await self._record_success(
                source_version_id,
                run_id,
                window_id,
                parsed,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception as exc:
            await self._record_failure(
                source_version_id,
                run_id,
                window_id,
                error_code=type(exc).__name__,
                diagnostics=str(exc)[-2000:],
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
            self._log.error(
                "knowledge_window_failed",
                source_version=str(source_version_id),
                extraction_run=str(run_id),
                window_number=window_sequence,
                cache="miss",
                error_code=type(exc).__name__,
            )
            return False
        self._log.info(
            "knowledge_window_succeeded",
            source_version=str(source_version_id),
            extraction_run=str(run_id),
            window_number=window_sequence,
            cache="miss",
        )
        return True

    async def _record_failure(
        self,
        source_version_id: UUID,
        run_id: UUID,
        window_id: UUID,
        *,
        error_code: str,
        diagnostics: str,
        elapsed_ms: int,
    ) -> None:
        async with self._database.transaction() as session:
            repository = KnowledgeRepository(session)
            result = await repository.result(run_id, window_id)
            if result is None:
                result = WindowResult(
                    extraction_run_id=run_id,
                    window_id=window_id,
                    status=WindowStatus.FAILED,
                    attempt_count=1,
                )
                session.add(result)
                await session.flush()
            else:
                result.attempt_count += 1
            result.status = WindowStatus.FAILED
            result.error_code = error_code
            result.diagnostics = diagnostics
            result.elapsed_ms = elapsed_ms
            result.updated_at = utc_now()
            existing_flag = await session.scalar(
                select(ReviewFlag.id).where(
                    ReviewFlag.window_result_id == result.id,
                    ReviewFlag.reason == ReviewReason.EXTRACTION_ANOMALY,
                    ReviewFlag.status == KnowledgeReviewStatus.OPEN,
                )
            )
            if existing_flag is None:
                session.add(
                    ReviewFlag(
                        source_version_id=source_version_id,
                        window_result_id=result.id,
                        reason=ReviewReason.EXTRACTION_ANOMALY,
                        status=KnowledgeReviewStatus.OPEN,
                        message=f"Window extraction failed: {error_code}",
                    )
                )

    async def _record_success(
        self,
        source_version_id: UUID,
        run_id: UUID,
        window_id: UUID,
        output: WindowExtraction,
        *,
        elapsed_ms: int,
    ) -> None:
        payload = output.model_dump(mode="json")
        output_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        async with self._database.transaction() as session:
            repository = KnowledgeRepository(session)
            result = await repository.result(run_id, window_id)
            if result is None:
                result = WindowResult(
                    extraction_run_id=run_id,
                    window_id=window_id,
                    status=WindowStatus.SUCCEEDED,
                    attempt_count=1,
                )
                session.add(result)
            else:
                result.attempt_count += 1
            result.status = WindowStatus.SUCCEEDED
            result.structured_output = payload
            result.output_hash = output_hash
            result.error_code = None
            result.diagnostics = None
            result.elapsed_ms = elapsed_ms
            result.updated_at = utc_now()
            await session.flush()
            recovered_flag = await session.scalar(
                select(ReviewFlag).where(
                    ReviewFlag.window_result_id == result.id,
                    ReviewFlag.reason == ReviewReason.EXTRACTION_ANOMALY,
                    ReviewFlag.status == KnowledgeReviewStatus.OPEN,
                )
            )
            if recovered_flag is not None:
                recovered_flag.status = KnowledgeReviewStatus.RESOLVED
                recovered_flag.reviewer_notes = "Succeeded on a later automatic retry."
                recovered_flag.reviewed_at = utc_now()
            await self._materialize(
                session, source_version_id, run_id, window_id, output
            )

    async def _materialize(
        self,
        session: AsyncSession,
        source_version_id: UUID,
        run_id: UUID,
        window_id: UUID,
        output: WindowExtraction,
    ) -> None:
        segment_rows = list(
            await session.scalars(
                select(SourceSegment)
                .join(
                    ExtractionWindowSegment,
                    ExtractionWindowSegment.source_segment_id == SourceSegment.id,
                )
                .where(
                    SourceSegment.source_version_id == source_version_id,
                    ExtractionWindowSegment.window_id == window_id,
                )
            )
        )
        segments = {item.sequence: item for item in segment_rows}
        for extracted in output.mentions:
            segment = segments.get(extracted.start_segment_sequence)
            if segment is None or extracted.end_segment_sequence not in segments:
                raise ExternalIngestionError(
                    "extraction cited a segment outside its source"
                )
            normalized = normalize_external_text(extracted.normalized_candidate)
            target = await self._entity(session, extracted.entity_type, normalized)
            existing = await session.scalar(
                select(Mention.id).where(
                    Mention.extraction_run_id == run_id,
                    Mention.source_segment_id == segment.id,
                    Mention.entity_type == extracted.entity_type,
                    Mention.surface_text == extracted.surface_text,
                )
            )
            if existing is not None:
                continue
            values: dict[str, object] = {
                "person_id": None,
                "work_id": None,
                "organization_id": None,
                "concept_id": None,
            }
            values[f"{extracted.entity_type.value}_id"] = target.id
            mention = Mention(
                source_version_id=source_version_id,
                source_segment_id=segment.id,
                extraction_run_id=run_id,
                entity_type=extracted.entity_type,
                surface_text=extracted.surface_text,
                context=extracted.context,
                confidence=extracted.confidence,
                resolution_status=ResolutionStatus.REVIEW,
                **values,
            )
            session.add(mention)
            await session.flush()
            reason = (
                ReviewReason.AMBIGUOUS_PERSON
                if extracted.entity_type is EntityType.PERSON
                else ReviewReason.AMBIGUOUS_WORK
                if extracted.entity_type is EntityType.WORK
                else ReviewReason.UNRESOLVED_REFERENCE
            )
            session.add(
                ReviewFlag(
                    source_version_id=source_version_id,
                    mention_id=mention.id,
                    reason=reason,
                    status=KnowledgeReviewStatus.OPEN,
                    message=(
                        "Machine-extracted external identity requires "
                        "resolution review."
                    ),
                )
            )
        for extracted_claim in output.claims:
            segment = segments.get(extracted_claim.source_segment_sequence)
            if segment is None:
                raise ExternalIngestionError("claim cited a segment outside its source")
            normalized = normalize_external_text(extracted_claim.claim_text)
            existing = await session.scalar(
                select(ExternalClaim.id).where(
                    ExternalClaim.extraction_run_id == run_id,
                    ExternalClaim.source_segment_id == segment.id,
                    ExternalClaim.normalized_claim_text == normalized,
                )
            )
            if existing is None:
                session.add(
                    ExternalClaim(
                        source_version_id=source_version_id,
                        source_segment_id=segment.id,
                        extraction_run_id=run_id,
                        claimant_person_id=None,
                        claim_text=extracted_claim.claim_text,
                        normalized_claim_text=normalized,
                        claim_domain=extracted_claim.claim_domain,
                        claim_type=extracted_claim.claim_type,
                        extraction_confidence=extracted_claim.confidence,
                        verification_status=VerificationStatus.ATTRIBUTED_ONLY,
                    )
                )

    async def _entity(
        self, session: AsyncSession, entity_type: EntityType, normalized: str
    ) -> Person | Work | Organization | ExternalConcept:
        if entity_type is EntityType.PERSON:
            entity = await session.scalar(
                select(Person).where(Person.normalized_name == normalized)
            )
            if entity is None:
                entity = Person(
                    canonical_name=normalized,
                    normalized_name=normalized,
                    metadata_json={"resolution": "machine_candidate"},
                )
                session.add(entity)
                await session.flush()
                session.add(
                    EntityLabel(
                        person_id=entity.id,
                        label=normalized,
                        normalized_label=normalized,
                        language="und",
                        kind=LabelKind.CANONICAL,
                    )
                )
            return entity
        if entity_type is EntityType.WORK:
            work = await session.scalar(
                select(Work).where(Work.normalized_title == normalized)
            )
            if work is None:
                work = Work(
                    work_type=WorkType.OTHER,
                    canonical_title=normalized,
                    normalized_title=normalized,
                    metadata_json={"resolution": "machine_candidate"},
                )
                session.add(work)
                await session.flush()
                session.add(
                    EntityLabel(
                        work_id=work.id,
                        label=normalized,
                        normalized_label=normalized,
                        language="und",
                        kind=LabelKind.CANONICAL,
                    )
                )
            return work
        if entity_type is EntityType.ORGANIZATION:
            organization = await session.scalar(
                select(Organization).where(Organization.normalized_name == normalized)
            )
            if organization is None:
                organization = Organization(
                    canonical_name=normalized,
                    normalized_name=normalized,
                    metadata_json={"resolution": "machine_candidate"},
                )
                session.add(organization)
                await session.flush()
                session.add(
                    EntityLabel(
                        organization_id=organization.id,
                        label=normalized,
                        normalized_label=normalized,
                        language="und",
                        kind=LabelKind.CANONICAL,
                    )
                )
            return organization
        concept = await session.scalar(
            select(ExternalConcept).where(ExternalConcept.normalized_name == normalized)
        )
        if concept is None:
            concept = ExternalConcept(
                canonical_name=normalized,
                normalized_name=normalized,
            )
            session.add(concept)
            await session.flush()
            session.add(
                EntityLabel(
                    concept_id=concept.id,
                    label=normalized,
                    normalized_label=normalized,
                    language="und",
                    kind=LabelKind.CANONICAL,
                )
            )
        return concept

    async def _finish_run(self, source_id: UUID, run_id: UUID, failures: int) -> None:
        async with self._database.transaction() as session:
            run = await session.get(ExtractionRun, run_id)
            source = await session.get(Source, source_id)
            if run is None or source is None:
                raise ExternalIngestionError("source or extraction run disappeared")
            run.status = RunStatus.PARTIAL if failures else RunStatus.SUCCEEDED
            run.completed_at = utc_now()
            source.ingestion_status = (
                IngestionStatus.PARTIAL if failures else IngestionStatus.INGESTED
            )

    async def _result(
        self,
        source_id: UUID,
        version_id: UUID,
        run_id: UUID,
        *,
        source_created: bool,
        source_version_created: bool,
        cache_hits: int,
        cache_misses: int,
        failed_windows: int,
    ) -> ExternalImportResult:
        async with self._database.transaction() as session:

            async def count(
                identifier: InstrumentedAttribute[object],
                *where: ColumnElement[bool],
            ) -> int:
                value = await session.scalar(
                    select(func.count(identifier)).where(*where)
                )
                return int(value or 0)

            return ExternalImportResult(
                source_id=source_id,
                source_version_id=version_id,
                extraction_run_id=run_id,
                source_created=source_created,
                source_version_created=source_version_created,
                segment_count=await count(
                    SourceSegment.id, SourceSegment.source_version_id == version_id
                ),
                window_count=await count(
                    ExtractionWindow.id,
                    ExtractionWindow.source_version_id == version_id,
                    ExtractionWindow.window_size == self._window_size,
                    ExtractionWindow.overlap == self._overlap,
                ),
                cache_hits=cache_hits,
                cache_misses=cache_misses,
                failed_windows=failed_windows,
                mention_count=await count(
                    Mention.id, Mention.extraction_run_id == run_id
                ),
                claim_count=await count(
                    ExternalClaim.id, ExternalClaim.extraction_run_id == run_id
                ),
                people_count=await count(Person.id),
                work_count=await count(Work.id),
                organization_count=await count(Organization.id),
                concept_count=await count(ExternalConcept.id),
                review_count=await count(
                    ReviewFlag.id, ReviewFlag.source_version_id == version_id
                ),
            )


def _snapshot_hashes(snapshot: ExternalSourceSnapshot) -> tuple[str, str]:
    transcript_payload = [
        {
            "sequence": item.sequence,
            "start": item.start_seconds,
            "duration": item.duration_seconds,
            "text": item.text,
        }
        for item in snapshot.transcript
    ]
    transcript_bytes = json.dumps(
        transcript_payload, ensure_ascii=False, separators=(",", ":")
    ).encode()
    transcript_hash = hashlib.sha256(transcript_bytes).hexdigest()
    content_payload = {
        "platform": snapshot.platform,
        "external_id": snapshot.external_id,
        "title": snapshot.title,
        "description": snapshot.description,
        "language": snapshot.language,
        "published_at": snapshot.published_at.isoformat()
        if snapshot.published_at
        else None,
        "duration_seconds": snapshot.duration_seconds,
        "channel_external_id": snapshot.channel_external_id,
        "transcript_hash": transcript_hash,
    }
    content_hash = hashlib.sha256(
        json.dumps(content_payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return content_hash, transcript_hash
