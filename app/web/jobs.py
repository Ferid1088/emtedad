"""Background execution for long owner actions (single local process).

Production steps call LLMs and can take minutes. Instead of blocking the
browser request, an action starts a job keyed by the production (brief);
the workspace shows its status and refreshes until it finishes. Only one
job per key runs at a time, so double clicks cannot start a step twice.

State lives in memory: after an app restart the job list is empty, but
every finished step is persisted in the database as usual.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.content_engine.service import GateBlockedError
from app.knowledge.llm.apimaster import APIMasterError
from app.knowledge.llm.factory import RoutingConfigurationError

logger = logging.getLogger(__name__)


@dataclass
class Job:
    key: str
    action: str
    label: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    error: str | None = None

    @property
    def running(self) -> bool:
        return self.finished_at is None

    @property
    def elapsed_seconds(self) -> int:
        end = self.finished_at or datetime.now(UTC)
        return int((end - self.started_at).total_seconds())


_API_MESSAGES = {
    "missing_key": (
        "Kein APIMaster-API-Key eingetragen. Trage EMTEDAD_APIMASTER_API_KEY "
        "in die .env-Datei ein und starte die App neu."
    ),
    "auth": "APIMaster hat den API-Key abgelehnt. Bitte den Key prüfen.",
    "quota": "APIMaster-Guthaben oder Kontingent ist erschöpft.",
    "rate_limit": (
        "APIMaster meldet zu viele Anfragen. Bitte in ein paar Minuten erneut starten."
    ),
    "timeout": (
        "APIMaster/das Modell hat zu lange gebraucht (Timeout). Bitte den "
        "Schritt erneut starten."
    ),
    "upstream": (
        "Das Modell bei APIMaster ist gerade nicht erreichbar. Bitte später "
        "erneut starten."
    ),
    "transport": (
        "Keine Verbindung zu APIMaster (Netzwerk). Internetverbindung prüfen "
        "und erneut starten."
    ),
    "model_not_found": (
        "Die eingestellte Modell-ID gibt es bei APIMaster nicht. Bitte unter "
        "Settings die Modelle prüfen."
    ),
    "schema": (
        "Das Modell hat keine gültige Antwort geliefert. Bitte den Schritt "
        "erneut starten."
    ),
    "malformed": (
        "APIMaster hat eine unlesbare Antwort geliefert. Bitte erneut starten."
    ),
}

_KNOWN_MESSAGES = {
    "has no grounding units": (
        "Für dieses Thema gibt es kein Quellmaterial (keine Knowledge Units). "
        "Weise dem Kanal passende Quellen zu oder aktiviere die "
        "Internet-Recherche unter Settings."
    ),
}


def friendly_error(exc: BaseException) -> str:
    """A message the owner can act on — never a bare stack trace."""

    if isinstance(exc, APIMasterError):
        kind = getattr(exc, "error_kind", "")
        if type(exc).__name__ == "APIMasterMissingKeyError":
            kind = "missing_key"
        return _API_MESSAGES.get(kind, f"APIMaster-Fehler: {exc}")
    from app.voice.elevenlabs import VoiceProviderError

    if isinstance(exc, VoiceProviderError):
        return str(exc)
    if isinstance(exc, RoutingConfigurationError):
        return f"Konfigurationsfehler: {exc}"
    text = str(exc)
    for needle, message in _KNOWN_MESSAGES.items():
        if needle in text:
            return message
    if isinstance(exc, (GateBlockedError, ValueError, LookupError)):
        return text or type(exc).__name__
    return f"Unerwarteter Fehler ({type(exc).__name__}): {text}"[:500]


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def get(self, key: str) -> Job | None:
        return self._jobs.get(key)

    def is_running(self, key: str) -> bool:
        job = self._jobs.get(key)
        return job is not None and job.running

    def start(
        self,
        key: str,
        action: str,
        label: str,
        work: Callable[[], Awaitable[object]],
    ) -> bool:
        """Start ``work`` in the background; False if a job already runs."""

        if self.is_running(key):
            return False
        job = Job(key=key, action=action, label=label)
        self._jobs[key] = job

        async def runner() -> None:
            try:
                await work()
            except Exception as exc:  # noqa: BLE001 — surfaced to the owner
                logger.exception("job %s (%s) failed", key, action)
                job.error = friendly_error(exc)
            finally:
                job.finished_at = datetime.now(UTC)

        task = asyncio.create_task(runner())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    def clear(self, key: str) -> None:
        job = self._jobs.get(key)
        if job is not None and not job.running:
            del self._jobs[key]

    async def wait_all(self) -> None:
        """Test/shutdown helper: wait until every running job finished."""

        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


jobs = JobRegistry()
