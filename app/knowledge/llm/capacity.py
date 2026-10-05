"""Process-wide provider capacity policy.

Provider-agnostic: every structured-extraction provider call acquires a
capacity slot so background source processing can never consume the whole
provider concurrency budget. Two limits are enforced:

- ``provider_max_concurrency`` — total in-flight provider calls.
- ``provider_background_max_concurrency`` — cap for BACKGROUND_* classes;
  the remainder is effectively reserved for interactive/owner work.

Work class is propagated via a ContextVar, so the scheduler can tag the
work it drives without threading a parameter through every service in the
call chain. ``asyncio.create_task`` copies context, which keeps the tag
inside scheduled tasks.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from contextvars import ContextVar, Token
from enum import StrEnum

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class WorkClass(StrEnum):
    """Scheduling priority classes for provider capacity."""

    INTERACTIVE_OWNER = "interactive_owner"  # owner actions: mine, review, translate
    OWNER_REQUESTED = "owner_requested"  # owner-triggered resource processing
    BACKGROUND_NEW = "background_new"  # scheduler: never-processed sources
    BACKGROUND_RETRY = "background_retry"  # scheduler: retrying failed sources


BACKGROUND_CLASSES = frozenset({WorkClass.BACKGROUND_NEW, WorkClass.BACKGROUND_RETRY})

_current_work_class: ContextVar[WorkClass] = ContextVar(
    "emtedad_llm_work_class", default=WorkClass.INTERACTIVE_OWNER
)


def current_work_class() -> WorkClass:
    return _current_work_class.get()


def set_work_class(work_class: WorkClass) -> Token[WorkClass]:
    return _current_work_class.set(work_class)


def reset_work_class(token: Token[WorkClass]) -> None:
    _current_work_class.reset(token)


class ProviderCapacity:
    """Bounded acquisition of provider slots with per-class accounting."""

    def __init__(self, *, total: int, background_max: int) -> None:
        self.total = max(1, total)
        self.background_max = max(1, min(background_max, self.total))
        self._total_sem = asyncio.Semaphore(self.total)
        self._background_sem = asyncio.Semaphore(self.background_max)
        self.in_flight: dict[WorkClass, int] = {c: 0 for c in WorkClass}
        self.waiting: dict[WorkClass, int] = {c: 0 for c in WorkClass}

    @contextlib.asynccontextmanager
    async def acquire(self, work_class: WorkClass) -> AsyncIterator[None]:
        """Hold a capacity slot; background classes hold two gates."""

        is_background = work_class in BACKGROUND_CLASSES
        wait_started = time.monotonic()
        self.waiting[work_class] += 1
        try:
            if is_background:
                await self._background_sem.acquire()
            try:
                await self._total_sem.acquire()
            except BaseException:
                if is_background:
                    self._background_sem.release()
                raise
        finally:
            self.waiting[work_class] -= 1
        wait_seconds = time.monotonic() - wait_started
        # Slot acquisition is the starvation signal the owner cares about:
        # a long interactive wait means background work consumed the pool.
        if wait_seconds >= 1.0:
            logger.info(
                "provider_capacity_wait",
                extra={
                    "work_class": work_class.value,
                    "wait_seconds": round(wait_seconds, 1),
                    "in_flight": sum(self.in_flight.values()),
                },
            )
        self.in_flight[work_class] += 1
        try:
            yield
        finally:
            self.in_flight[work_class] -= 1
            self._total_sem.release()
            if is_background:
                self._background_sem.release()

    def snapshot(self) -> dict[str, object]:
        return {
            "total": self.total,
            "background_max": self.background_max,
            "reserved_interactive": self.total - self.background_max,
            "in_flight": {c.value: n for c, n in self.in_flight.items() if n},
            "waiting": {c.value: n for c, n in self.waiting.items() if n},
            "in_flight_total": sum(self.in_flight.values()),
            "waiting_total": sum(self.waiting.values()),
        }


_capacity: ProviderCapacity | None = None


def get_capacity() -> ProviderCapacity:
    """Process-wide capacity pool, sized from provider settings."""

    global _capacity
    if _capacity is None:
        settings = get_settings()
        _capacity = ProviderCapacity(
            total=settings.provider_max_concurrency,
            background_max=settings.provider_background_max_concurrency,
        )
    return _capacity


def reset_capacity() -> None:
    """Drop the singleton (tests re-create it with different limits)."""

    global _capacity
    _capacity = None
