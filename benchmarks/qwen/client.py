"""HISTORICAL benchmark-only OpenRouter chat client for the Qwen evaluation.

Retired 2026-10-05 with the APIMaster migration — preserved for artifact
provenance (``docs/audits/qwen_benchmark/``), not part of active runtime.

This is deliberately *not* wired into production routing. It implements
``LLMProvider.extract`` so ``ScriptService`` and the critic loop can run
against Qwen with the exact production payloads, and a plain ``chat``
method for the short-form benchmark cases. Every call appends one JSON
line to ``docs/audits/qwen_benchmark/telemetry.jsonl`` and stores the raw
response under ``docs/audits/qwen_benchmark/raw/``.

The API key is read from the environment or ``.env`` (case-insensitive
``*OPENROUTER_API_KEY``) and is never logged, stored, or printed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.knowledge.llm.base import StructuredExtractionRequest

MODEL = "qwen/qwen3-235b-a22b-2507"
BASE_URL = "https://openrouter.ai/api/v1"
ARTIFACT_DIR = Path("docs/audits/qwen_benchmark")
RAW_DIR = ARTIFACT_DIR / "raw"
TELEMETRY_PATH = ARTIFACT_DIR / "telemetry.jsonl"

_RATE_LIMIT_MAX_ATTEMPTS = 3
_RATE_LIMIT_BACKOFF_SECONDS = 15.0


class OpenRouterError(RuntimeError):
    """Transport, auth, schema, or parse failure — surfaced truthfully."""


class OpenRouterRateLimitError(OpenRouterError):
    """HTTP 429 — bounded retry applies."""


def load_api_key() -> str | None:
    """Return the OpenRouter key from env or .env; never logs the value."""

    for name, value in os.environ.items():
        if name.upper().endswith("OPENROUTER_API_KEY") and value:
            return value
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, _, value = stripped.partition("=")
            if name.strip().upper().endswith("OPENROUTER_API_KEY"):
                return value.strip().strip('"').strip("'") or None
    return None


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class CallRecord:
    """One benchmark call's telemetry — appended to telemetry.jsonl."""

    def __init__(self, task: str, model: str, case_id: str = "") -> None:
        self.task = task
        self.model = model
        self.case_id = case_id
        self.started = time.monotonic()
        self.timestamp = datetime.now(UTC).isoformat()

    def finish(
        self,
        *,
        ok: bool,
        raw: dict[str, Any] | None = None,
        error: str = "",
        status_code: int | None = None,
    ) -> dict[str, Any]:
        usage = (raw or {}).get("usage") or {}
        record = {
            "timestamp": self.timestamp,
            "task": self.task,
            "case_id": self.case_id,
            "model_requested": self.model,
            "model_returned": (raw or {}).get("model"),
            "provider": (raw or {}).get("provider"),
            "latency_ms": int((time.monotonic() - self.started) * 1000),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "cost": usage.get("cost"),
            "ok": ok,
            "status_code": status_code,
            "error": error[:300],
        }
        TELEMETRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with TELEMETRY_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record


def save_raw(name: str, payload: dict[str, Any]) -> str:
    """Persist a raw response artifact; returns its sha256."""

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=1)
    (RAW_DIR / f"{name}.json").write_text(body, encoding="utf-8")
    return _sha256(body)


class OpenRouterBenchmarkClient:
    """Minimal chat-completions client — benchmark use only."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = MODEL,
        timeout_seconds: float = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else load_api_key()
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    @property
    def has_key(self) -> bool:
        return bool(self._api_key)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        task: str = "chat",
        case_id: str = "",
        model: str | None = None,
        response_format: dict[str, Any] | None = None,
        max_tokens: int = 8192,
        temperature: float | None = None,
        save_name: str = "",
    ) -> tuple[str, dict[str, Any]]:
        """One bounded chat call. Returns (content, telemetry record)."""

        if not self._api_key:
            raise OpenRouterError("OpenRouter API key is not configured")
        model = model or self.model
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "usage": {"include": True},
        }
        if response_format is not None:
            body["response_format"] = response_format
        if temperature is not None:
            body["temperature"] = temperature

        record = CallRecord(task, model, case_id)
        last_error: OpenRouterError | None = None
        for attempt in range(1, _RATE_LIMIT_MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(
                    base_url=BASE_URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=httpx.Timeout(self.timeout_seconds),
                    transport=self._transport,
                ) as client:
                    response = await client.post("/chat/completions", json=body)
            except httpx.HTTPError as exc:
                last_error = OpenRouterError(f"transport error: {type(exc).__name__}")
                if attempt == _RATE_LIMIT_MAX_ATTEMPTS:
                    record.finish(ok=False, error=str(last_error))
                    raise last_error from exc
                await asyncio.sleep(_RATE_LIMIT_BACKOFF_SECONDS)
                continue
            if response.status_code == 429:
                last_error = OpenRouterRateLimitError(
                    f"rate limited (429): {response.text[:200]}"
                )
                if attempt == _RATE_LIMIT_MAX_ATTEMPTS:
                    record.finish(ok=False, error=str(last_error), status_code=429)
                    raise last_error
                await asyncio.sleep(_RATE_LIMIT_BACKOFF_SECONDS * attempt)
                continue
            if response.status_code == 401:
                error = OpenRouterError("API key rejected (401)")
                record.finish(ok=False, error=str(error), status_code=401)
                raise error
            if response.status_code >= 400:
                error = OpenRouterError(
                    f"request failed: {response.status_code} {response.text[:300]}"
                )
                record.finish(
                    ok=False, error=str(error), status_code=response.status_code
                )
                raise error
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                error = OpenRouterError("response is not JSON")
                record.finish(ok=False, error=str(error))
                raise error from exc
            digest = save_raw(save_name or f"{task}-{case_id or 'x'}", payload)
            telemetry = record.finish(ok=True, raw=payload, status_code=200)
            telemetry["raw_sha256"] = digest
            telemetry["attempts"] = attempt
            choices = payload.get("choices") or []
            message = (choices[0].get("message") or {}) if choices else {}
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                error = OpenRouterError("empty or missing message content")
                raise error
            return content, telemetry
        raise last_error or OpenRouterError("unreachable")


class QwenBenchmarkProvider:
    """``LLMProvider`` adapter so production pipelines can run on Qwen.

    Used by benchmark scripts only — passed explicitly, never resolved
    through ``resolve_llm_provider()``, so production routing is untouched.
    """

    name = "openrouter-qwen-benchmark"

    def __init__(self, client: OpenRouterBenchmarkClient) -> None:
        self.client = client

    async def extract(self, request: StructuredExtractionRequest) -> BaseModel:
        schema = request.output_model.model_json_schema()
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": request.output_model.__name__,
                "strict": True,
                "schema": schema,
            },
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "Produce exactly one JSON object matching the JSON schema "
                    "supplied via response_format. No markdown fences, no "
                    "commentary.\n\n"
                    f"Task: {request.task}\n"
                    f"Prompt version: {request.prompt_version}\n"
                    f"Instructions: {request.instructions}"
                ),
            },
            {"role": "user", "content": request.input_text},
        ]
        content, telemetry = await self.client.chat(
            messages,
            task=request.task,
            case_id=request.prompt_version,
            response_format=response_format,
            max_tokens=32768,
        )
        try:
            return request.output_model.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError) as exc:
            # One bounded in-conversation schema repair — mirrors the Devin
            # provider's corruption-repair nudge; counted as a repair call
            # in telemetry, never a silent fallback.
            messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your JSON did not validate against the schema: "
                        f"{type(exc).__name__}. Return exactly one JSON "
                        "object with the exact field names required by the "
                        "response_format schema. No commentary."
                    ),
                }
            )
            repaired, _tel2 = await self.client.chat(
                messages,
                task=request.task + "_schema_repair",
                case_id=request.prompt_version,
                response_format=response_format,
                max_tokens=32768,
            )
            try:
                return request.output_model.model_validate(json.loads(repaired))
            except (json.JSONDecodeError, ValidationError) as exc2:
                raise OpenRouterError(
                    f"invalid structured output after repair: {type(exc2).__name__}"
                ) from exc2
