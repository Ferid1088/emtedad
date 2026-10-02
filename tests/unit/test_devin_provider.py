"""Contract tests for the Devin Cloud structured-extraction provider."""

import dataclasses
import json

import httpx
import pytest
from pydantic import BaseModel, SecretStr

import app.knowledge.llm.devin as devin_module
from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.llm.devin import DevinCloudError, DevinCloudProvider


class _Output(BaseModel):
    status: str


class _Settings:
    devin_api_key = SecretStr("test-key")


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


def _provider(
    monkeypatch: pytest.MonkeyPatch, handler: httpx.MockTransport
) -> DevinCloudProvider:
    monkeypatch.setattr(devin_module, "get_settings", lambda: _Settings())
    monkeypatch.setattr(devin_module, "_POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(devin_module, "_MESSAGE_INITIALIZING_DELAY_SECONDS", 0)
    return DevinCloudProvider(transport=handler)


def _session_response(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "session_id": "s-1",
        "status_enum": "finished",
        "structured_output": {"status": "ok"},
        "messages": [],
    }
    payload.update(overrides)
    return payload


def _handler(payload: dict[str, object]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"session_id": "s-1"})
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handle)


@pytest.mark.asyncio
async def test_devin_provider_polls_session_and_validates_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(monkeypatch, _handler(_session_response()))
    assert await provider.extract(_request()) == _Output(status="ok")


@pytest.mark.asyncio
async def test_devin_provider_recovers_json_from_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _session_response(
        structured_output=None,
        messages=[{"type": "devin_message", "message": 'done {"status": "ok"}'}],
    )
    provider = _provider(monkeypatch, _handler(payload))
    assert await provider.extract(_request()) == _Output(status="ok")


@pytest.mark.asyncio
async def test_devin_provider_waits_for_message_lagging_blocked_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # status_enum="blocked" lands before the final devin_message is visible.
    gets = 0
    message_posts: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal gets
        if request.method == "POST":
            if request.url.path.endswith("/message"):
                message_posts.append(str(json.loads(request.content)["message"]))
            return httpx.Response(200, json={"session_id": "s-1"})
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        gets += 1
        if gets == 1:
            return httpx.Response(
                200,
                json=_session_response(
                    status_enum="blocked", structured_output=None, messages=[]
                ),
            )
        return httpx.Response(
            200,
            json=_session_response(
                status_enum="blocked",
                structured_output=None,
                messages=[{"type": "devin_message", "message": '{"status":"ok"}'}],
            ),
        )

    provider = _provider(monkeypatch, httpx.MockTransport(handle))
    assert await provider.extract(_request()) == _Output(status="ok")
    assert gets == 2
    assert len(message_posts) == 1  # one nudge to resume the blocked session


@pytest.mark.asyncio
async def test_devin_provider_rejects_finished_without_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(devin_module, "_EMPTY_OUTPUT_GRACE_SECONDS", 0)
    provider = _provider(
        monkeypatch,
        _handler(_session_response(structured_output=None, messages=[])),
    )
    with pytest.raises(DevinCloudError, match="structured output"):
        await provider.extract(_request())


@pytest.mark.asyncio
async def test_devin_provider_rejects_expired_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(
        monkeypatch, _handler(_session_response(status_enum="expired"))
    )
    with pytest.raises(DevinCloudError, match="expired"):
        await provider.extract(_request())


@pytest.mark.asyncio
async def test_devin_provider_accepts_blocked_as_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Devin uses "blocked" for "finished working, awaiting input" — a done state.
    provider = _provider(
        monkeypatch,
        _handler(_session_response(status_enum="blocked")),
    )
    result = await provider.extract(_request())
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_devin_provider_chunks_long_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts: list[tuple[str, dict[str, object]]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/sessions":
            posts.append(("create", json.loads(request.content)))
            return httpx.Response(200, json={"session_id": "s-1"})
        if request.method == "POST":
            posts.append(("message", json.loads(request.content)))
            return httpx.Response(200, json={})
        return httpx.Response(200, json=_session_response())

    provider = _provider(monkeypatch, httpx.MockTransport(handle))
    long_request = dataclasses.replace(
        _request(), input_text="x" * (devin_module._PROMPT_CHAR_LIMIT * 2)
    )
    assert await provider.extract(long_request) == _Output(status="ok")
    kinds = [kind for kind, _ in posts]
    assert kinds == ["create", "message", "message", "message"]
    create_body = posts[0][1]
    assert len(str(create_body["prompt"])) <= devin_module._PROMPT_CHAR_LIMIT + 200
    assert "END-OF-INPUT" in str(create_body["prompt"])
    assert posts[-1][1]["message"].startswith("END-OF-INPUT")


@pytest.mark.asyncio
async def test_devin_provider_retries_message_while_session_initializes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.method == "POST" and request.url.path == "/v1/sessions":
            return httpx.Response(200, json={"session_id": "s-1"})
        if request.method == "POST":
            attempts += 1
            if attempts == 1:
                return httpx.Response(
                    400, json={"detail": "Devin session still initializing"}
                )
            return httpx.Response(200, json={})
        return httpx.Response(200, json=_session_response())

    provider = _provider(monkeypatch, httpx.MockTransport(handle))
    long_request = dataclasses.replace(
        _request(), input_text="x" * (devin_module._PROMPT_CHAR_LIMIT * 2)
    )
    assert await provider.extract(long_request) == _Output(status="ok")
    assert attempts == 4  # retried chunk, remaining chunk, then END-OF-INPUT


@pytest.mark.asyncio
async def test_devin_provider_surfaces_message_send_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/sessions":
            return httpx.Response(200, json={"session_id": "s-1"})
        if request.method == "POST":
            return httpx.Response(500, json={"detail": "boom"})
        return httpx.Response(200, json=_session_response())

    provider = _provider(monkeypatch, httpx.MockTransport(handle))
    long_request = dataclasses.replace(
        _request(), input_text="x" * (devin_module._PROMPT_CHAR_LIMIT * 2)
    )
    with pytest.raises(DevinCloudError, match="request failed: 500"):
        await provider.extract(long_request)


@pytest.mark.asyncio
async def test_devin_provider_rejects_invalid_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(
        monkeypatch,
        _handler(_session_response(structured_output={"wrong": 1})),
    )
    with pytest.raises(DevinCloudError, match="invalid structured output"):
        await provider.extract(_request())


@pytest.mark.asyncio
async def test_devin_provider_rejects_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    provider = _provider(monkeypatch, httpx.MockTransport(handle))
    with pytest.raises(DevinCloudError, match="401"):
        await provider.extract(_request())


@pytest.mark.asyncio
async def test_devin_provider_explains_out_of_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "detail": "Your organization has a billing error. Error: out_of_quota"
            },
        )

    provider = _provider(monkeypatch, httpx.MockTransport(handle))
    with pytest.raises(DevinCloudError, match="Kontingent"):
        await provider.extract(_request())


@pytest.mark.asyncio
async def test_devin_provider_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NoKey:
        devin_api_key = None

    monkeypatch.setattr(devin_module, "get_settings", lambda: _NoKey())
    with pytest.raises(DevinCloudError, match="EMTEDAD_DEVIN_API_KEY"):
        await DevinCloudProvider().extract(_request())


def test_factory_selects_devin(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.knowledge.llm.factory as factory
    from app.knowledge.llm.factory import resolve_llm_provider

    class _FactorySettings:
        llm_provider = "devin"

    monkeypatch.setattr(factory, "get_settings", lambda: _FactorySettings())
    assert isinstance(resolve_llm_provider(), DevinCloudProvider)


def test_factory_default_is_codex(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.knowledge.llm.factory as factory
    from app.knowledge.llm.codex import CodexCliProvider
    from app.knowledge.llm.factory import resolve_llm_provider

    class _FactorySettings:
        llm_provider = None

    monkeypatch.setattr(factory, "get_settings", lambda: _FactorySettings())
    assert isinstance(resolve_llm_provider(), CodexCliProvider)


def test_json_recovery_helper() -> None:
    recovered = devin_module._recover_from_messages(
        [
            {"message": "no json here"},
            {"message": 'note {"a": 1} end'},
        ]
    )
    assert recovered == {"a": 1}
    # Devin appends an ATTACHMENT trailer after the JSON payload.
    with_attachment = devin_module._recover_from_messages(
        [
            {
                "type": "devin_message",
                "message": '{"topics": []}\n\nATTACHMENT:{"url":"https://x","fileSize":1}',
            }
        ]
    )
    assert with_attachment == {"topics": []}
    assert devin_module._recover_from_messages([]) is None
    assert json.loads("{}") == {}
