"""Automatic speech-structure scheduling, eligibility, and status derivation.

A single in-process scheduler queues sources after import and periodically
rescans for missing, failed, or stale structures. Attempt counts and backoff
are derived from persisted ``speech_structure_runs`` rows, so restarts lose
nothing: an interrupted run rolls back its transaction and the next scan sees
the source as missing again.
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
from app.knowledge.models import Source, SourceSegment, SourceVersion
from app.speech_structure.domain import (
    GLOBAL_PROMPT_VERSION,
    LOCAL_PROMPT_VERSION,
    StructureStatus,
)
from app.speech_structure.models import SpeechStructure, SpeechStructureRun
from app.speech_structure.service import SpeechStructureService

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)

CURRENT_PROMPT_VERSION = f"{LOCAL_PROMPT_VERSION}+{GLOBAL_PROMPT_VERSION}"


class DisplayStatus(StrEnum):
    """User-facing lifecycle state of a source's speech structure."""

    PENDING = "PENDING"  # queued or waiting for (re)processing
    RUNNING = "RUNNING"  # analysis currently executing
    READY = "READY"  # a current, valid structure exists
    STALE = "STALE"  # a structure exists but the input changed
    FAILED = "FAILED"  # failed and automatic retries exhausted
    UNAVAILABLE = "UNAVAILABLE"  # no usable transcript


class FailureClass(StrEnum):
    QUOTA = "quota"  # provider quota/billing — retry later, unbounded
    RATE_LIMIT = "rate_limit"  # provider concurrency/throttling — retry later
    FAILED = "failed"  # real analysis failure — counted against max attempts


def classify_failure(error: str | None) -> FailureClass:
    """Bucket a persisted run error into a retry class."""

    text = (error or "").lower()
    if "out_of_quota" in text or "kontingent" in text or "billing" in text:
        return FailureClass.QUOTA
    if "429" in text or "rate limit" in text or "parallele sessions" in text:
        return FailureClass.RATE_LIMIT
    return FailureClass.FAILED


@dataclass(frozen=True, slots=True)
class SourceStructureInfo:
    """Persisted facts about one source's structure state (pure data)."""

    source_id: UUID
    has_transcript: bool
    latest_source_version_id: UUID | None
    structure_status: str | None
    structure_source_version_id: UUID | None
    structure_completed_at: datetime | None
    run_prompt_version: str | None
    run_error: str | None
    run_started_at: datetime | None
    run_completed_at: datetime | None
    failed_attempts: int


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
    if info.structure_status is None:
        return SourceEvaluation(DisplayStatus.PENDING, True, "missing")

    current = (
        info.structure_source_version_id is not None
        and info.structure_source_version_id == info.latest_source_version_id
        and info.run_prompt_version == CURRENT_PROMPT_VERSION
    )
    if info.structure_status in {
        StructureStatus.READY.value,
        StructureStatus.REVIEW.value,
    }:
        if current:
            return SourceEvaluation(DisplayStatus.READY, False, "ready")
        return SourceEvaluation(DisplayStatus.STALE, True, "stale_input")

    if info.structure_status == StructureStatus.PROCESSING.value:
        # A committed PROCESSING row means a run was interrupted mid-commit or
        # left orphaned; the work is not actually in flight, so reprocess.
        return SourceEvaluation(DisplayStatus.PENDING, True, "interrupted")

    # DRAFT or FAILED: decide between retry-pending and exhausted.
    failure = classify_failure(info.run_error)
    if failure in {FailureClass.QUOTA, FailureClass.RATE_LIMIT}:
        if info.run_completed_at is None:
            return SourceEvaluation(DisplayStatus.PENDING, True, failure.value)
        due = info.run_completed_at + timedelta(seconds=quota_backoff_seconds)
        if now >= due:
            return SourceEvaluation(DisplayStatus.PENDING, True, failure.value)
        return SourceEvaluation(DisplayStatus.PENDING, False, "backoff")
    if info.failed_attempts >= max_attempts:
        return SourceEvaluation(DisplayStatus.FAILED, False, "attempts_exhausted")
    if info.run_completed_at is None:
        return SourceEvaluation(DisplayStatus.PENDING, True, "retry")
    delay = retry_backoff_seconds * (2 ** max(info.failed_attempts - 1, 0))
    if now >= info.run_completed_at + timedelta(seconds=delay):
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

    structure_rows = (
        await session.execute(
            select(SpeechStructure)
            .distinct(SpeechStructure.source_id)
            .order_by(
                SpeechStructure.source_id, SpeechStructure.version.desc()
            )
        )
    ).scalars().all()
    structures = {item.source_id: item for item in structure_rows}

    run_rows = (
        await session.execute(
            select(SpeechStructureRun)
            .distinct(SpeechStructureRun.speech_structure_id)
            .order_by(
                SpeechStructureRun.speech_structure_id,
                SpeechStructureRun.created_at.desc(),
            )
        )
    ).scalars().all()
    runs = {item.speech_structure_id: item for item in run_rows}

    failed_rows = (
        await session.execute(
            select(
                SpeechStructure.source_id,
                SpeechStructure.input_hash,
                func.count(SpeechStructureRun.id),
            )
            .join(
                SpeechStructureRun,
                SpeechStructureRun.speech_structure_id == SpeechStructure.id,
            )
            .where(SpeechStructureRun.status == StructureStatus.FAILED.value)
            .group_by(SpeechStructure.source_id, SpeechStructure.input_hash)
        )
    ).all()
    failed_by_hash = {
        (source_id, input_hash): int(count)
        for source_id, input_hash, count in failed_rows
    }

    source_ids = list(
        await session.scalars(select(Source.id).order_by(Source.created_at))
    )
    infos: list[SourceStructureInfo] = []
    for source_id in source_ids:
        version_entry = latest_version.get(source_id)
        structure = structures.get(source_id)
        run = runs.get(structure.id) if structure is not None else None
        infos.append(
            SourceStructureInfo(
                source_id=source_id,
                has_transcript=version_entry is not None,
                latest_source_version_id=(
                    version_entry[0] if version_entry else None
                ),
                structure_status=structure.status if structure else None,
                structure_source_version_id=(
                    structure.source_version_id if structure else None
                ),
                structure_completed_at=(
                    structure.completed_at if structure else None
                ),
                run_prompt_version=run.prompt_version if run else None,
                run_error=run.error if run else None,
                run_started_at=run.started_at if run else None,
                run_completed_at=run.completed_at if run else None,
                failed_attempts=(
                    failed_by_hash.get((source_id, structure.input_hash), 0)
                    if structure is not None
                    else 0
                ),
            )
        )
    return infos


class SpeechStructureScheduler:
    """Bounded in-process queue driving ``SpeechStructureService``."""

    def __init__(
        self,
        database: Database,
        *,
        concurrency: int = 2,
        max_attempts: int = 3,
        retry_backoff_seconds: int = 300,
        quota_backoff_seconds: int = 1800,
        service_factory: Callable[[Database], SpeechStructureService] = (
            SpeechStructureService
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
        task.add_done_callback(
            lambda done: self._log_task_failure(source_id, done)
        )
        logger.info(
            "speech_structure.queued",
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
            self._phases[source_id] = "topics"
            started = asyncio.get_running_loop().time()
            try:
                service = self._service_factory(self._database)
                await service.create_for_source(
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
                    "speech_structure.run_finished",
                    extra={
                        "source_id": str(source_id),
                        "duration_s": round(
                            asyncio.get_running_loop().time() - started, 1
                        ),
                    },
                )

    def _log_task_failure(
        self, source_id: UUID, done: "asyncio.Task[None]"
    ) -> None:
        if done.cancelled():
            return
        exc = done.exception()
        if exc is not None:
            logger.error(
                "speech_structure.background_failed",
                extra={"source_id": str(source_id)},
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    async def scan_once(self) -> dict[str, int]:
        """Evaluate every source once and enqueue the eligible ones."""

        async with self._database.transaction() as session:
            infos = await collect_source_infos(session)
        now = datetime.now(UTC)
        counts: dict[str, int] = {
            status.value: 0 for status in DisplayStatus
        }
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
        logger.info("speech_structure.scan", extra=counts)
        return counts

    async def retry_failed(self) -> int:
        """Manually re-enqueue every FAILED source, ignoring the retry cap."""

        async with self._database.transaction() as session:
            infos = await collect_source_infos(session)
        enqueued = 0
        for info in infos:
            if (
                info.structure_status == StructureStatus.FAILED.value
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
                logger.exception("speech_structure.scan_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), interval_seconds)

    def stop(self) -> None:
        self._stop.set()


_scheduler: SpeechStructureScheduler | None = None


def init_scheduler(
    database: Database, settings: "Settings"
) -> SpeechStructureScheduler:
    """Bind the process-wide scheduler during app startup."""

    global _scheduler
    _scheduler = SpeechStructureScheduler(
        database,
        concurrency=settings.speech_structure_concurrency,
        max_attempts=settings.speech_structure_max_attempts,
        retry_backoff_seconds=settings.speech_structure_retry_backoff_seconds,
        quota_backoff_seconds=settings.speech_structure_quota_backoff_seconds,
    )
    return _scheduler


def get_scheduler(database: Database) -> SpeechStructureScheduler:
    """Return the process scheduler; create a default one outside the app."""

    global _scheduler
    if _scheduler is None:
        from app.core.config import get_settings

        _scheduler = init_scheduler(database, get_settings())
    return _scheduler


def schedule_structure_analysis(
    database: Database, source_id: UUID, *, force: bool = False
) -> bool:
    """Queue a speech-structure analysis in the background after an import."""

    return get_scheduler(database).enqueue(source_id, force=force)


def summarize_states(
    infos: Sequence[SourceStructureInfo],
    scheduler: SpeechStructureScheduler,
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
