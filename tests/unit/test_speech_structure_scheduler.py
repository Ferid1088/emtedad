"""Eligibility, deduplication, and status tests for the structure scheduler."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.speech_structure import scheduler as scheduler_module
from app.speech_structure.scheduler import (
    CURRENT_PROMPT_VERSION,
    FailureClass,
    SourceStructureInfo,
    SpeechStructureScheduler,
    classify_failure,
    evaluate_source,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
TEMPLATES = Path(__file__).parents[2] / "app" / "web" / "templates"


def _info(**overrides: object) -> SourceStructureInfo:
    values = dict(
        source_id=uuid4(),
        has_transcript=True,
        latest_source_version_id=uuid4(),
        structure_status=None,
        structure_source_version_id=None,
        structure_completed_at=None,
        run_prompt_version=None,
        run_error=None,
        run_started_at=None,
        run_completed_at=None,
        failed_attempts=0,
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


def test_missing_structure_is_eligible() -> None:
    evaluation = _evaluate(_info())
    assert evaluation.eligible
    assert evaluation.status.value == "PENDING"
    assert evaluation.reason == "missing"


def test_ready_current_structure_is_not_eligible() -> None:
    version_id = uuid4()
    evaluation = _evaluate(
        _info(
            latest_source_version_id=version_id,
            structure_status="READY",
            structure_source_version_id=version_id,
            structure_completed_at=NOW,
            run_prompt_version=CURRENT_PROMPT_VERSION,
        )
    )
    assert not evaluation.eligible
    assert evaluation.status.value == "READY"


def test_ready_with_newer_transcript_is_stale_and_eligible() -> None:
    evaluation = _evaluate(
        _info(
            structure_status="READY",
            structure_source_version_id=uuid4(),  # older version
            structure_completed_at=NOW,
            run_prompt_version=CURRENT_PROMPT_VERSION,
        )
    )
    assert evaluation.eligible
    assert evaluation.status.value == "STALE"


def test_ready_with_outdated_prompt_version_is_stale() -> None:
    version_id = uuid4()
    evaluation = _evaluate(
        _info(
            latest_source_version_id=version_id,
            structure_status="READY",
            structure_source_version_id=version_id,
            structure_completed_at=NOW,
            run_prompt_version="old-v0",
        )
    )
    assert evaluation.eligible
    assert evaluation.status.value == "STALE"


def test_failed_structure_retries_after_backoff() -> None:
    failed = _info(
        structure_status="FAILED",
        run_error="provider exploded",
        run_completed_at=NOW - timedelta(seconds=120),
        failed_attempts=1,
    )
    evaluation = _evaluate(failed)
    assert evaluation.eligible
    assert evaluation.reason == "retry"


def test_recent_failure_waits_for_backoff() -> None:
    evaluation = _evaluate(
        _info(
            structure_status="FAILED",
            run_error="provider exploded",
            run_completed_at=NOW - timedelta(seconds=10),
            failed_attempts=1,
        )
    )
    assert not evaluation.eligible
    assert evaluation.status.value == "PENDING"
    assert evaluation.reason == "backoff"


def test_retry_backoff_grows_with_attempts() -> None:
    info = _info(
        structure_status="FAILED",
        run_error="boom",
        run_completed_at=NOW - timedelta(seconds=200),
        failed_attempts=2,
    )
    # second retry requires 120s backoff; 200s elapsed -> due
    assert _evaluate(info).eligible
    # a fresh second failure at t-100s is still in backoff
    recent = _info(
        structure_status="FAILED",
        run_error="boom",
        run_completed_at=NOW - timedelta(seconds=100),
        failed_attempts=2,
    )
    assert not _evaluate(recent).eligible


def test_attempts_exhausted_marks_failed() -> None:
    evaluation = _evaluate(
        _info(
            structure_status="FAILED",
            run_error="boom",
            run_completed_at=NOW - timedelta(days=1),
            failed_attempts=3,
        )
    )
    assert not evaluation.eligible
    assert evaluation.status.value == "FAILED"


def test_quota_failure_gets_longer_backoff_and_no_attempt_cap() -> None:
    info = _info(
        structure_status="FAILED",
        run_error="Devin-Kontingent erschöpft (out_of_quota)",
        run_completed_at=NOW - timedelta(seconds=100),
        failed_attempts=99,
    )
    assert classify_failure(info.run_error) is FailureClass.QUOTA
    assert not _evaluate(info).eligible  # still inside quota backoff
    old = _info(
        structure_status="FAILED",
        run_error="Devin-Kontingent erschöpft (out_of_quota)",
        run_completed_at=NOW - timedelta(seconds=700),
        failed_attempts=99,
    )
    assert _evaluate(old).eligible  # quota never exhausts retries


def test_rate_limit_failure_classified() -> None:
    info = _info(
        structure_status="FAILED",
        run_error="429 too many requests",
        run_completed_at=NOW - timedelta(seconds=700),
    )
    assert classify_failure(info.run_error) is FailureClass.RATE_LIMIT
    assert _evaluate(info).eligible


def test_interrupted_processing_is_recovered() -> None:
    evaluation = _evaluate(_info(structure_status="PROCESSING"))
    assert evaluation.eligible
    assert evaluation.reason == "interrupted"


def test_active_and_queued_sources_are_not_eligible() -> None:
    assert _evaluate(_info(), is_active=True).status.value == "RUNNING"
    assert not _evaluate(_info(), is_active=True).eligible
    assert _evaluate(_info(), is_queued=True).status.value == "PENDING"
    assert not _evaluate(_info(), is_queued=True).eligible


def test_source_without_transcript_is_unavailable() -> None:
    evaluation = _evaluate(_info(has_transcript=False, latest_source_version_id=None))
    assert not evaluation.eligible
    assert evaluation.status.value == "UNAVAILABLE"


def test_failed_without_run_row_is_retryable() -> None:
    evaluation = _evaluate(
        _info(structure_status="FAILED", run_completed_at=None, failed_attempts=1)
    )
    assert evaluation.eligible


class _FakeService:
    """Records calls; optionally blocks or raises."""

    def __init__(
        self,
        database: object,
        calls: list[tuple[object, bool]],
        started: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
        fail: bool = False,
    ) -> None:
        self._calls = calls
        self._started = started
        self._release = release
        self._fail = fail

    async def create_for_source(
        self,
        source_id: object,
        *,
        force: bool = False,
        on_progress: object = None,
    ) -> None:
        self._calls.append((source_id, force))
        if self._started is not None:
            self._started.set()
        if self._release is not None:
            await self._release.wait()
        if callable(on_progress):
            on_progress("topics:1/3")
        if self._fail:
            raise RuntimeError("provider exploded")


def _scheduler(
    calls: list[tuple[object, bool]],
    *,
    concurrency: int = 1,
    started: asyncio.Event | None = None,
    release: asyncio.Event | None = None,
    fail: bool = False,
) -> SpeechStructureScheduler:
    def factory(database: object) -> _FakeService:
        return _FakeService(
            database, calls, started=started, release=release, fail=fail
        )

    return SpeechStructureScheduler(
        object(), concurrency=concurrency, service_factory=factory  # type: ignore[arg-type]
    )


async def _drain(scheduler: SpeechStructureScheduler) -> None:
    while scheduler._tasks:
        await asyncio.gather(*scheduler._tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_enqueue_runs_service_and_reports_phase() -> None:
    calls: list[tuple[object, bool]] = []
    started, release = asyncio.Event(), asyncio.Event()
    scheduler = _scheduler(calls, started=started, release=release)
    source_id = uuid4()
    assert scheduler.enqueue(source_id)
    await asyncio.wait_for(started.wait(), timeout=5)
    assert scheduler.is_running(source_id)
    release.set()
    await _drain(scheduler)
    assert calls == [(source_id, False)]
    assert not scheduler.is_running(source_id)
    assert scheduler.phase_of(source_id) is None


@pytest.mark.asyncio
async def test_enqueue_dedupes_queued_and_active() -> None:
    calls: list[tuple[object, bool]] = []
    started, release = asyncio.Event(), asyncio.Event()
    scheduler = _scheduler(calls, started=started, release=release)
    source_id = uuid4()
    assert scheduler.enqueue(source_id)
    assert not scheduler.enqueue(source_id)  # already queued or active
    await asyncio.wait_for(started.wait(), timeout=5)
    assert not scheduler.enqueue(source_id)  # active
    release.set()
    await _drain(scheduler)
    assert len(calls) == 1
    assert scheduler.enqueue(source_id)  # completed -> new run allowed
    await _drain(scheduler)


@pytest.mark.asyncio
async def test_concurrency_limits_parallel_runs() -> None:
    calls: list[tuple[object, bool]] = []
    started, release = asyncio.Event(), asyncio.Event()
    scheduler = _scheduler(
        calls, concurrency=1, started=started, release=release
    )
    first, second = uuid4(), uuid4()
    scheduler.enqueue(first)
    scheduler.enqueue(second)
    await asyncio.wait_for(started.wait(), timeout=5)
    assert scheduler.is_running(first)
    assert scheduler.is_queued(second)
    assert not scheduler.is_running(second)
    release.set()
    await _drain(scheduler)
    assert {sid for sid, _ in calls} == {first, second}


@pytest.mark.asyncio
async def test_failing_service_is_logged_not_raised(caplog) -> None:
    calls: list[tuple[object, bool]] = []
    scheduler = _scheduler(calls, fail=True)
    scheduler.enqueue(uuid4())
    await _drain(scheduler)
    assert any(
        record.message == "speech_structure.background_failed"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_schedule_structure_analysis_uses_global_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, bool]] = []
    scheduler = _scheduler(calls)
    monkeypatch.setattr(scheduler_module, "_scheduler", scheduler)
    source_id = uuid4()
    assert scheduler_module.schedule_structure_analysis(object(), source_id)
    assert not scheduler_module.schedule_structure_analysis(object(), source_id)
    await _drain(scheduler)
    assert calls == [(source_id, False)]


def _render_list(status: str, *, structure: object = None, attempts: int = 0) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]),
    )
    source = SimpleNamespace(
        id=uuid4(), title="Talk", language="fa", canonical_url="https://x.test"
    )
    info = SimpleNamespace(failed_attempts=attempts)
    state = SimpleNamespace(status=SimpleNamespace(value=status))
    return env.get_template("speech_structures.html").render(
        request=SimpleNamespace(url=SimpleNamespace(path="/speech-structures")),
        title="t",
        sources=[source],
        structures={source.id: structure} if structure else {},
        infos={source.id: info},
        states={source.id: state},
        counts={},
        scheduler=SimpleNamespace(phase_of=lambda _sid: None),
    )


def test_list_shows_pending_badge() -> None:
    assert "wartet" in _render_list("PENDING")


def test_list_shows_running_without_start_button() -> None:
    html = _render_list("RUNNING")
    assert "wird erstellt" in html
    assert "Erneut versuchen" not in html
    assert "Struktur erstellen" not in html


def test_list_shows_ready_with_link_and_timestamp() -> None:
    structure = SimpleNamespace(
        version=2,
        status="READY",
        completed_at=datetime(2026, 1, 1, 12, 30, tzinfo=UTC),
    )
    html = _render_list("READY", structure=structure)
    assert "fertig" in html
    assert "Struktur ansehen" in html
    assert "01.01.2026 12:30" in html


def test_list_shows_failed_with_retry_button() -> None:
    structure = SimpleNamespace(version=1, status="FAILED", completed_at=None)
    html = _render_list("FAILED", structure=structure)
    assert "fehlgeschlagen" in html
    assert "Erneut versuchen" in html


def test_list_shows_unavailable_neutral_state() -> None:
    html = _render_list("UNAVAILABLE")
    assert "kein Transkript" in html
    assert "Erneut versuchen" not in html
