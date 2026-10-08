"""Contract tests for the production APIMaster provider."""

import json

import httpx
import pytest
from pydantic import BaseModel

import app.knowledge.llm.apimaster as apimaster_module
from app.knowledge.llm.apimaster import (
    APIMasterAuthError,
    APIMasterConfig,
    APIMasterMissingKeyError,
    APIMasterModelNotFoundError,
    APIMasterProvider,
    APIMasterSchemaError,
    CallTelemetry,
    json_response_format,
)
from app.knowledge.llm.base import StructuredExtractionRequest


class _Output(BaseModel):
    status: str


class _Collector:
    def __init__(self) -> None:
        self.events: list[CallTelemetry] = []

    async def record(self, event: CallTelemetry) -> None:
        self.events.append(event)


def _request() -> StructuredExtractionRequest:
    return StructuredExtractionRequest(
        task="test",
        prompt_version="v1",
        model="configured-default",
        instructions="extract",
        input_text="text",
        output_model=_Output,
        timeout_seconds=5,
    )


def _config(**updates: object) -> APIMasterConfig:
    kwargs: dict[str, object] = {
        "api_key": "sk-apimaster-unit-test-key",
        "model": "gpt-6.1-sol",
        "max_retries": 2,
    }
    kwargs.update(updates)
    return APIMasterConfig(**kwargs)  # type: ignore[arg-type]


def _completion(content: object, **usage_overrides: object) -> dict[str, object]:
    usage: dict[str, object] = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost": 0.0001,
        "prompt_tokens_details": {"cached_tokens": 4},
        "completion_tokens_details": {"reasoning_tokens": 2},
    }
    usage.update(usage_overrides)
    return {
        "id": "gen-1",
        "model": "gpt-6.1-sol",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": usage,
    }


def _provider(
    handler, monkeypatch: pytest.MonkeyPatch, collector: _Collector | None = None
) -> tuple[APIMasterProvider, _Collector]:
    monkeypatch.setattr(apimaster_module, "_backoff_seconds", lambda *a: 0.0)
    sink = collector or _Collector()
    return (
        APIMasterProvider(
            _config(),
            recorder=sink,
            transport=httpx.MockTransport(handler),
            agent_role="unit_role",
        ),
        sink,
    )


@pytest.mark.asyncio
async def test_extract_parses_json_and_records_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, sink = _provider(
        lambda request: httpx.Response(200, json=_completion('{"status": "ok"}')),
        monkeypatch,
    )
    result = await provider.extract(_request())
    assert result == _Output(status="ok")
    event = sink.events[0]
    assert event.ok and event.request_id == "gen-1"
    assert event.prompt_tokens == 10 and event.completion_tokens == 5
    assert event.cached_tokens == 4 and event.reasoning_tokens == 2
    assert event.cost_usd == pytest.approx(0.0001)
    assert event.agent_role == "unit_role"


@pytest.mark.asyncio
async def test_request_id_falls_back_to_response_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, sink = _provider(
        lambda request: httpx.Response(
            200,
            json=_completion('{"status": "ok"}'),
            headers={"x-request-id": "req-abc"},
        ),
        monkeypatch,
    )
    await provider.extract(_request())
    assert sink.events[0].request_id == "req-abc"


@pytest.mark.asyncio
async def test_extract_retries_on_429_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"error": {"message": "slow down"}})
        return httpx.Response(200, json=_completion('{"status": "ok"}'))

    provider, sink = _provider(handler, monkeypatch)
    result = await provider.extract(_request())
    assert result.status == "ok"
    assert calls == 2 and sink.events[0].retries == 1


@pytest.mark.asyncio
async def test_extract_gives_up_after_bounded_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, sink = _provider(
        lambda request: httpx.Response(503, json={"error": {"message": "upstream"}}),
        monkeypatch,
    )
    with pytest.raises(Exception) as excinfo:
        await provider.extract(_request())
    assert getattr(excinfo.value, "error_kind", None) == "upstream"
    assert sink.events[0].retries == 2 and not sink.events[0].ok


@pytest.mark.asyncio
async def test_model_not_found_503_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """APIMaster reports model misses as 503 with a typed error code."""

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            503,
            json={
                "error": {
                    "code": "model_not_found",
                    "message": "no non-exclusive channel available",
                    "type": "new_api_error",
                }
            },
        )

    provider, _ = _provider(handler, monkeypatch)
    with pytest.raises(APIMasterModelNotFoundError):
        await provider.extract(_request())
    assert calls == 1


@pytest.mark.asyncio
async def test_extract_repairs_schema_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = '{"wrong": true}' if calls == 1 else '{"status": "fixed"}'
        return httpx.Response(200, json=_completion(content))

    provider, sink = _provider(handler, monkeypatch)
    result = await provider.extract(_request())
    assert result.status == "fixed" and calls == 2
    assert sink.events[0].schema_repairs == 1


@pytest.mark.asyncio
async def test_extract_fails_after_one_failed_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_completion('{"wrong": true}'))

    provider, sink = _provider(handler, monkeypatch)
    with pytest.raises(APIMasterSchemaError):
        await provider.extract(_request())
    assert calls == 2  # exactly one repair attempt, then fail


@pytest.mark.asyncio
async def test_auth_error_is_classified_without_key_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, sink = _provider(
        lambda request: httpx.Response(401, json={"error": {"message": "bad key"}}),
        monkeypatch,
    )
    with pytest.raises(APIMasterAuthError) as excinfo:
        await provider.extract(_request())
    assert "sk-apimaster-unit-test-key" not in str(excinfo.value)
    assert sink.events[0].error_kind == "auth"


@pytest.mark.asyncio
async def test_missing_key_fails_before_http() -> None:
    provider = APIMasterProvider(_config(api_key=None))
    with pytest.raises(APIMasterMissingKeyError):
        await provider.extract(_request())


@pytest.mark.asyncio
async def test_malformed_body_is_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, sink = _provider(
        lambda request: httpx.Response(200, content=b"not json"),
        monkeypatch,
    )
    with pytest.raises(Exception) as excinfo:
        await provider.extract(_request())
    assert getattr(excinfo.value, "error_kind", None) == "malformed"


@pytest.mark.asyncio
async def test_request_body_uses_json_schema_and_secret_free_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_completion('{"status": "ok"}'))

    provider, _ = _provider(handler, monkeypatch)
    await provider.extract(_request())
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-6.1-sol"
    assert body["response_format"]["type"] == "json_schema"  # type: ignore[index]
    assert body["usage"] == {"include": True}
    # The API key travels only in the Authorization header — never in body.
    assert "sk-apimaster" not in json.dumps(body)
    assert str(seen["auth"]).startswith("Bearer ")


def test_gemini_uses_json_object_mode_not_strict_schema() -> None:
    """Verified live: APIMaster Gemini Flash ignores strict json_schema."""

    fmt = json_response_format("gemini-3.8-flash", _Output)
    assert fmt == {"type": "json_object"}
    strict = json_response_format("gpt-6.1-sol", _Output)
    assert strict["type"] == "json_schema"
    schema = strict["json_schema"]["schema"]  # type: ignore[index]
    assert schema["additionalProperties"] is False  # type: ignore[index]
    assert schema["required"] == ["status"]  # type: ignore[index]


def test_free_form_object_models_fall_back_to_json_object_mode() -> None:
    """Regression: strict mode cannot express ``dict[str, object]``.

    Seen live while processing an ingested web page: APIMaster answered
    ``SourceStructureOutputRaw`` with 400 "Invalid schema for
    response_format … In context=('properties', 'nodes', 'items'),
    'additionalProperties' is required to be supplied and to be false."
    The items schema is a bare ``{"type": "object"}`` — forbidding extra
    properties there would allow only ``{}``, so the whole model has to go
    through json_object mode, where the schema travels in the prompt.
    """

    class _FreeForm(BaseModel):
        nodes: list[dict[str, object]] = []

    assert json_response_format("gpt-6.1-sol", _FreeForm) == {"type": "json_object"}
    # A fully declared model is unaffected and stays strict.
    assert json_response_format("gpt-6.1-sol", _Output)["type"] == "json_schema"


# ---------------------------------------------------------------------
# Sol Responses protocol (§34–38): opt-in route + explicit chat fallback
# ---------------------------------------------------------------------


def _responses_payload(content: str, **usage_overrides: object) -> dict[str, object]:
    usage: dict[str, object] = {
        "input_tokens": 200,
        "output_tokens": 40,
        "input_tokens_details": {"cached_tokens": 0},
    }
    usage.update(usage_overrides)
    return {
        "id": "resp-1",
        "model": "gpt-6.1-sol",
        "output_text": content,
        "usage": usage,
    }


@pytest.mark.asyncio
async def test_responses_protocol_success_and_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_responses_payload('{"status": "ok"}'))

    monkeypatch.setattr(apimaster_module, "_backoff_seconds", lambda *a: 0.0)
    sink = _Collector()
    provider = APIMasterProvider(
        _config(protocol="responses"),
        recorder=sink,
        transport=httpx.MockTransport(handler),
        agent_role="unit_role",
    )
    result = await provider.extract(_request())
    assert result == _Output(status="ok")
    assert seen["path"] == "/v1/responses"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-6.1-sol"
    assert "instructions" in body and "input" in body
    assert body["text"]["format"]["type"] == "json_schema"  # type: ignore[index]
    assert body["text"]["format"]["name"] == "_Output"  # type: ignore[index]
    event = sink.events[0]
    assert event.requested_protocol == "responses"
    assert event.actual_protocol == "responses"
    assert not event.fallback_used
    assert event.prompt_tokens == 200 and event.completion_tokens == 40


@pytest.mark.asyncio
async def test_responses_failure_falls_back_to_chat_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/v1/responses":
            return httpx.Response(404, json={"error": {"message": "not found"}})
        return httpx.Response(200, json=_completion('{"status": "ok"}'))

    monkeypatch.setattr(apimaster_module, "_backoff_seconds", lambda *a: 0.0)
    sink = _Collector()
    provider = APIMasterProvider(
        _config(protocol="responses"),
        recorder=sink,
        transport=httpx.MockTransport(handler),
    )
    result = await provider.extract(_request())
    assert result == _Output(status="ok")
    assert calls == ["/v1/responses", "/v1/chat/completions"]
    event = sink.events[0]
    assert event.requested_protocol == "responses"
    assert event.actual_protocol == "chat"
    assert event.fallback_used
    assert event.fallback_reason == "model_not_found"


@pytest.mark.asyncio
async def test_responses_and_chat_both_fail_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    monkeypatch.setattr(apimaster_module, "_backoff_seconds", lambda *a: 0.0)
    provider = APIMasterProvider(
        _config(protocol="responses"),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(APIMasterAuthError):
        await provider.extract(_request())


@pytest.mark.asyncio
async def test_responses_timeout_falls_back_to_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/responses":
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json=_completion('{"status": "ok"}'))

    monkeypatch.setattr(apimaster_module, "_backoff_seconds", lambda *a: 0.0)
    sink = _Collector()
    provider = APIMasterProvider(
        _config(protocol="responses", max_retries=0),
        recorder=sink,
        transport=httpx.MockTransport(handler),
    )
    result = await provider.extract(_request())
    assert result == _Output(status="ok")
    event = sink.events[0]
    assert event.fallback_used
    assert event.fallback_reason == "timeout"
    assert event.actual_protocol == "chat"


@pytest.mark.asyncio
async def test_responses_output_items_fallback_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Responses without a top-level output_text: walk output items."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp-2",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": '{"status": "ok"}'}
                        ],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 3},
            },
        )

    monkeypatch.setattr(apimaster_module, "_backoff_seconds", lambda *a: 0.0)
    provider = APIMasterProvider(
        _config(protocol="responses"),
        transport=httpx.MockTransport(handler),
    )
    result = await provider.extract(_request())
    assert result == _Output(status="ok")


@pytest.mark.asyncio
async def test_chat_protocol_unchanged_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=_completion('{"status": "ok"}'))

    provider, sink = _provider(handler, monkeypatch)
    await provider.extract(_request())
    assert calls == ["/v1/chat/completions"]
    event = sink.events[0]
    assert event.requested_protocol == "chat"
    assert event.actual_protocol == "chat"
    assert not event.fallback_used
