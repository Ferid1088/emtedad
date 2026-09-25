"""Deterministic channel discovery and explicitly approved batch import."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select

from app.channel_monitoring.domain import CandidateStatus
from app.channel_monitoring.models import ChannelVideoCandidate, MonitoredChannel
from app.db.session import Database
from app.knowledge.adapters.youtube import YouTubeAdapter
from app.knowledge.importer import ExternalKnowledgeImporter
from app.knowledge.llm.codex import CodexCliProvider
from app.knowledge.models import Source
from app.retrieval.embeddings import EmbeddingProvider
from app.semantic_content.ingestion import SemanticKnowledgePipeline


@dataclass(frozen=True, slots=True)
class CandidateImportResult:
    candidate_id: UUID
    video_id: str
    success: bool
    message: str


class ChannelDiscoveryService:
    """Register, inspect, and import channel candidates with owner approval."""

    def __init__(
        self,
        database: Database,
        *,
        adapter: YouTubeAdapter | None = None,
        importer: ExternalKnowledgeImporter | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        pipeline: SemanticKnowledgePipeline | None = None,
    ) -> None:
        self.database = database
        self.adapter = adapter or YouTubeAdapter()
        self.importer = importer or ExternalKnowledgeImporter(
            database, self.adapter, CodexCliProvider()
        )
        self.pipeline = pipeline
        if self.pipeline is None and embedding_provider is not None:
            self.pipeline = SemanticKnowledgePipeline(
                database,
                self.adapter,
                CodexCliProvider(),
                embedding_provider,
            )

    async def register(self, locator: str) -> MonitoredChannel:
        snapshot = await self.adapter.resolve_channel(locator)
        async with self.database.transaction() as session:
            existing = await session.scalar(
                select(MonitoredChannel).where(
                    MonitoredChannel.platform == "YOUTUBE",
                    MonitoredChannel.external_channel_id
                    == snapshot.external_channel_id,
                )
            )
            if existing is not None:
                return existing
            channel = MonitoredChannel(
                platform="YOUTUBE",
                external_channel_id=snapshot.external_channel_id,
                name=snapshot.name,
                channel_url=snapshot.channel_url,
                handle=snapshot.handle,
            )
            session.add(channel)
            await session.flush()
            return channel

    async def discover(self, channel_id: UUID) -> list[ChannelVideoCandidate]:
        async with self.database.transaction() as session:
            channel = await session.get(MonitoredChannel, channel_id)
            if channel is None:
                raise ValueError("channel not found")
            channel_url = channel.channel_url
        discovered = await self.adapter.list_channel_videos(channel_url)
        now = datetime.now(UTC)
        async with self.database.transaction() as session:
            channel = await session.get(MonitoredChannel, channel_id)
            if channel is None:
                raise ValueError("channel not found")
            existing_video_ids = set(
                await session.scalars(
                    select(Source.external_id).where(Source.platform == "youtube")
                )
            )
            for item in discovered:
                candidate = await session.scalar(
                    select(ChannelVideoCandidate).where(
                        ChannelVideoCandidate.channel_id == channel_id,
                        ChannelVideoCandidate.youtube_video_id == item.youtube_video_id,
                    )
                )
                if item.youtube_video_id in existing_video_ids:
                    if candidate is not None:
                        candidate.status = CandidateStatus.IMPORTED
                    continue
                if candidate is None:
                    session.add(
                        ChannelVideoCandidate(
                            channel_id=channel_id,
                            youtube_video_id=item.youtube_video_id,
                            title=item.title,
                            published_at=item.published_at,
                            thumbnail_url=item.thumbnail_url,
                            duration_seconds=item.duration_seconds,
                            discovered_at=now,
                            status=CandidateStatus.NEW,
                        )
                    )
                elif candidate.status not in {
                    CandidateStatus.IGNORED,
                    CandidateStatus.IMPORTED,
                }:
                    candidate.title = item.title
                    candidate.published_at = item.published_at
                    candidate.thumbnail_url = item.thumbnail_url
                    candidate.duration_seconds = item.duration_seconds
                    candidate.status = CandidateStatus.NEW
            channel.last_checked_at = now
            channel.last_successful_check_at = now
            await session.flush()
            return list(
                await session.scalars(
                    select(ChannelVideoCandidate)
                    .where(
                        ChannelVideoCandidate.channel_id == channel_id,
                        ChannelVideoCandidate.status == CandidateStatus.NEW,
                    )
                    .order_by(ChannelVideoCandidate.published_at.desc())
                )
            )

    async def candidates(
        self, channel_id: UUID, statuses: set[CandidateStatus] | None = None
    ) -> list[ChannelVideoCandidate]:
        async with self.database.transaction() as session:
            statement = select(ChannelVideoCandidate).where(
                ChannelVideoCandidate.channel_id == channel_id
            )
            if statuses:
                statement = statement.where(ChannelVideoCandidate.status.in_(statuses))
            return list(
                await session.scalars(
                    statement.order_by(ChannelVideoCandidate.discovered_at.desc())
                )
            )

    async def import_selected(
        self, channel_id: UUID, candidate_ids: list[UUID]
    ) -> list[CandidateImportResult]:
        async with self.database.transaction() as session:
            candidates = list(
                await session.scalars(
                    select(ChannelVideoCandidate).where(
                        ChannelVideoCandidate.channel_id == channel_id,
                        ChannelVideoCandidate.id.in_(candidate_ids),
                        ChannelVideoCandidate.status.in_(
                            [CandidateStatus.NEW, CandidateStatus.FAILED]
                        ),
                    )
                )
            )
            for candidate in candidates:
                candidate.status = CandidateStatus.IMPORTING
            await session.flush()
            work = [
                (candidate.id, candidate.youtube_video_id) for candidate in candidates
            ]

        if self.pipeline is None:
            return await self._import_without_semantic_pipeline(work)

        # Semantic extraction is source-specific, but chunk/embedding refresh is global.
        # Batch imports therefore refresh the retrieval index only once.
        prepared: list[tuple[UUID, str, UUID]] = []
        results: dict[UUID, CandidateImportResult] = {}
        for candidate_id, video_id in work:
            try:
                source = await self.pipeline.ingest_source(video_id)
            except Exception as exc:
                async with self.database.transaction() as session:
                    updated = await session.get(ChannelVideoCandidate, candidate_id)
                    if updated is not None:
                        updated.status = CandidateStatus.FAILED
                        updated.last_error = type(exc).__name__
                results[candidate_id] = CandidateImportResult(
                    candidate_id,
                    video_id,
                    False,
                    "Import fehlgeschlagen; der Versuch kann wiederholt werden.",
                )
            else:
                prepared.append((candidate_id, video_id, source.source_id))

        if prepared:
            try:
                await self.pipeline.refresh_index()
            except Exception as exc:
                async with self.database.transaction() as session:
                    for candidate_id, _video_id, source_id in prepared:
                        updated = await session.get(
                            ChannelVideoCandidate, candidate_id
                        )
                        if updated is not None:
                            updated.status = CandidateStatus.FAILED
                            updated.imported_source_id = source_id
                            updated.last_error = f"index:{type(exc).__name__}"
                for candidate_id, video_id, _source_id in prepared:
                    results[candidate_id] = CandidateImportResult(
                        candidate_id,
                        video_id,
                        False,
                        "Quelle gespeichert; Wissensindex konnte nicht " \
                        "erneuert werden.",
                    )
            else:
                async with self.database.transaction() as session:
                    for candidate_id, _video_id, source_id in prepared:
                        updated = await session.get(
                            ChannelVideoCandidate, candidate_id
                        )
                        if updated is not None:
                            updated.status = CandidateStatus.IMPORTED
                            updated.imported_source_id = source_id
                            updated.last_error = None
                for candidate_id, video_id, _source_id in prepared:
                    results[candidate_id] = CandidateImportResult(
                        candidate_id, video_id, True, "importiert"
                    )

        return [
            results[candidate_id]
            for candidate_id, _video_id in work
            if candidate_id in results
        ]

    async def _import_without_semantic_pipeline(
        self, work: list[tuple[UUID, str]]
    ) -> list[CandidateImportResult]:
        """Compatibility path for tests and callers that do not provide embeddings."""

        results: list[CandidateImportResult] = []
        for candidate_id, video_id in work:
            try:
                imported = await self.importer.ingest(video_id)
            except Exception as exc:
                async with self.database.transaction() as session:
                    updated = await session.get(ChannelVideoCandidate, candidate_id)
                    if updated is not None:
                        updated.status = CandidateStatus.FAILED
                        updated.last_error = type(exc).__name__
                results.append(
                    CandidateImportResult(
                        candidate_id,
                        video_id,
                        False,
                        "Import fehlgeschlagen; der Versuch kann wiederholt werden.",
                    )
                )
            else:
                async with self.database.transaction() as session:
                    updated = await session.get(ChannelVideoCandidate, candidate_id)
                    if updated is not None:
                        updated.status = CandidateStatus.IMPORTED
                        updated.imported_source_id = imported.source_id
                        updated.last_error = None
                results.append(
                    CandidateImportResult(candidate_id, video_id, True, "importiert")
                )
        return results

    async def ignore(self, channel_id: UUID, candidate_id: UUID) -> bool:
        async with self.database.transaction() as session:
            candidate = await session.scalar(
                select(ChannelVideoCandidate).where(
                    ChannelVideoCandidate.id == candidate_id,
                    ChannelVideoCandidate.channel_id == channel_id,
                    ChannelVideoCandidate.status == CandidateStatus.NEW,
                )
            )
            if candidate is None:
                return False
            candidate.status = CandidateStatus.IGNORED
            return True

    async def delete_channel(self, channel_id: UUID) -> bool:
        """Remove monitoring metadata while leaving knowledge sources untouched."""

        async with self.database.transaction() as session:
            channel = await session.get(MonitoredChannel, channel_id)
            if channel is None:
                return False
            await session.delete(channel)
            await session.flush()
            return True

    async def active_channels(self) -> list[MonitoredChannel]:
        async with self.database.transaction() as session:
            return list(
                await session.scalars(
                    select(MonitoredChannel)
                    .where(MonitoredChannel.active.is_(True))
                    .order_by(MonitoredChannel.name)
                )
            )

    async def pending_count(self) -> int:
        async with self.database.transaction() as session:
            return int(
                await session.scalar(
                    select(func.count(ChannelVideoCandidate.id)).where(
                        ChannelVideoCandidate.status == CandidateStatus.NEW
                    )
                )
                or 0
            )
