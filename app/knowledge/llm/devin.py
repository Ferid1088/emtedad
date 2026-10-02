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
import time

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.knowledge.llm.base import StructuredExtractionRequest

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


class DevinCloudError(RuntimeError):
    """Raised for auth, HTTP, timeout, JSON, or schema failures."""


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
        timeout = max(request.timeout_seconds, _MINIMUM_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={
                "Authorization": (f"Bearer {settings.devin_api_key.get_secret_value()}")
            },
            timeout=60,
            transport=self._transport,
        ) as client:
            session_id = await self._create_session(client, prompt)
            try:
                payload = await self._await_session(
                    client, session_id, deadline_seconds=timeout
                )
            finally:
                await self._terminate_session(client, session_id)
        return self._validate(request, payload)

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
        payload = await self._post(client, "/v1/sessions", {"prompt": first})
        session_id = str(payload.get("session_id") or "")
        if not session_id:
            raise DevinCloudError("session creation returned no session_id")
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
        with contextlib.suppress(httpx.HTTPError):
            await client.delete(f"/v1/sessions/{session_id}")

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
            raise DevinCloudError(
                "Devin-Kontingent erschöpft (out_of_quota). "
                "Billing in Devin prüfen oder später erneut versuchen."
            )
        if response.status_code == 429:
            raise DevinCloudError(
                "Devin-Limit für parallele Sessions erreicht: " + response.text[:300]
            )
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
    ) -> object:
        deadline = time.monotonic() + deadline_seconds
        empty_since: float | None = None
        nudged = False
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
                if structured:
                    return structured
                recovered = _recover_from_messages(detail.get("messages", []))
                if recovered is not None:
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
