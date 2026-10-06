"""Production APIMaster structured-extraction provider.

Implements the shared ``LLMProvider`` contract over the APIMaster
OpenAI-compatible chat-completions API (``https://apimaster.ai/v1``):
schema-aware ``response_format``, one bounded schema-repair turn,
classified errors, bounded retries on transient failures, provider-reported
usage and cost, and a telemetry recorder hook. The API key never appears
in errors, logs, or telemetry — messages carry classification only.

Live-verified wire facts (2026-10-05, ``GET /v1/models`` + probes):

- ``supported_endpoint_types``: ``openai`` for all four production models;
  ``openai-response`` only on ``qwen3.8-flash``. ``gpt-6.1-sol`` answers
  ``POST /v1/responses`` despite not advertising it — verified live —
  and that route omits the ~4.4k injected prompt prefix chat
  completions carries. Production still uses chat completions: the
  Responses route is undocumented gateway behaviour, not a contract.
- ``POST /v1/batches`` does not exist (404) — APIMaster has **no batch
  API**; premium work runs on the standard route.
- ``gemini-3.8-flash`` honours ``response_format={"type": "json_object"}``
  but ignores ``json_schema``; ``qwen3.8-flash``, ``gpt-6.1-sol`` and
  ``gpt-6-astra`` accept strict ``json_schema``.
- Unknown models return ``503`` with ``error.code == "model_not_found"``
  (a ``new_api_error``) — classified non-retryable despite the 5xx status.
- ``usage.cost`` is returned for ``qwen3.8-flash``; ``gpt-6.1-sol`` /
  ``gpt-6-astra`` / ``gemini-3.8-flash`` omit it (NULL, never estimated).
  ``cached_tokens`` appears under ``prompt_tokens_details``.
- No route/channel/fingerprint fields are exposed: the only request
  identity is the ``x-request-id`` / body ``id``.

This module is the production boundary; the web-research provider in
``app/web_research/providers.py`` is a separate search contract.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from app.knowledge.llm.base import StructuredExtractionRequest


class APIMasterError(RuntimeError):
    """Base class for provider failures; message is always secret-free."""

    def __init__(self, message: str, *, error_kind: str = "provider") -> None:
        super().__init__(message)
        self.error_kind = error_kind


class APIMasterAuthError(APIMasterError):
    def __init__(self) -> None:
        super().__init__(
            "APIMaster authentication failed (401/403)",
            error_kind="auth",
        )


class APIMasterModelNotFoundError(APIMasterError):
    def __init__(self, model: str) -> None:
        super().__init__(
            f"APIMaster model not available: {model}",
            error_kind="model_not_found",
        )


class APIMasterRateLimitError(APIMasterError):
    def __init__(self) -> None:
        super().__init__("APIMaster rate limited (429)", error_kind="rate_limit")


class APIMasterQuotaError(APIMasterError):
    def __init__(self) -> None:
        super().__init__("APIMaster quota/credit exhausted", error_kind="quota")


class APIMasterTimeoutError(APIMasterError):
    def __init__(self) -> None:
        super().__init__("APIMaster request timed out", error_kind="timeout")


class APIMasterTransportError(APIMasterError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            f"APIMaster transport failure: {detail}", error_kind="transport"
        )


class APIMasterMalformedResponseError(APIMasterError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            f"APIMaster malformed response: {detail}", error_kind="malformed"
        )


class APIMasterSchemaError(APIMasterError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            f"APIMaster schema validation failed: {detail}",
            error_kind="schema",
        )


class APIMasterUpstreamError(APIMasterError):
    def __init__(self, status: int) -> None:
        super().__init__(
            f"APIMaster upstream/provider failure ({status})",
            error_kind="upstream",
        )


class APIMasterMissingKeyError(APIMasterError):
    def __init__(self) -> None:
        super().__init__("APIMaster API key is not configured", error_kind="auth")


@dataclass(slots=True)
class CallTelemetry:
    """Provider-reported truth for one completed or failed call."""

    provider: str = "apimaster"
    model: str = ""
    upstream_provider: str | None = None
    task: str = ""
    agent_role: str = ""
    prompt_version: str = ""
    request_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None
    # Only populated when the provider reports a real cost — never an
    # estimate. ``None`` means the provider did not report one.
    cost_usd: float | None = None
    latency_ms: int = 0
    retries: int = 0
    schema_repairs: int = 0
    ok: bool = False
    error_kind: str | None = None
    # Protocol truth (§38): what was requested vs what the provider
    # actually spoke. A Responses→Chat fallback is recorded, never hidden.
    requested_protocol: str = "chat"
    actual_protocol: str = "chat"
    fallback_used: bool = False
    fallback_reason: str | None = None


class TelemetryRecorder(Protocol):
    """Sink for call telemetry; services decide where events persist."""

    async def record(self, event: CallTelemetry) -> None: ...


class NullRecorder:
    async def record(self, event: CallTelemetry) -> None:
        del event


@dataclass(slots=True)
class APIMasterConfig:
    api_key: str | None
    base_url: str = "https://apimaster.ai/v1"
    model: str = ""
    timeout_seconds: float = 300.0
    max_retries: int = 2
    # Models whose OpenAI-compatible endpoint ignores ``json_schema`` and
    # requires ``json_object`` mode instead (verified live). The schema is
    # then embedded in the system prompt and enforced by Pydantic
    # validation + the bounded repair turn.
    json_object_models: frozenset[str] = frozenset({"gemini-3.8-flash"})
    # "chat" (default, documented production route) or "responses"
    # (undocumented POST /v1/responses — certified per §34–39 before
    # production use; failures fall back to chat once, logged).
    protocol: str = "chat"
    # Whether client timeouts and gateway timeouts (504/524) are retried.
    # Off for premium roles by default: a timed-out premium generation may
    # still run (and bill) upstream, so a blind retry can pay twice.
    retry_timeouts: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


def bare_model_id(model: str) -> str:
    """Model ID without the provider namespace (``openai/gpt-6.1-sol`` →
    ``gpt-6.1-sol``). Capability tables and the price catalog are keyed by
    bare IDs, while routing uses namespaced IDs because only those return
    provider-reported cost."""

    return model.rsplit("/", 1)[-1]


# Retry decisions follow the *classified* error kind, not the bare status:
# APIMaster reports ``model_not_found`` as a 503, which must not retry.
_RETRYABLE_KINDS = frozenset({"rate_limit", "upstream", "timeout", "transport"})


def _error_detail(body: object) -> str:
    """Provider error text, bounded — never includes request payload."""

    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    if not isinstance(error, dict):
        return ""
    message = error.get("message")
    if not isinstance(message, str):
        return ""
    return message.replace("\n", " ")[:300]


def _error_code(body: object) -> str:
    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    if not isinstance(error, dict):
        return ""
    code = error.get("code")
    return str(code) if isinstance(code, str) else ""


def _classify_status(status: int, model: str, body: object = None) -> APIMasterError:
    detail = _error_detail(body)
    code = _error_code(body)
    suffix = f": {detail}" if detail else ""
    lowered = detail.lower()
    if status in (401, 403):
        return APIMasterAuthError()
    if status == 404 or code == "model_not_found":
        # APIMaster returns model-miss as 503 + code, not 404.
        return APIMasterModelNotFoundError(model)
    if status == 402 or "quota" in lowered or "insufficient" in lowered:
        return APIMasterQuotaError()
    if status == 429:
        return APIMasterRateLimitError()
    if status in (504, 524):
        # Gateway/edge timeout: the generation outlived the proxy window.
        return APIMasterTimeoutError()
    if status >= 500:
        return APIMasterUpstreamError(status)
    return APIMasterError(
        f"APIMaster request rejected ({status}){suffix}",
        error_kind="request",
    )


def _strictify(node: object) -> None:
    """Rewrite a Pydantic JSON schema in place for strict tool/response mode.

    Providers implementing OpenAI-compatible strict structured output
    require every object to declare ``additionalProperties: false`` and to
    list *all* properties in ``required``. Pydantic omits defaulted fields
    from ``required`` — they are still optional for validation since the
    model supplies defaults when the field is absent.
    """

    if isinstance(node, dict):
        if node.get("type") == "object" and isinstance(node.get("properties"), dict):
            node["additionalProperties"] = False
            node["required"] = sorted(node["properties"].keys())
        for value in node.values():
            _strictify(value)
    elif isinstance(node, list):
        for item in node:
            _strictify(item)


def json_response_format(
    model: str,
    output_model: type[BaseModel],
    *,
    json_object_models: frozenset[str] = frozenset({"gemini-3.8-flash"}),
) -> dict[str, Any]:
    """``response_format`` honouring the model's live-verified capability.

    Models that accept strict ``json_schema`` get it; models verified to
    ignore it (Gemini Flash on APIMaster) get ``json_object`` mode — the
    schema is then carried in the prompt and enforced by validation.
    """

    if model in json_object_models or bare_model_id(model) in json_object_models:
        return {"type": "json_object"}
    schema = output_model.model_json_schema()
    _strictify(schema)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": output_model.__name__,
            "strict": True,
            "schema": schema,
        },
    }


def _responses_format(response_format: dict[str, Any]) -> dict[str, Any]:
    """Map a chat-completions ``response_format`` to Responses ``text.format``.

    The Responses API flattens the ``json_schema`` wrapper: name/schema/
    strict are top-level fields, not nested under a ``json_schema`` key.
    """

    if response_format.get("type") == "json_schema":
        js = response_format.get("json_schema") or {}
        return {
            "type": "json_schema",
            "name": js.get("name", "output"),
            "schema": js.get("schema", {}),
            "strict": js.get("strict", True),
        }
    return response_format


def _backoff_seconds(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None and retry_after > 0:
        return min(retry_after, 120.0)
    return min(5.0 * attempt, 30.0)


class APIMasterProvider:
    """``LLMProvider`` over APIMaster chat completions."""

    name = "apimaster"

    def __init__(
        self,
        config: APIMasterConfig,
        *,
        recorder: TelemetryRecorder | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        agent_role: str = "",
    ) -> None:
        self.config = config
        self.recorder = recorder or NullRecorder()
        self._transport = transport
        self.agent_role = agent_role

    async def extract(self, request: StructuredExtractionRequest) -> BaseModel:
        telemetry = CallTelemetry(
            model=self.config.model or request.model,
            task=request.task,
            agent_role=self.agent_role,
            prompt_version=request.prompt_version,
        )
        telemetry.requested_protocol = self.config.protocol
        started = time.monotonic()
        try:
            result = await self._extract(request, telemetry)
            telemetry.ok = True
            return result
        except APIMasterError as exc:
            telemetry.error_kind = exc.error_kind
            raise
        finally:
            telemetry.latency_ms = int((time.monotonic() - started) * 1000)
            await self.recorder.record(telemetry)

    async def _extract(
        self, request: StructuredExtractionRequest, telemetry: CallTelemetry
    ) -> BaseModel:
        if not self.config.api_key:
            raise APIMasterMissingKeyError()
        model = self.config.model or request.model
        if not model or model == "configured-default":
            raise APIMasterError(
                "No model resolved for APIMaster call", error_kind="request"
            )
        response_format = json_response_format(
            model,
            request.output_model,
            json_object_models=self.config.json_object_models,
        )
        schema_hint = ""
        if response_format.get("type") == "json_object":
            schema = request.output_model.model_json_schema()
            schema_hint = (
                "\n\nRequired JSON schema (return fields exactly):\n"
                f"{json.dumps(schema, ensure_ascii=False)}"
            )
        instructions = (
            "Produce exactly one JSON object matching the required "
            "schema. No markdown fences, no commentary.\n\n"
            f"Task: {request.task}\n"
            f"Prompt version: {request.prompt_version}\n"
            f"Instructions: {request.instructions}"
            f"{schema_hint}"
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": request.input_text},
        ]
        if self.config.protocol == "responses":
            try:
                content = await self._responses(
                    model=model,
                    instructions=instructions,
                    input_text=request.input_text,
                    response_format=response_format,
                    timeout_seconds=request.timeout_seconds,
                    telemetry=telemetry,
                )
                telemetry.actual_protocol = "responses"
            except APIMasterError as exc:
                # Explicit same-model protocol fallback (§37–38) — one
                # logged chat retry, never a silent channel switch.
                telemetry.fallback_used = True
                telemetry.fallback_reason = exc.error_kind
                telemetry.actual_protocol = "chat"
                content = await self._chat(
                    messages,
                    model=model,
                    response_format=response_format,
                    timeout_seconds=request.timeout_seconds,
                    telemetry=telemetry,
                )
        else:
            telemetry.actual_protocol = "chat"
            content = await self._chat(
                messages,
                model=model,
                response_format=response_format,
                timeout_seconds=request.timeout_seconds,
                telemetry=telemetry,
            )
        try:
            return request.output_model.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError) as exc:
            telemetry.schema_repairs += 1
            repaired = await self._repair(
                messages,
                content,
                exc,
                model=model,
                response_format=response_format,
                timeout_seconds=request.timeout_seconds,
                telemetry=telemetry,
            )
            try:
                return request.output_model.model_validate(json.loads(repaired))
            except (json.JSONDecodeError, ValidationError) as exc2:
                raise APIMasterSchemaError(
                    f"{type(exc2).__name__} after one repair attempt"
                ) from exc2

    async def _repair(
        self,
        messages: list[dict[str, Any]],
        bad_content: str,
        error: Exception,
        *,
        model: str,
        response_format: dict[str, Any],
        timeout_seconds: int,
        telemetry: CallTelemetry,
    ) -> str:
        """One bounded in-conversation repair; never a silent fallback."""

        repair_messages = [
            *messages,
            {"role": "assistant", "content": bad_content},
            {
                "role": "user",
                "content": (
                    "Your JSON did not validate against the schema: "
                    f"{type(error).__name__}. Return exactly one JSON object "
                    "matching the required schema. No commentary."
                ),
            },
        ]
        return await self._chat(
            repair_messages,
            model=model,
            response_format=response_format,
            timeout_seconds=timeout_seconds,
            telemetry=telemetry,
        )

    async def _chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        response_format: dict[str, Any] | None,
        timeout_seconds: int,
        telemetry: CallTelemetry,
    ) -> str:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "usage": {"include": True},
        }
        if response_format is not None:
            body["response_format"] = response_format
        payload, request_id = await self._post(
            "/chat/completions",
            body,
            model=model,
            timeout_seconds=timeout_seconds,
            telemetry=telemetry,
        )
        return self._parse_chat(payload, request_id, telemetry)

    async def _responses(
        self,
        *,
        model: str,
        instructions: str,
        input_text: str,
        response_format: dict[str, Any] | None,
        timeout_seconds: int,
        telemetry: CallTelemetry,
    ) -> str:
        """Undocumented ``POST /v1/responses`` — certified per §34–39.

        The Responses route avoids the ~4.4k injected prompt prefix chat
        completions carries. Body maps chat fields onto the Responses
        shape: ``instructions`` + ``input`` + ``text.format``.
        """

        body: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": input_text,
        }
        if response_format is not None:
            body["text"] = {"format": _responses_format(response_format)}
        payload, request_id = await self._post(
            "/responses",
            body,
            model=model,
            timeout_seconds=timeout_seconds,
            telemetry=telemetry,
        )
        return self._parse_responses(payload, request_id, telemetry)

    async def _post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        model: str,
        timeout_seconds: int,
        telemetry: CallTelemetry,
    ) -> tuple[dict[str, Any], str | None]:
        """One endpoint POST with the shared retry/classify machinery."""

        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        attempts = max(1, self.config.max_retries + 1)
        last_error: APIMasterError | None = None
        for attempt in range(1, attempts + 1):
            try:
                async with httpx.AsyncClient(
                    base_url=self.config.base_url.rstrip("/"),
                    headers=headers,
                    timeout=httpx.Timeout(
                        timeout_seconds or self.config.timeout_seconds
                    ),
                    transport=self._transport,
                ) as client:
                    response = await client.post(path, json=body)
            except httpx.TimeoutException as exc:
                last_error = APIMasterTimeoutError()
                if attempt == attempts or not self.config.retry_timeouts:
                    raise last_error from exc
                telemetry.retries += 1
                await asyncio.sleep(_backoff_seconds(attempt, None))
                continue
            except httpx.HTTPError as exc:
                last_error = APIMasterTransportError(type(exc).__name__)
                if attempt == attempts:
                    raise last_error from exc
                telemetry.retries += 1
                await asyncio.sleep(_backoff_seconds(attempt, None))
                continue
            if response.status_code == 200:
                try:
                    payload = response.json()
                except json.JSONDecodeError as exc:
                    raise APIMasterMalformedResponseError("body is not JSON") from exc
                if not isinstance(payload, dict):
                    raise APIMasterMalformedResponseError("body is not an object")
                return payload, response.headers.get("x-request-id")
            try:
                error_body: object = response.json()
            except ValueError:
                error_body = None
            error = _classify_status(response.status_code, model, error_body)
            retry_after: float | None = None
            header = response.headers.get("retry-after")
            if header and header.replace(".", "", 1).isdigit():
                retry_after = float(header)
            retryable = error.error_kind in _RETRYABLE_KINDS and (
                error.error_kind != "timeout" or self.config.retry_timeouts
            )
            if retryable and attempt < attempts:
                telemetry.retries += 1
                last_error = error
                await asyncio.sleep(_backoff_seconds(attempt, retry_after))
                continue
            raise error
        raise last_error or APIMasterError(
            "unreachable retry state", error_kind="provider"
        )

    @staticmethod
    def _parse_chat(
        payload: dict[str, Any], request_id: str | None, telemetry: CallTelemetry
    ) -> str:
        telemetry.request_id = request_id or (
            str(payload.get("id")) if payload.get("id") else None
        )
        upstream = payload.get("provider")
        telemetry.upstream_provider = str(upstream) if upstream else None
        usage = payload.get("usage") or {}
        if isinstance(usage, dict):
            telemetry.prompt_tokens = _opt_int(usage.get("prompt_tokens"))
            telemetry.completion_tokens = _opt_int(usage.get("completion_tokens"))
            telemetry.cost_usd = _opt_float(usage.get("cost"))
            prompt_details = usage.get("prompt_tokens_details") or {}
            if isinstance(prompt_details, dict):
                telemetry.cached_tokens = _opt_int(prompt_details.get("cached_tokens"))
            completion_details = usage.get("completion_tokens_details") or {}
            if isinstance(completion_details, dict):
                telemetry.reasoning_tokens = _opt_int(
                    completion_details.get("reasoning_tokens")
                )
        choices = payload.get("choices") or []
        message = (choices[0].get("message") or {}) if choices else {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise APIMasterMalformedResponseError("empty message content")
        return content

    @staticmethod
    def _parse_responses(
        payload: dict[str, Any], request_id: str | None, telemetry: CallTelemetry
    ) -> str:
        telemetry.request_id = request_id or (
            str(payload.get("id")) if payload.get("id") else None
        )
        upstream = payload.get("provider")
        telemetry.upstream_provider = str(upstream) if upstream else None
        usage = payload.get("usage") or {}
        if isinstance(usage, dict):
            # Responses API names: input_tokens / output_tokens.
            telemetry.prompt_tokens = _opt_int(usage.get("input_tokens"))
            telemetry.completion_tokens = _opt_int(usage.get("output_tokens"))
            telemetry.cost_usd = _opt_float(usage.get("cost"))
            input_details = usage.get("input_tokens_details") or {}
            if isinstance(input_details, dict):
                telemetry.cached_tokens = _opt_int(input_details.get("cached_tokens"))
            output_details = usage.get("output_tokens_details") or {}
            if isinstance(output_details, dict):
                telemetry.reasoning_tokens = _opt_int(
                    output_details.get("reasoning_tokens")
                )
        text = payload.get("output_text")
        if isinstance(text, str) and text.strip():
            return text
        # Fallback: walk output items for the message's output_text part.
        chunks: list[str] = []
        for item in payload.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    chunk = part.get("text")
                    if isinstance(chunk, str):
                        chunks.append(chunk)
        content = "".join(chunks)
        if not content.strip():
            raise APIMasterMalformedResponseError("empty responses output")
        return content


def _opt_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _opt_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
