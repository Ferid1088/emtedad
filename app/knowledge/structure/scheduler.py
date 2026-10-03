"""Canonical post-ingestion scheduling (Phase 21 consolidation).

Ported from the retired ``app.speech_structure.scheduler``: a single
in-process scheduler queues sources after import and periodically rescans
for missing, failed, or stale processing. The authoritative state is now
``SourceProcessingState``; attempt counts and backoff are derived from its
``attempt_count`` plus ``ExtractionRun`` completion times, so restarts lose
nothing — an interrupted run leaves an orphaned ``STRUCTURING`` /
``UNIT_EXTRACTING`` state that the next scan re-enqueues.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.knowledge.domain import RunStatus
from app.knowledge.models import ExtractionRun, Source, SourceSegment, SourceVersion
from app.knowledge.processing import SourceProcessingService
from app.knowledge.structure.domain import SourceProcessingStatus
from app.knowledge.structure.models import SourceProcessingState

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)


class DisplayStatus(StrEnum):
    """User-facing lifecycle state of a source's processing state."""

    PENDING = "PENDING"  # queued or waiting for (re)processing
    RUNNING = "RUNNING"  # processing currently executing
    READY = "READY"  # canonical structure + units exist and are current
    STALE = "STALE"  # processing exists but the input changed
    FAILED = "FAILED"  # failed and automatic retries exhausted
    UNAVAILABLE = "UNAVAILABLE"  # no usable transcript
    REVIEW = "REVIEW"  # validation flagged the output; owner review needed


class FailureClass(StrEnum):
    QUOTA = "quota"  # provider quota/billing — retry later, unbounded
    RATE_LIMIT = "rate_limit"  # provider concurrency/throttling — retry later
    FAILED = "failed"  # real analysis failure — counted against max attempts


def classify_failure(error: str | None) -> FailureClass:
    """Bucket a persisted processing error into a retry class."""

    text = (error or "").lower()
    if "out_of_quota" in text or "kontingent" in text or "billing" in text:
        return FailureClass.QUOTA
    if "429" in text or "rate limit" in text or "parallele sessions" in text:
        return FailureClass.RATE_LIMIT
    return FailureClass.FAILED


@dataclass(frozen=True, slots=True)
class SourceStructureInfo:
    """Persisted facts about one source's processing state (pure data)."""

    source_id: UUID
    has_transcript: bool
    latest_source_version_id: UUID | None
    processing_status: str | None
    processed_source_version_id: UUID | None
    last_error: str | None
    failed_attempts: int
    last_failed_at: datetime | None


@dataclass(frozen=True, slots=True)
class SourceEvaluation:
    """Decision for one source: display status plus scheduling eligibility."""

    status: DisplayStatus
    eligible: bool
    reason: str


def evaluate_source(
    info: SourceStructureInfo,
    *,
    now: datetime,
    is_active: bool,
    is_queued: bool,
    max_attempts: int,
    retry_backoff_seconds: int,
    quota_backoff_seconds: int,
) -> SourceEvaluation:
    """Idempotent eligibility decision — pure, no side effects."""

    if not info.has_transcript:
        return SourceEvaluation(DisplayStatus.UNAVAILABLE, False, "no_transcript")
    if is_active:
        return SourceEvaluation(DisplayStatus.RUNNING, False, "in_flight")
    if is_queued:
        return SourceEvaluation(DisplayStatus.PENDING, False, "queued")
    if info.processing_status is None:
        return SourceEvaluation(DisplayStatus.PENDING, True, "missing")

    status = info.processing_status
    if status == SourceProcessingStatus.READY.value:
        current = (
            info.processed_source_version_id is not None
            and info.processed_source_version_id == info.latest_source_version_id
        )
        if current:
            return SourceEvaluation(DisplayStatus.READY, False, "ready")
        return SourceEvaluation(DisplayStatus.STALE, True, "stale_input")

    if status in {
        SourceProcessingStatus.STRUCTURE_REVIEW_REQUIRED.value,
        SourceProcessingStatus.UNIT_REVIEW_REQUIRED.value,
    }:
        return SourceEvaluation(DisplayStatus.REVIEW, False, "review_required")

    if status in {
        SourceProcessingStatus.INGESTED.value,
        SourceProcessingStatus.STRUCTURE_PENDING.value,
        SourceProcessingStatus.UNIT_EXTRACTION_PENDING.value,
        SourceProcessingStatus.STRUCTURED.value,
    }:
        return SourceEvaluation(DisplayStatus.PENDING, True, "pending")

    if status in {
        SourceProcessingStatus.STRUCTURING.value,
        SourceProcessingStatus.UNIT_EXTRACTING.value,
    }:
        # A committed in-progress state means a run was interrupted; the work
        # is not actually in flight, so reprocess.
        return SourceEvaluation(DisplayStatus.PENDING, True, "interrupted")

    # FAILED: decide between retry-pending and exhausted.
    failure = classify_failure(info.last_error)
    if failure in {FailureClass.QUOTA, FailureClass.RATE_LIMIT}:
        if info.last_failed_at is None:
            return SourceEvaluation(DisplayStatus.PENDING, True, failure.value)
        due = info.last_failed_at + timedelta(seconds=quota_backoff_seconds)
        if now >= due:
            return SourceEvaluation(DisplayStatus.PENDING, True, failure.value)
        return SourceEvaluation(DisplayStatus.PENDING, False, "backoff")
    if info.failed_attempts >= max_attempts:
        return SourceEvaluation(DisplayStatus.FAILED, False, "attempts_exhausted")
    if info.last_failed_at is None:
        return SourceEvaluation(DisplayStatus.PENDING, True, "retry")
    delay = retry_backoff_seconds * (2 ** max(info.failed_attempts - 1, 0))
    if now >= info.last_failed_at + timedelta(seconds=delay):
        return SourceEvaluation(DisplayStatus.PENDING, True, "retry")
    return SourceEvaluation(DisplayStatus.PENDING, False, "backoff")


async def collect_source_infos(session: AsyncSession) -> list[SourceStructureInfo]:
    """Load the persisted facts needed for eligibility and status display."""

    version_rows = (
        await session.execute(
            select(
                SourceVersion.source_id,
                SourceVersion.id,
                SourceVersion.created_at,
                func.count(SourceSegment.id),
            )
            .join(SourceSegment, SourceSegment.source_version_id == SourceVersion.id)
            .group_by(SourceVersion.source_id, SourceVersion.id)
        )
    ).all()
    # (version_id, created_at) — keep the newest version per source
    latest_version: dict[UUID, tuple[UUID, datetime]] = {}
    for source_id, version_id, created_at, _count in version_rows:
        existing = latest_version.get(source_id)
        if existing is None or created_at > existing[1]:
            latest_version[source_id] = (version_id, created_at)

    state_rows = (await session.execute(select(SourceProcessingState))).scalars().all()
    states = {item.source_id: item for item in state_rows}

    failed_rows = (
        await session.execute(
            select(
                ExtractionRun.source_version_id,
                func.max(ExtractionRun.completed_at),
            )
            .where(ExtractionRun.status == RunStatus.FAILED)
            .group_by(ExtractionRun.source_version_id)
        )
    ).all()
    last_failed_by_version = {
        version_id: completed_at for version_id, completed_at in failed_rows
    }

    source_ids = list(
        await session.scalars(select(Source.id).order_by(Source.created_at))
    )
    infos: list[SourceStructureInfo] = []
    for source_id in source_ids:
        version_entry = latest_version.get(source_id)
        state = states.get(source_id)
        latest_version_id = version_entry[0] if version_entry else None
        infos.append(
            SourceStructureInfo(
                source_id=source_id,
                has_transcript=version_entry is not None,
                latest_source_version_id=latest_version_id,
                processing_status=(state.status.value if state is not None else None),
                processed_source_version_id=(
                    state.source_version_id if state is not None else None
                ),
                last_error=state.last_error if state is not None else None,
                failed_attempts=(int(state.attempt_count) if state is not None else 0),
                last_failed_at=(
                    last_failed_by_version.get(latest_version_id)
                    if latest_version_id
                    else None
                ),
            )
        )
    return infos


class SourceProcessingScheduler:
    """Bounded in-process queue driving ``SourceProcessingService``."""

    def __init__(
        self,
        database: Database,
        *,
        concurrency: int = 2,
        max_attempts: int = 3,
        retry_backoff_seconds: int = 300,
        quota_backoff_seconds: int = 1800,
        service_factory: Callable[[Database], SourceProcessingService] = (
            SourceProcessingService
        ),
    ) -> None:
        self._database = database
        self._semaphore = asyncio.Semaphore(concurrency)
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.quota_backoff_seconds = quota_backoff_seconds
        self._service_factory = service_factory
        self._queued: set[UUID] = set()
        self._active: set[UUID] = set()
        self._phases: dict[UUID, str] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._stop = asyncio.Event()

    def enqueue(self, source_id: UUID, *, force: bool = False) -> bool:
        """Queue a source; returns False when already queued or running."""

        if source_id in self._queued or source_id in self._active:
            return False
        self._queued.add(source_id)
        task = asyncio.create_task(self._run(source_id, force=force))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(lambda done: self._log_task_failure(source_id, done))
        logger.info(
            "source_processing.queued",
            extra={"source_id": str(source_id), "force": force},
        )
        return True

    def is_queued(self, source_id: UUID) -> bool:
        return source_id in self._queued

    def is_running(self, source_id: UUID) -> bool:
        return source_id in self._active

    def phase_of(self, source_id: UUID) -> str | None:
        return self._phases.get(source_id)

    async def _run(self, source_id: UUID, *, force: bool) -> None:
        async with self._semaphore:
            self._queued.discard(source_id)
            self._active.add(source_id)
            self._phases[source_id] = "structure"
            started = asyncio.get_running_loop().time()
            try:
                service = self._service_factory(self._database)
                await service.process_source(
                    source_id,
                    force=force,
                    on_progress=lambda phase: self._phases.__setitem__(
                        source_id, phase
                    ),
                )
            finally:
                self._active.discard(source_id)
                self._phases.pop(source_id, None)
                logger.info(
                    "source_processing.run_finished",
                    extra={
                        "source_id": str(source_id),
                        "duration_s": round(
                            asyncio.get_running_loop().time() - started, 1
                        ),
                    },
                )

    def _log_task_failure(self, source_id: UUID, done: "asyncio.Task[None]") -> None:
        if done.cancelled():
            return
        exc = done.exception()
        if exc is not None:
            logger.error(
                "source_processing.background_failed",
                extra={"source_id": str(source_id)},
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    async def scan_once(self) -> dict[str, int]:
        """Evaluate every source once and enqueue the eligible ones."""

        async with self._database.transaction() as session:
            infos = await collect_source_infos(session)
        now = datetime.now(UTC)
        counts: dict[str, int] = {status.value: 0 for status in DisplayStatus}
        scheduled = 0
        for info in infos:
            evaluation = evaluate_source(
                info,
                now=now,
                is_active=self.is_running(info.source_id),
                is_queued=self.is_queued(info.source_id),
                max_attempts=self.max_attempts,
                retry_backoff_seconds=self.retry_backoff_seconds,
                quota_backoff_seconds=self.quota_backoff_seconds,
            )
            counts[evaluation.status.value] += 1
            if evaluation.eligible and self.enqueue(info.source_id):
                scheduled += 1
        counts["scheduled"] = scheduled
        logger.info("source_processing.scan", extra=counts)
        return counts

    async def retry_failed(self) -> int:
        """Manually re-enqueue every FAILED source, ignoring the retry cap."""

        async with self._database.transaction() as session:
            infos = await collect_source_infos(session)
        enqueued = 0
        for info in infos:
            if (
                info.processing_status == SourceProcessingStatus.FAILED.value
                and self.enqueue(info.source_id)
            ):
                enqueued += 1
        return enqueued

    async def run_forever(self, interval_seconds: int) -> None:
        """Periodic catch-up: scan immediately, then every interval."""

        while not self._stop.is_set():
            try:
                await self.scan_once()
            except Exception:
                logger.exception("source_processing.scan_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), interval_seconds)

    def stop(self) -> None:
        self._stop.set()


_scheduler: SourceProcessingScheduler | None = None


def init_scheduler(
    database: Database, settings: "Settings"
) -> SourceProcessingScheduler:
    """Bind the process-wide scheduler during app startup."""

    global _scheduler
    _scheduler = SourceProcessingScheduler(
        database,
        concurrency=settings.speech_structure_concurrency,
        max_attempts=settings.speech_structure_max_attempts,
        retry_backoff_seconds=settings.speech_structure_retry_backoff_seconds,
        quota_backoff_seconds=settings.speech_structure_quota_backoff_seconds,
    )
    return _scheduler


def get_scheduler(database: Database) -> SourceProcessingScheduler:
    """Return the process scheduler; create a default one outside the app."""

    global _scheduler
    if _scheduler is None:
        from app.core.config import get_settings

        _scheduler = init_scheduler(database, get_settings())
    return _scheduler


def schedule_structure_analysis(
    database: Database, source_id: UUID, *, force: bool = False
) -> bool:
    """Queue post-ingestion processing in the background after an import."""

    return get_scheduler(database).enqueue(source_id, force=force)


def summarize_states(
    infos: Sequence[SourceStructureInfo],
    scheduler: SourceProcessingScheduler,
    *,
    now: datetime,
) -> dict[UUID, SourceEvaluation]:
    """Evaluate all sources for UI display with scheduler state applied."""

    return {
        info.source_id: evaluate_source(
            info,
            now=now,
            is_active=scheduler.is_running(info.source_id),
            is_queued=scheduler.is_queued(info.source_id),
            max_attempts=scheduler.max_attempts,
            retry_backoff_seconds=scheduler.retry_backoff_seconds,
            quota_backoff_seconds=scheduler.quota_backoff_seconds,
        )
        for info in infos
    }
