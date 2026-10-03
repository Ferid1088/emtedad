"""Eligibility, deduplication, and status tests for the canonical scheduler."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.knowledge.structure.domain import SourceProcessingStatus
from app.knowledge.structure.scheduler import (
    DisplayStatus,
    FailureClass,
    SourceProcessingScheduler,
    SourceStructureInfo,
    classify_failure,
    evaluate_source,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _info(**overrides: object) -> SourceStructureInfo:
    values = dict(
        source_id=uuid4(),
        has_transcript=True,
        latest_source_version_id=uuid4(),
        processing_status=None,
        processed_source_version_id=None,
        last_error=None,
        failed_attempts=0,
        last_failed_at=None,
    )
    values.update(overrides)
    return SourceStructureInfo(**values)  # type: ignore[arg-type]


def _evaluate(info: SourceStructureInfo, **overrides: object):
    values = dict(
        now=NOW,
        is_active=False,
        is_queued=False,
        max_attempts=3,
        retry_backoff_seconds=60,
        quota_backoff_seconds=600,
    )
    values.update(overrides)
    return evaluate_source(info, **values)  # type: ignore[arg-type]


def test_missing_state_is_eligible() -> None:
    evaluation = _evaluate(_info())
    assert evaluation.eligible
    assert evaluation.status == DisplayStatus.PENDING
    assert evaluation.reason == "missing"


def test_ready_current_structure_is_not_eligible() -> None:
    version_id = uuid4()
    evaluation = _evaluate(
        _info(
            latest_source_version_id=version_id,
            processing_status=SourceProcessingStatus.READY.value,
            processed_source_version_id=version_id,
        )
    )
    assert not evaluation.eligible
    assert evaluation.status == DisplayStatus.READY


def test_ready_with_newer_version_is_stale_and_eligible() -> None:
    evaluation = _evaluate(
        _info(
            latest_source_version_id=uuid4(),
            processing_status=SourceProcessingStatus.READY.value,
            processed_source_version_id=uuid4(),
        )
    )
    assert evaluation.eligible
    assert evaluation.status == DisplayStatus.STALE
    assert evaluation.reason == "stale_input"


def test_no_transcript_is_unavailable() -> None:
    evaluation = _evaluate(_info(has_transcript=False))
    assert not evaluation.eligible
    assert evaluation.status == DisplayStatus.UNAVAILABLE


def test_interrupted_in_progress_state_is_reprocessed() -> None:
    for status in (
        SourceProcessingStatus.STRUCTURING,
        SourceProcessingStatus.UNIT_EXTRACTING,
    ):
        evaluation = _evaluate(_info(processing_status=status.value))
        assert evaluation.eligible
        assert evaluation.reason == "interrupted"


def test_active_or_queued_source_is_not_double_scheduled() -> None:
    info = _info()
    assert not _evaluate(info, is_active=True).eligible
    assert not _evaluate(info, is_queued=True).eligible


def test_pending_states_are_eligible() -> None:
    for status in (
        SourceProcessingStatus.INGESTED,
        SourceProcessingStatus.STRUCTURE_PENDING,
        SourceProcessingStatus.STRUCTURED,
        SourceProcessingStatus.UNIT_EXTRACTION_PENDING,
    ):
        assert _evaluate(_info(processing_status=status.value)).eligible


def test_review_required_blocks_scheduling() -> None:
    for status in (
        SourceProcessingStatus.STRUCTURE_REVIEW_REQUIRED,
        SourceProcessingStatus.UNIT_REVIEW_REQUIRED,
    ):
        evaluation = _evaluate(_info(processing_status=status.value))
        assert not evaluation.eligible
        assert evaluation.status == DisplayStatus.REVIEW


def test_failed_within_backoff_waits() -> None:
    evaluation = _evaluate(
        _info(
            processing_status=SourceProcessingStatus.FAILED.value,
            last_error="boom",
            failed_attempts=1,
            last_failed_at=NOW - timedelta(seconds=30),
        )
    )
    assert not evaluation.eligible
    assert evaluation.status == DisplayStatus.PENDING
    assert evaluation.reason == "backoff"


def test_failed_after_backoff_retries() -> None:
    evaluation = _evaluate(
        _info(
            processing_status=SourceProcessingStatus.FAILED.value,
            last_error="boom",
            failed_attempts=1,
            last_failed_at=NOW - timedelta(seconds=90),
        )
    )
    assert evaluation.eligible
    assert evaluation.reason == "retry"


def test_exhausted_attempts_are_failed() -> None:
    evaluation = _evaluate(
        _info(
            processing_status=SourceProcessingStatus.FAILED.value,
            last_error="boom",
            failed_attempts=3,
            last_failed_at=NOW - timedelta(days=1),
        )
    )
    assert not evaluation.eligible
    assert evaluation.status == DisplayStatus.FAILED
    assert evaluation.reason == "attempts_exhausted"


def test_quota_failures_retry_on_the_longer_quota_backoff() -> None:
    assert classify_failure("DevinCloudError: out_of_quota") == FailureClass.QUOTA
    assert classify_failure("HTTP 429: rate limit") == FailureClass.RATE_LIMIT
    assert classify_failure("ValueError: parse failed") == FailureClass.FAILED

    # Quota failures are not counted against max_attempts.
    evaluation = _evaluate(
        _info(
            processing_status=SourceProcessingStatus.FAILED.value,
            last_error="DevinCloudError: out_of_quota",
            failed_attempts=9,
            last_failed_at=NOW - timedelta(seconds=700),
        ),
        max_attempts=3,
    )
    assert evaluation.eligible
    assert evaluation.reason == "quota"


class _FakeService:
    """Stand-in for SourceProcessingService that records calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, bool]] = []

    async def process_source(self, source_id, *, force=False, on_progress=None):
        self.calls.append((source_id, force))
        if on_progress is not None:
            on_progress("structure")


@pytest.mark.asyncio
async def test_scheduler_deduplicates_queued_and_running_sources() -> None:
    service = _FakeService()
    scheduler = SourceProcessingScheduler(
        database=None,  # type: ignore[arg-type]
        service_factory=lambda _db: service,  # type: ignore[arg-type]
    )
    source_id = uuid4()

    assert scheduler.enqueue(source_id)
    assert not scheduler.enqueue(source_id)  # already queued
    assert scheduler.is_queued(source_id)

    await asyncio.gather(*scheduler._tasks)
    assert service.calls == [(source_id, False)]
    assert not scheduler.is_queued(source_id)
    assert not scheduler.is_running(source_id)


@pytest.mark.asyncio
async def test_scheduler_task_failure_is_logged_not_raised() -> None:
    class _Boom:
        async def process_source(self, source_id, *, force=False, on_progress=None):
            raise RuntimeError("provider down")

    scheduler = SourceProcessingScheduler(
        database=None,  # type: ignore[arg-type]
        service_factory=lambda _db: _Boom(),  # type: ignore[arg-type]
    )
    source_id = uuid4()
    assert scheduler.enqueue(source_id)
    await asyncio.wait(scheduler._tasks)
    # The task crashed but the error callback consumed it; the scheduler
    # remains usable and the failed state drives the next scan.
    assert scheduler.enqueue(source_id)
    await asyncio.wait(scheduler._tasks)
