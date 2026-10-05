"""Phase 4 §2–§6: provider capacity policy and work-class starvation."""

import asyncio
from uuid import uuid4

from app.knowledge.llm.capacity import (
    ProviderCapacity,
    WorkClass,
    current_work_class,
    reset_work_class,
    set_work_class,
)
from app.knowledge.structure.scheduler import SourceProcessingScheduler


def test_background_never_consumes_all_slots() -> None:
    """With bg_max=2 of total=5, the 3rd background caller waits while an
    interactive caller still acquires a slot."""

    async def scenario() -> None:
        capacity = ProviderCapacity(total=5, background_max=2)
        acquired: list[str] = []
        release = asyncio.Event()

        async def hold(work_class: WorkClass, name: str) -> None:
            async with capacity.acquire(work_class):
                acquired.append(name)
                await release.wait()

        tasks = [
            asyncio.create_task(hold(WorkClass.BACKGROUND_RETRY, "bg1")),
            asyncio.create_task(hold(WorkClass.BACKGROUND_RETRY, "bg2")),
            asyncio.create_task(hold(WorkClass.BACKGROUND_RETRY, "bg3")),
            asyncio.create_task(hold(WorkClass.INTERACTIVE_OWNER, "ui1")),
        ]
        await asyncio.sleep(0.05)
        # bg1+bg2 hold both background slots; bg3 waits at the bg gate —
        # but ui1 must still get a slot: background cannot starve it.
        assert sorted(acquired) == ["bg1", "bg2", "ui1"]
        assert capacity.waiting[WorkClass.BACKGROUND_RETRY] == 1
        assert capacity.snapshot()["in_flight_total"] == 3
        release.set()
        await asyncio.gather(*tasks)

    asyncio.run(scenario())


def test_total_capacity_bounds_all_classes() -> None:
    async def scenario() -> None:
        capacity = ProviderCapacity(total=3, background_max=2)
        entered = 0
        peak = 0
        release = asyncio.Event()

        async def hold(work_class: WorkClass) -> None:
            nonlocal entered, peak
            async with capacity.acquire(work_class):
                entered += 1
                peak = max(peak, entered)
                await release.wait()
                entered -= 1

        tasks = [
            asyncio.create_task(hold(WorkClass.INTERACTIVE_OWNER)) for _ in range(4)
        ]
        tasks += [asyncio.create_task(hold(WorkClass.BACKGROUND_NEW)) for _ in range(4)]
        await asyncio.sleep(0.05)
        assert peak == 3  # total cap enforced across classes
        release.set()
        await asyncio.gather(*tasks)

    asyncio.run(scenario())


def test_work_class_contextvar_defaults_to_interactive() -> None:
    assert current_work_class() is WorkClass.INTERACTIVE_OWNER
    token = set_work_class(WorkClass.BACKGROUND_RETRY)
    assert current_work_class() is WorkClass.BACKGROUND_RETRY
    reset_work_class(token)
    assert current_work_class() is WorkClass.INTERACTIVE_OWNER


def test_scheduler_maps_reason_to_work_class() -> None:
    assert (
        SourceProcessingScheduler._work_class_for_reason("quota")
        is WorkClass.BACKGROUND_RETRY
    )
    assert (
        SourceProcessingScheduler._work_class_for_reason("rate_limit")
        is WorkClass.BACKGROUND_RETRY
    )
    assert (
        SourceProcessingScheduler._work_class_for_reason("retry")
        is WorkClass.BACKGROUND_RETRY
    )
    assert (
        SourceProcessingScheduler._work_class_for_reason("missing")
        is WorkClass.BACKGROUND_NEW
    )
    assert (
        SourceProcessingScheduler._work_class_for_reason("pending")
        is WorkClass.BACKGROUND_NEW
    )


class _NoopService:
    async def process_source(self, *args: object, **kwargs: object) -> None:
        return None


def test_paused_scheduler_refuses_background_not_owner() -> None:
    async def scenario() -> None:
        scheduler = SourceProcessingScheduler(
            database=None,  # type: ignore[arg-type]
            service_factory=lambda db: _NoopService(),  # type: ignore[arg-type,return-value]
        )
        scheduler.set_paused(True)
        # Background work is gated…
        assert not scheduler.enqueue(uuid4(), work_class=WorkClass.BACKGROUND_NEW)
        assert not scheduler.enqueue(uuid4(), work_class=WorkClass.BACKGROUND_RETRY)
        # …but owner-requested processing still enqueues.
        assert scheduler.enqueue(uuid4(), force=True)
        await asyncio.sleep(0)
        scheduler.stop()

    asyncio.run(scenario())


def test_force_enqueue_is_owner_requested() -> None:
    scheduler = SourceProcessingScheduler(
        database=None,  # type: ignore[arg-type]
        service_factory=lambda db: _NoopService(),  # type: ignore[arg-type,return-value]
    )
    assert scheduler._default_work_class(force=True) is WorkClass.OWNER_REQUESTED
    assert scheduler._default_work_class(force=False) is WorkClass.BACKGROUND_NEW


def test_retry_failed_enqueues_as_owner_even_when_paused(
    monkeypatch,
) -> None:
    """Owner retry-all must bypass the pause gate and the attempt cap."""
    import app.knowledge.structure.scheduler as scheduler_module

    class _Tx:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> bool:
            return False

    class _FakeDb:
        def transaction(self) -> _Tx:
            return _Tx()

    info = scheduler_module.SourceStructureInfo(
        source_id=uuid4(),
        has_transcript=True,
        latest_source_version_id=uuid4(),
        processing_status="FAILED",
        processed_source_version_id=None,
        last_error="genuine analysis failure",
        failed_attempts=9,
        last_failed_at=None,
    )

    async def scenario() -> None:
        scheduler = SourceProcessingScheduler(
            database=_FakeDb(),  # type: ignore[arg-type]
            service_factory=lambda db: _NoopService(),  # type: ignore[arg-type,return-value]
        )
        scheduler.set_paused(True)

        async def fake_collect(session: object) -> list:
            return [info]

        monkeypatch.setattr(scheduler_module, "collect_source_infos", fake_collect)
        assert await scheduler.retry_failed() == 1
        await asyncio.sleep(0)
        scheduler.stop()

    asyncio.run(scenario())
