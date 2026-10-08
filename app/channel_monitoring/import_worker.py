"""Background import of selected channel videos.

Selecting videos only marks them SELECTED; this worker downloads metadata
and transcripts in parallel (``youtube_import_concurrency``) and hands each
imported source to the processing scheduler. The queue lives in the
database, so closing the browser or restarting the app loses nothing:
on start, videos left in IMPORTING by an interrupted run go back to
SELECTED and are imported again.
"""

import asyncio
import contextlib
import logging
from uuid import UUID

from sqlalchemy import select, update

from app.channel_monitoring.domain import CandidateStatus
from app.channel_monitoring.models import ChannelVideoCandidate
from app.db.session import Database
from app.knowledge.adapters.youtube import (
    YouTubeRateLimitedError,
    YouTubeTranscriptUnavailableError,
    YouTubeVideoInaccessibleError,
)

logger = logging.getLogger(__name__)

_RATE_LIMIT_PAUSE_SECONDS = 600


def import_error_message(exc: BaseException) -> str:
    """Owner-readable reason, stored on the candidate."""

    if isinstance(exc, YouTubeTranscriptUnavailableError):
        if exc.available:
            return "Kein persisches Transkript — vorhanden nur: " + ", ".join(
                exc.available
            )
        return "Video hat kein abrufbares Transkript."
    if isinstance(exc, YouTubeRateLimitedError):
        return "YouTube drosselt diese IP vorübergehend — wird später wiederholt."
    if isinstance(exc, YouTubeVideoInaccessibleError):
        return (
            "Video ist nicht abrufbar (nur für Mitglieder, privat, "
            "altersbeschränkt oder entfernt) — ein erneuter Versuch hilft nicht."
        )
    # Unknown causes stay retryable, but the owner needs the reason to judge
    # that — hiding it behind the class name alone says nothing.
    return f"Import fehlgeschlagen ({type(exc).__name__}): {exc} — erneut versuchbar."


class ChannelImportWorker:
    def __init__(self, database: Database, *, concurrency: int = 4) -> None:
        self.database = database
        self.concurrency = max(1, concurrency)
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._active: set[UUID] = set()
        self._paused_until = 0.0

    @property
    def active_count(self) -> int:
        return len(self._active)

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    async def recover_interrupted(self) -> int:
        """IMPORTING rows have no live worker after a restart — requeue."""

        async with self.database.transaction() as session:
            result = await session.execute(
                update(ChannelVideoCandidate)
                .where(ChannelVideoCandidate.status == CandidateStatus.IMPORTING)
                .values(status=CandidateStatus.SELECTED)
            )
        return int(getattr(result, "rowcount", 0) or 0)

    async def _claim(self, limit: int) -> list[tuple[UUID, str]]:
        async with self.database.transaction() as session:
            rows = list(
                await session.scalars(
                    select(ChannelVideoCandidate)
                    .where(ChannelVideoCandidate.status == CandidateStatus.SELECTED)
                    .order_by(ChannelVideoCandidate.published_at.desc().nulls_last())
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            for row in rows:
                row.status = CandidateStatus.IMPORTING
            return [(row.id, row.youtube_video_id) for row in rows]

    async def _import_one(self, candidate_id: UUID, video_id: str) -> None:
        from app.channel_monitoring.service import ChannelDiscoveryService
        from app.knowledge.structure.scheduler import schedule_structure_analysis

        self._active.add(candidate_id)
        try:
            service = ChannelDiscoveryService(self.database)
            imported = await service.importer.ingest(video_id)
        except Exception as exc:  # noqa: BLE001 — recorded per video
            rate_limited = isinstance(exc, YouTubeRateLimitedError)
            if rate_limited:
                self._paused_until = (
                    asyncio.get_running_loop().time() + _RATE_LIMIT_PAUSE_SECONDS
                )
            async with self.database.transaction() as session:
                row = await session.get(ChannelVideoCandidate, candidate_id)
                if row is not None:
                    # Throttling is temporary: keep it queued, not failed.
                    row.status = (
                        CandidateStatus.SELECTED
                        if rate_limited
                        else CandidateStatus.FAILED
                    )
                    row.last_error = import_error_message(exc)
            logger.info("channel import failed for %s: %s", video_id, exc)
        else:
            async with self.database.transaction() as session:
                row = await session.get(ChannelVideoCandidate, candidate_id)
                if row is not None:
                    row.status = CandidateStatus.IMPORTED
                    row.imported_source_id = imported.source_id
                    row.last_error = None
            schedule_structure_analysis(self.database, imported.source_id)
        finally:
            self._active.discard(candidate_id)

    async def run_once(self) -> int:
        """Import everything currently SELECTED, ``concurrency`` at a time."""

        done = 0
        semaphore = asyncio.Semaphore(self.concurrency)

        async def guarded(candidate_id: UUID, video_id: str) -> None:
            async with semaphore:
                await self._import_one(candidate_id, video_id)

        while not self._stop.is_set():
            if asyncio.get_running_loop().time() < self._paused_until:
                break
            batch = await self._claim(self.concurrency * 2)
            if not batch:
                break
            await asyncio.gather(*(guarded(cid, vid) for cid, vid in batch))
            done += len(batch)
        return done

    async def run_forever(self, interval_seconds: int = 60) -> None:
        with contextlib.suppress(Exception):
            recovered = await self.recover_interrupted()
            if recovered:
                logger.info("requeued %s interrupted video imports", recovered)
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001 — keep the worker alive
                logger.exception("channel import worker iteration failed")
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), interval_seconds)


_worker: ChannelImportWorker | None = None


def init_import_worker(database: Database, concurrency: int) -> ChannelImportWorker:
    global _worker
    _worker = ChannelImportWorker(database, concurrency=concurrency)
    return _worker


def get_import_worker() -> ChannelImportWorker | None:
    return _worker
