"""Background channel import: queue, parallelism, recovery, readable errors."""

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.channel_monitoring.domain import CandidateStatus
from app.channel_monitoring.import_worker import ChannelImportWorker
from app.channel_monitoring.models import ChannelVideoCandidate
from app.channel_monitoring.service import ChannelDiscoveryService
from app.db.session import Database
from app.knowledge.adapters.base import ChannelSnapshot, ChannelVideoSnapshot
from app.knowledge.adapters.youtube import YouTubeTranscriptUnavailableError
from tests.integration.test_channel_discovery import FakeChannelAdapter

pytestmark = pytest.mark.integration


class _ManyVideos(FakeChannelAdapter):
    def __init__(self, count: int) -> None:
        self.ids = [f"V{i:010d}" for i in range(count)]
        self.channel_id = "UC" + uuid4().hex[:22]

    async def resolve_channel(self, _locator: str) -> ChannelSnapshot:
        return ChannelSnapshot(
            external_channel_id=self.channel_id,
            name="Import worker test",
            channel_url=f"https://www.youtube.com/channel/{self.channel_id}",
            handle=None,
        )

    async def list_channel_videos(
        self, _locator: str
    ) -> tuple[ChannelVideoSnapshot, ...]:
        return tuple(
            ChannelVideoSnapshot(
                youtube_video_id=video_id,
                title=video_id,
                published_at=datetime.now(UTC),
                thumbnail_url=None,
                duration_seconds=60,
            )
            for video_id in self.ids
        )


@dataclass
class _Imported:
    source_id: UUID


class _FakeImporter:
    def __init__(self, fail: set[str], database: Database) -> None:
        self.fail = fail
        self.database = database
        self.running = 0
        self.peak = 0

    async def ingest(self, video_id: str) -> _Imported:
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await asyncio.sleep(0.05)
            if video_id in self.fail:
                raise YouTubeTranscriptUnavailableError(
                    "no transcript in the channel language (fa); available: en",
                    available=("en",),
                )
            from app.knowledge.domain import IngestionStatus, SourceType
            from app.knowledge.models import Source

            async with self.database.transaction() as session:
                source = Source(
                    source_type=SourceType.YOUTUBE_VIDEO,
                    platform="youtube-test",
                    external_id=f"{video_id}-{uuid4().hex[:6]}",
                    canonical_url=f"https://www.youtube.com/watch?v={video_id}",
                    title=video_id,
                    language="fa",
                    raw_metadata={},
                    ingestion_status=IngestionStatus.INGESTED,
                )
                session.add(source)
                await session.flush()
                return _Imported(source.id)
        finally:
            self.running -= 1


@pytest.fixture
def database(migrated_database_url: str) -> Database:
    """A disposable database — this suite writes channels, candidates and
    sources, and must never do that to the owner's corpus."""

    return Database(migrated_database_url)


@pytest.mark.asyncio
async def test_selected_videos_import_in_parallel_with_readable_errors(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _ManyVideos(8)
    service = ChannelDiscoveryService(database, adapter=adapter)  # type: ignore[arg-type]
    channel = await service.register("https://www.youtube.com/@many")
    importer = _FakeImporter(fail={adapter.ids[0]}, database=database)
    scheduled: list[UUID] = []
    monkeypatch.setattr(
        ChannelDiscoveryService, "importer", property(lambda self: importer)
    )
    monkeypatch.setattr(
        "app.knowledge.structure.scheduler.schedule_structure_analysis",
        lambda _db, source_id: scheduled.append(source_id),
    )
    try:
        candidates = await service.discover(channel.id)
        queued = await service.import_selected(channel.id, [c.id for c in candidates])
        assert queued == 8
        worker = ChannelImportWorker(database, concurrency=4)
        assert await worker.run_once() >= 8  # plus leftovers from other tests
        assert importer.peak == 4  # really parallel, but bounded
        async with database.transaction() as session:
            rows = list(
                await session.scalars(
                    select(ChannelVideoCandidate).where(
                        ChannelVideoCandidate.channel_id == channel.id
                    )
                )
            )
        by_status = {r.youtube_video_id: r for r in rows}
        failed = by_status[adapter.ids[0]]
        assert failed.status is CandidateStatus.FAILED
        assert failed.last_error is not None
        assert "Kein persisches Transkript" in failed.last_error
        assert sum(r.status is CandidateStatus.IMPORTED for r in rows) == 7
        assert len(scheduled) == 7  # every import is handed to processing

        # Failed ones can be queued again in one go.
        assert await service.retry_failed(channel.id) == 1
    finally:
        await service.delete_channel(channel.id)
        await database.dispose()


@pytest.mark.asyncio
async def test_interrupted_imports_are_requeued_after_restart(
    database: Database,
) -> None:
    adapter = _ManyVideos(2)
    service = ChannelDiscoveryService(database, adapter=adapter)  # type: ignore[arg-type]
    channel = await service.register("https://www.youtube.com/@restart")
    try:
        candidates = await service.discover(channel.id)
        async with database.transaction() as session:
            for candidate in candidates:
                row = await session.get(ChannelVideoCandidate, candidate.id)
                assert row is not None
                row.status = CandidateStatus.IMPORTING  # app died mid-import
        worker = ChannelImportWorker(database, concurrency=2)
        assert await worker.recover_interrupted() >= 2
        async with database.transaction() as session:
            statuses = {
                row.status
                for row in await session.scalars(
                    select(ChannelVideoCandidate).where(
                        ChannelVideoCandidate.channel_id == channel.id
                    )
                )
            }
        assert statuses == {CandidateStatus.SELECTED}
    finally:
        await service.delete_channel(channel.id)
        await database.dispose()


def test_writing_suites_never_use_the_owner_database(
    migrated_database_url: str,
) -> None:
    """Regression: this suite used to write into ``EMTEDAD_DATABASE_URL``.

    Every run left a monitored channel, eight candidates and seven
    ``V0000000000`` sources in the owner's corpus — visible in the Studio
    library and eligible for topic mining. Tests that write take a
    disposable database (tests/integration/conftest.py).
    """

    from sqlalchemy.engine import make_url

    configured = os.environ.get("EMTEDAD_DATABASE_URL") or ""
    assert configured, "EMTEDAD_DATABASE_URL is required"
    disposable = make_url(migrated_database_url).database or ""
    assert disposable.startswith("emtedad_test_")
    assert disposable != make_url(configured).database
