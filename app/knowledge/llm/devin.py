"""Structured extraction provider backed by Devin Cloud sessions.

Each call creates a session via the Devin v1 REST API (``POST /v1/sessions``)
and polls it until finished, reading the session's ``structured_output``. A
cloud session is a full agent run — minute-scale latency, billed in ACUs — so
this provider is an opt-in fallback, not the default. Select it with
``EMTEDAD_LLM_PROVIDER=devin`` and set ``EMTEDAD_DEVIN_API_KEY``.
"""

import asyncio
import contextlib
import json
import logging
import time
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.llm.capacity import current_work_class, get_capacity

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.devin.ai"
_POLL_INTERVAL_SECONDS = 15.0
_MINIMUM_TIMEOUT_SECONDS = 1200
_TERMINAL_DONE_STATES = frozenset({"blocked", "finished"})
_TERMINAL_FAILURE_STATES = frozenset({"expired"})
_PROMPT_CHAR_LIMIT = 29_000  # API hard limit is 30_000
_END_OF_INPUT = "END-OF-INPUT"
# A fresh session rejects /message with 400 "still initializing" while the
# agent boots; retry briefly instead of failing the whole extraction.
_MESSAGE_INITIALIZING_DELAY_SECONDS = 5.0
_MESSAGE_INITIALIZING_RETRY_SECONDS = 120.0
# status_enum flips to "blocked" before the final devin_message lands in the
# messages array; keep polling briefly instead of failing the extraction.
_EMPTY_OUTPUT_GRACE_SECONDS = 60.0
_NUDGE_MESSAGE = (
    f"{_END_OF_INPUT}. You finished your turn without producing the JSON "
    "output. Produce exactly one JSON object matching the JSON schema given "
    "earlier and set the session's structured output to it. No commentary."
)
_CORRUPTION_REPAIR_MESSAGE = (
    "Your JSON output contains Unicode replacement characters (U+FFFD, �) "
    "— corrupted text inside the string values. Produce the same JSON "
    "object again with the corrupted words rewritten as intact text; "
    "keep every other value unchanged. No commentary."
)
# In-session repair gives the agent one bounded turn to fix corrupted
# output before the provider falls back to a fresh session.
_CORRUPTION_REPAIR_TIMEOUT_SECONDS = 600.0
# Orphaned remote sessions (process killed before _terminate_session ran)
# hold concurrency slots forever. ``blocked``/``expired`` sessions older
# than this have no live caller — every extract path fails or finishes
# long before — so they are safe to reap.
_ORPHAN_SESSION_AGE_SECONDS = 30 * 60
_ORPHAN_STATES = frozenset({"blocked", "expired"})
# Only sessions we created carry this tag — the sweep must never reap a
# session the account owns for other tools (Devin app, CLI, other services
# share the same concurrency quota).
_APP_TAG = "emtedad-app"
_SWEEP_INTERVAL_SECONDS = 600.0
# -inf so the first sweep after process start always runs; 0.0 compared
# against time.monotonic() skipped it whenever uptime < sweep interval.
_last_orphan_sweep = float("-inf")


class DevinCloudError(RuntimeError):
    """Raised for auth, HTTP, timeout, JSON, or schema failures."""


class DevinRateLimitError(DevinCloudError):
    """Transient 429 — safe to retry with bounded backoff."""


class DevinQuotaError(DevinCloudError):
    """Hard quota/concurrency exhaustion — never retried inside one call."""


class DevinCloudProvider:
    name = "devin-cloud"

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def extract(self, request: StructuredExtractionRequest) -> BaseModel:
        settings = get_settings()
        if settings.devin_api_key is None:
            raise DevinCloudError(
                "EMTEDAD_DEVIN_API_KEY ist nicht gesetzt. "
                "Devin Cloud ist als LLM-Provider konfiguriert."
            )
        prompt = (
            "Produce exactly one JSON object matching the JSON schema below "
            "and set the session's structured output to it. "
            "Do not use markdown fences and do not add commentary.\n\n"
            f"JSON schema:\n{request.output_model.model_json_schema()}\n\n"
            f"Task: {request.task}\n"
            f"Prompt version: {request.prompt_version}\n"
            f"Instructions: {request.instructions}\n\n"
            f"Source material:\n{request.input_text}"
        )
        timeout_seconds = max(request.timeout_seconds, _MINIMUM_TIMEOUT_SECONDS)
        # The capacity slot is held only while a cloud session exists —
        # prompt assembly and validation never occupy provider quota.
        async with get_capacity().acquire(current_work_class()):  # noqa: ASYNC100
            result = await self._run_session(
                request,
                prompt,
                timeout_seconds,
                settings.devin_api_key.get_secret_value(),
            )
            if _has_replacement_chars(result):
                # Remote sessions sometimes corrupt multi-byte output
                # (observed: U+FFFD inside Persian words). One fresh
                # session usually produces clean text; a still-corrupted
                # retry is returned as-is — downstream deterministic
                # gates (e.g. ENCODING_CORRUPTION) remain the backstop.
                logger.warning(
                    "devin.encoding_corruption_retry",
                    extra={"task": request.task},
                )
                result = await self._run_session(
                    request,
                    prompt,
                    timeout_seconds,
                    settings.devin_api_key.get_secret_value(),
                )
            return result

    async def _run_session(
        self,
        request: StructuredExtractionRequest,
        prompt: str,
        timeout_seconds: float,
        api_key: str,
    ) -> BaseModel:
        settings = get_settings()
        async with httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={"Authorization": (f"Bearer {api_key}")},
            timeout=60,
            transport=self._transport,
        ) as client:
            await self._sweep_orphaned_sessions(client)
            session_id = await self._create_session_with_backoff(
                client, prompt, settings
            )
            try:
                payload = await self._await_session(
                    client, session_id, deadline_seconds=timeout_seconds
                )
                result = self._validate(request, payload)
                if _has_replacement_chars(result):
                    # Cheapest fix first: the live session can see and
                    # repair its own corrupted output — a fresh session
                    # only makes sense when the session is unreachable
                    # (handled by the caller's one-shot retry).
                    try:
                        await self._send_message(
                            client, session_id, _CORRUPTION_REPAIR_MESSAGE
                        )
                    except DevinCloudError:
                        pass  # finished/expired sessions take no messages
                    else:
                        try:
                            repaired = await self._await_session(
                                client,
                                session_id,
                                deadline_seconds=(_CORRUPTION_REPAIR_TIMEOUT_SECONDS),
                                ignore_structured=payload,
                            )
                            candidate = self._validate(request, repaired)
                        except DevinCloudError:
                            pass  # keep the original corrupted result
                        else:
                            if not _has_replacement_chars(candidate):
                                result = candidate
            finally:
                # Every code path out of the call — success, timeout, HTTP
                # error, cancellation — must release the cloud session; an
                # abandoned session keeps a slot in the concurrency cap.
                await self._terminate_session(client, session_id)
        return result

    async def _create_session_with_backoff(
        self, client: httpx.AsyncClient, prompt: str, settings: object
    ) -> str:
        """Create a session, retrying only transient rate limits."""

        max_attempts = int(getattr(settings, "devin_rate_limit_max_attempts", 3))
        delay = float(
            getattr(settings, "devin_rate_limit_initial_backoff_seconds", 20.0)
        )
        max_delay = float(
            getattr(settings, "devin_rate_limit_max_backoff_seconds", 120.0)
        )
        last: DevinCloudError | None = None
        quota_retried = False
        for attempt in range(1, max_attempts + 1):
            try:
                return await self._create_session(client, prompt)
            except DevinQuotaError as exc:
                # Orphaned remote sessions can hold the concurrency cap even
                # though no live caller owns them — sweep once, then retry.
                # A still-full cap means live (possibly foreign) sessions hold
                # the slots; they clear in minutes, so back off like any other
                # rate limit instead of retrying instantly.
                last = exc
                if not quota_retried:
                    quota_retried = True
                    await self._sweep_orphaned_sessions(client, force=True)
                if attempt == max_attempts:
                    break
                logger.warning(
                    "devin.quota_exhausted",
                    extra={"attempt": attempt, "backoff_seconds": delay},
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)
            except DevinRateLimitError as exc:
                last = exc
                if attempt == max_attempts:
                    break
                logger.warning(
                    "devin.rate_limited",
                    extra={"attempt": attempt, "backoff_seconds": delay},
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)
        raise last if last is not None else DevinCloudError("unreachable")

    async def _sweep_orphaned_sessions(
        self, client: httpx.AsyncClient, *, force: bool = False
    ) -> int:
        """Delete abandoned remote sessions that still hold a quota slot.

        A session in ``blocked``/``expired`` state older than
        ``_ORPHAN_SESSION_AGE_SECONDS`` cannot have a live caller — every
        extract path resolves or fails well inside that window — so reaping
        is safe. Best-effort: sweep errors are logged, never fatal.
        """

        global _last_orphan_sweep
        now = time.monotonic()
        if not force and now - _last_orphan_sweep < _SWEEP_INTERVAL_SECONDS:
            return 0
        _last_orphan_sweep = now
        try:
            response = await client.get("/v1/sessions", params={"limit": 50})
            if response.status_code != 200:
                return 0
            sessions = response.json().get("sessions", [])
        except (httpx.HTTPError, json.JSONDecodeError, AttributeError) as exc:
            logger.warning("devin.orphan_sweep_failed", extra={"error": str(exc)[:200]})
            return 0
        reaped = 0
        for session in sessions if isinstance(sessions, list) else []:
            if not isinstance(session, dict):
                continue
            if str(session.get("status_enum", "")) not in _ORPHAN_STATES:
                continue
            tags = session.get("tags") or []
            if _APP_TAG not in tags:
                continue  # not ours — other tools share this account
            if not _older_than_orphan_age(session):
                continue
            session_id = str(session.get("session_id") or "")
            if not session_id:
                continue
            with contextlib.suppress(httpx.HTTPError):
                delete = await client.delete(f"/v1/sessions/{session_id}")
                if delete.status_code < 400:
                    reaped += 1
                    logger.info(
                        "devin.orphan_session_reaped",
                        extra={"session_id": session_id},
                    )
        return reaped

    async def _create_session(self, client: httpx.AsyncClient, prompt: str) -> str:
        chunks = _chunk_prompt(prompt)
        first = chunks[0]
        if len(chunks) > 1:
            first += (
                "\n\n[The task input continues in follow-up messages. "
                f"Do not produce output until you receive {_END_OF_INPUT}.]"
            )
        # Not idempotent: retries must create a fresh session — an idempotent
        # create resurrects the previous session, which may be a terminal
        # dead-end that can never produce output.
        payload = await self._post(
            client, "/v1/sessions", {"prompt": first, "tags": [_APP_TAG]}
        )
        session_id = str(payload.get("session_id") or "")
        if not session_id:
            raise DevinCloudError("session creation returned no session_id")
        try:
            for chunk in chunks[1:]:
                await self._send_message(client, session_id, chunk)
            if len(chunks) > 1:
                await self._send_message(
                    client,
                    session_id,
                    f"{_END_OF_INPUT}. Now produce exactly one JSON object "
                    "matching the JSON schema given earlier and set the "
                    "session's structured output to it.",
                )
        except BaseException:
            # A failed follow-up message must not orphan the remote session.
            await self._terminate_session(client, session_id)
            raise
        return session_id

    async def _send_message(
        self, client: httpx.AsyncClient, session_id: str, message: str
    ) -> None:
        deadline = time.monotonic() + _MESSAGE_INITIALIZING_RETRY_SECONDS
        while True:
            try:
                await self._post(
                    client,
                    f"/v1/sessions/{session_id}/message",
                    {"message": message},
                )
                return
            except DevinCloudError as exc:
                if "still initializing" not in str(exc) or time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(_MESSAGE_INITIALIZING_DELAY_SECONDS)

    async def _terminate_session(
        self, client: httpx.AsyncClient, session_id: str
    ) -> None:
        # Blocked sessions keep a slot in the org's concurrency limit; free it.
        # Cleanup is idempotent and never masks the original failure.
        try:
            response = await client.delete(f"/v1/sessions/{session_id}")
        except httpx.HTTPError as exc:
            logger.warning(
                "devin.session_cleanup_error",
                extra={"session_id": session_id, "error": type(exc).__name__},
            )
            return
        if response.status_code >= 400:
            logger.warning(
                "devin.session_cleanup_failed",
                extra={
                    "session_id": session_id,
                    "status_code": response.status_code,
                },
            )

    async def _post(
        self, client: httpx.AsyncClient, path: str, body: dict[str, object]
    ) -> dict[str, object]:
        try:
            response = await client.post(path, json=body)
        except httpx.HTTPError as exc:
            raise DevinCloudError(type(exc).__name__) from exc
        if response.status_code == 401:
            raise DevinCloudError("EMTEDAD_DEVIN_API_KEY wurde abgelehnt (401)")
        if response.status_code == 403 and "out_of_quota" in response.text:
            raise DevinQuotaError(
                "Devin-Kontingent erschöpft (out_of_quota). "
                "Billing in Devin prüfen oder später erneut versuchen."
            )
        if response.status_code == 429:
            if "sessions running" in response.text or "parallel" in response.text:
                # Free-tier parallel-session cap: a hard concurrency quota,
                # not transient throttling — surface it, don't hammer it.
                raise DevinQuotaError(
                    "PROVIDER_QUOTA_EXHAUSTED: Devin-Limit für parallele "
                    "Sessions erreicht: " + response.text[:300]
                )
            raise DevinRateLimitError("Devin rate limit (429): " + response.text[:300])
        if response.status_code != 200:
            raise DevinCloudError(
                f"request failed: {response.status_code} {response.text[-500:]}"
            )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise DevinCloudError("response is not JSON") from exc
        return payload if isinstance(payload, dict) else {}

    async def _await_session(
        self,
        client: httpx.AsyncClient,
        session_id: str,
        deadline_seconds: float,
        *,
        ignore_structured: object | None = None,
    ) -> object:
        deadline = time.monotonic() + deadline_seconds
        empty_since: float | None = None
        nudged = ignore_structured is not None  # already nudged/repaired
        while time.monotonic() < deadline:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            try:
                response = await client.get(f"/v1/sessions/{session_id}")
            except httpx.HTTPError:
                continue  # transient poll failure; retry until deadline
            if response.status_code != 200:
                continue
            detail = response.json()
            status = str(detail.get("status_enum", ""))
            structured = detail.get("structured_output")
            if status in _TERMINAL_DONE_STATES:
                # ``ignore_structured`` suppresses the stale output a
                # blocked session still reports before it produces the
                # repaired JSON we asked for.
                if structured and structured != ignore_structured:
                    return structured
                recovered = _recover_from_messages(detail.get("messages", []))
                if recovered is not None and recovered != ignore_structured:
                    return recovered
                # A "blocked" session is awaiting input — nudge it once so it
                # resumes and produces the output; "finished" cannot be
                # messaged, so only the grace window applies there.
                if status == "blocked" and not nudged:
                    nudged = True
                    try:
                        await self._send_message(client, session_id, _NUDGE_MESSAGE)
                        continue
                    except DevinCloudError:
                        pass
                if empty_since is None:
                    empty_since = time.monotonic()
                if time.monotonic() - empty_since >= _EMPTY_OUTPUT_GRACE_SECONDS:
                    raise DevinCloudError("session finished without structured output")
                continue  # final message may lag the blocked status
            if status in _TERMINAL_FAILURE_STATES:
                raise DevinCloudError(f"session ended in state: {status}")
        raise DevinCloudError(f"session did not finish within {deadline_seconds}s")

    @staticmethod
    def _validate(request: StructuredExtractionRequest, payload: object) -> BaseModel:
        if not isinstance(payload, dict):
            raise DevinCloudError("structured output is not a JSON object")
        try:
            return request.output_model.model_validate(payload)
        except ValidationError as exc:
            raise DevinCloudError(
                f"invalid structured output: {type(exc).__name__}"
            ) from exc


def _has_replacement_chars(result: BaseModel) -> bool:
    """U+FFFD is never intentional output — it marks corrupted decoding."""

    return "�" in result.model_dump_json()


def _older_than_orphan_age(session: dict[object, object]) -> bool:
    """True when the session's last update predates the orphan window."""

    raw = session.get("updated_at") or session.get("created_at")
    if not isinstance(raw, str) or not raw:
        return False
    try:
        updated = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(UTC) - updated).total_seconds() > (_ORPHAN_SESSION_AGE_SECONDS)


def _chunk_prompt(prompt: str) -> list[str]:
    """Split a prompt into chunks that fit the session-message size limit."""

    if len(prompt) <= _PROMPT_CHAR_LIMIT:
        return [prompt]
    return [
        prompt[index : index + _PROMPT_CHAR_LIMIT]
        for index in range(0, len(prompt), _PROMPT_CHAR_LIMIT)
    ]


def _recover_from_messages(messages: object) -> dict[str, object] | None:
    """Scan session messages newest-first for an embedded JSON object.

    Devin may append trailers after the JSON (e.g. ``ATTACHMENT:{...}``), so
    decode the first complete object via ``raw_decode`` instead of relying on
    the last ``}`` in the text.
    """

    if not isinstance(messages, list):
        return None
    decoder = json.JSONDecoder()
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        text = message.get("message", "")
        if not isinstance(text, str):
            continue
        index = text.find("{")
        while index != -1:
            try:
                parsed, _end = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                index = text.find("{", index + 1)
                continue
            if isinstance(parsed, dict):
                return parsed
            index = text.find("{", _end)
    return None
