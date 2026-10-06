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
    devin_rate_limit_max_attempts = 3
    devin_rate_limit_initial_backoff_seconds = 0.0
    devin_rate_limit_max_backoff_seconds = 0.0


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


def _tracking_handler(
    payload: dict[str, object],
) -> tuple[httpx.MockTransport, dict[str, int]]:
    """Handler that counts create/poll/delete calls."""

    counts = {"create": 0, "delete": 0, "get": 0, "message": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            counts["delete"] += 1
            return httpx.Response(200, json={})
        if request.method == "POST" and request.url.path == "/v1/sessions":
            counts["create"] += 1
            return httpx.Response(200, json={"session_id": "s-1"})
        if request.method == "POST":
            counts["message"] += 1
            return httpx.Response(200, json={})
        counts["get"] += 1
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handle), counts


@pytest.mark.asyncio
async def test_devin_provider_terminates_session_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, counts = _tracking_handler(_session_response())
    provider = _provider(monkeypatch, transport)
    assert await provider.extract(_request()) == _Output(status="ok")
    assert counts["delete"] == 1


@pytest.mark.asyncio
async def test_devin_provider_terminates_session_on_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, counts = _tracking_handler(
        _session_response(structured_output={"wrong": 1})
    )
    provider = _provider(monkeypatch, transport)
    with pytest.raises(DevinCloudError, match="invalid structured output"):
        await provider.extract(_request())
    assert counts["delete"] == 1


@pytest.mark.asyncio
async def test_devin_provider_terminates_session_on_poll_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, counts = _tracking_handler(_session_response(status_enum="expired"))
    provider = _provider(monkeypatch, transport)
    with pytest.raises(DevinCloudError, match="expired"):
        await provider.extract(_request())
    assert counts["delete"] == 1


@pytest.mark.asyncio
async def test_devin_provider_terminates_session_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(devin_module, "_MINIMUM_TIMEOUT_SECONDS", 0)
    transport, counts = _tracking_handler(_session_response(status_enum="running"))
    provider = _provider(monkeypatch, transport)
    request = dataclasses.replace(_request(), timeout_seconds=0)
    with pytest.raises(DevinCloudError, match="did not finish"):
        await provider.extract(request)
    assert counts["delete"] == 1


@pytest.mark.asyncio
async def test_devin_provider_terminates_session_mid_create_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed follow-up message must not orphan the created session."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            counts["delete"] += 1
            return httpx.Response(200, json={})
        if request.method == "POST" and request.url.path == "/v1/sessions":
            return httpx.Response(200, json={"session_id": "s-1"})
        if request.method == "POST":
            return httpx.Response(500, json={"detail": "boom"})
        return httpx.Response(200, json=_session_response())

    counts = {"delete": 0}
    provider = _provider(monkeypatch, httpx.MockTransport(handle))
    long_request = dataclasses.replace(
        _request(), input_text="x" * (devin_module._PROMPT_CHAR_LIMIT * 2)
    )
    with pytest.raises(DevinCloudError, match="request failed: 500"):
        await provider.extract(long_request)
    assert counts["delete"] == 1


@pytest.mark.asyncio
async def test_devin_provider_retries_transient_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creates = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal creates
        if request.method == "POST" and request.url.path == "/v1/sessions":
            creates += 1
            if creates < 3:
                return httpx.Response(429, json={"detail": "slow down"})
            return httpx.Response(200, json={"session_id": "s-1"})
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        return httpx.Response(200, json=_session_response())

    provider = _provider(monkeypatch, httpx.MockTransport(handle))
    assert await provider.extract(_request()) == _Output(status="ok")
    assert creates == 3


@pytest.mark.asyncio
async def test_devin_provider_rate_limit_retry_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creates = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal creates
        if request.method == "POST" and request.url.path == "/v1/sessions":
            creates += 1
            return httpx.Response(429, json={"detail": "slow down"})
        return httpx.Response(200, json=_session_response())

    provider = _provider(monkeypatch, httpx.MockTransport(handle))
    with pytest.raises(devin_module.DevinRateLimitError):
        await provider.extract(_request())
    assert creates == 3  # bounded by devin_rate_limit_max_attempts


@pytest.mark.asyncio
async def test_devin_provider_parallel_session_cap_is_bounded_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    creates = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal creates
        if request.method == "POST" and request.url.path == "/v1/sessions":
            creates += 1
        return httpx.Response(
            429,
            json={
                "detail": (
                    "You have 5 SWE-2 sessions running, the most the free "
                    "SWE-2 promotion allows at once."
                )
            },
        )

    provider = _provider(monkeypatch, httpx.MockTransport(handle))
    with pytest.raises(devin_module.DevinQuotaError, match="PROVIDER_QUOTA"):
        await provider.extract(_request())
    # Hard quota: orphaned sessions are reaped once, then bounded backoff
    # retries — quota clears in minutes, so waiting beats an instant fail,
    # but the loop is still capped by devin_rate_limit_max_attempts.
    assert creates == 3


@pytest.mark.asyncio
async def test_devin_provider_cleanup_failure_preserves_original_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(500, json={"detail": "cleanup boom"})
        if request.method == "POST":
            return httpx.Response(200, json={"session_id": "s-1"})
        return httpx.Response(200, json=_session_response(status_enum="expired"))

    provider = _provider(monkeypatch, httpx.MockTransport(handle))
    with pytest.raises(DevinCloudError, match="expired"):
        await provider.extract(_request())


def test_factory_resolves_devin(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.knowledge.llm.factory as factory_module
    from app.core.config import Settings
    from app.knowledge.llm.factory import resolve_llm_provider

    monkeypatch.setattr(
        factory_module,
        "get_settings",
        lambda: Settings.model_construct(allow_devin_runtime_fallback=True),
    )
    assert isinstance(resolve_llm_provider(), DevinCloudProvider)


def test_factory_ignores_legacy_default_arg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.knowledge.llm.factory as factory_module
    from app.core.config import Settings
    from app.knowledge.llm.factory import resolve_llm_provider

    monkeypatch.setattr(
        factory_module,
        "get_settings",
        lambda: Settings.model_construct(allow_devin_runtime_fallback=True),
    )
    assert isinstance(resolve_llm_provider("codex"), DevinCloudProvider)


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


@pytest.mark.asyncio
async def test_devin_provider_repairs_corrupted_output_in_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """U+FFFD output gets one in-session repair turn — the agent sees and
    fixes its own corrupted text; the stale payload is never re-read."""

    monkeypatch.setattr(devin_module, "_CORRUPTION_REPAIR_TIMEOUT_SECONDS", 5)
    corrupted = {"status": "broken�text"}
    clean = {"status": "ok"}
    gets = 0
    messages: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal gets
        if request.method == "POST" and request.url.path == "/v1/sessions":
            return httpx.Response(200, json={"session_id": "s-1"})
        if request.method == "POST":
            messages.append(str(json.loads(request.content)["message"]))
            return httpx.Response(200, json={})
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        gets += 1
        if gets == 1:
            return httpx.Response(
                200,
                json=_session_response(
                    status_enum="blocked", structured_output=corrupted
                ),
            )
        return httpx.Response(
            200,
            json=_session_response(status_enum="blocked", structured_output=clean),
        )

    provider = _provider(monkeypatch, httpx.MockTransport(handle))
    result = await provider.extract(_request())

    assert result == _Output(status="ok")
    assert gets == 2
    assert any("U+FFFD" in message for message in messages)


@pytest.mark.asyncio
async def test_devin_provider_fresh_retry_when_repair_still_corrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed repair keeps the corrupted result; extract() then makes
    exactly one fresh-session attempt."""

    monkeypatch.setattr(devin_module, "_EMPTY_OUTPUT_GRACE_SECONDS", 0)
    creates = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal creates
        if request.method == "POST" and request.url.path == "/v1/sessions":
            creates += 1
            return httpx.Response(200, json={"session_id": f"s-{creates}"})
        if request.method == "POST":
            return httpx.Response(200, json={})
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        if creates == 1:
            # Session 1: corrupted output; repair re-polls see the same
            # stale payload (ignore_structured) until the grace expiry.
            return httpx.Response(
                200,
                json=_session_response(
                    status_enum="blocked",
                    structured_output={"status": "bad�"},
                ),
            )
        return httpx.Response(
            200,
            json=_session_response(
                status_enum="blocked", structured_output={"status": "ok"}
            ),
        )

    provider = _provider(monkeypatch, httpx.MockTransport(handle))
    result = await provider.extract(_request())

    assert result == _Output(status="ok")
    assert creates == 2


@pytest.mark.asyncio
async def test_devin_provider_retries_fresh_when_session_not_messageable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 'finished' session cannot be repaired — straight to the fresh
    retry, bounded at one."""

    creates = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal creates
        if request.method == "POST" and request.url.path == "/v1/sessions":
            creates += 1
            return httpx.Response(200, json={"session_id": f"s-{creates}"})
        if request.method == "POST":
            return httpx.Response(400, json={"detail": "session finished"})
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        if creates == 1:
            return httpx.Response(
                200,
                json=_session_response(
                    status_enum="finished",
                    structured_output={"status": "bad�"},
                ),
            )
        return httpx.Response(
            200,
            json=_session_response(
                status_enum="blocked", structured_output={"status": "ok"}
            ),
        )

    provider = _provider(monkeypatch, httpx.MockTransport(handle))
    result = await provider.extract(_request())

    assert result == _Output(status="ok")
    assert creates == 2


@pytest.mark.asyncio
async def test_orphan_sweep_reaps_old_blocked_sessions_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4 §5: dead sessions holding quota slots get reaped; fresh or
    running ones are untouched."""

    deleted: list[str] = []
    old = "2000-01-01T00:00:00Z"
    fresh = "2999-01-01T00:00:00Z"
    sessions = {
        "sessions": [
            {
                "session_id": "old-blocked",
                "status_enum": "blocked",
                "updated_at": old,
                "tags": ["emtedad-app"],
            },
            {
                "session_id": "foreign-blocked",
                "status_enum": "blocked",
                "updated_at": old,
                "tags": ["devin-app"],  # another tool's session — never reaped
            },
            {
                "session_id": "fresh-blocked",
                "status_enum": "blocked",
                "updated_at": fresh,
                "tags": ["emtedad-app"],
            },
            {
                "session_id": "live-running",
                "status_enum": "running",
                "updated_at": old,
                "tags": ["emtedad-app"],
            },
            {
                "session_id": "done",
                "status_enum": "finished",
                "updated_at": old,
                "tags": ["emtedad-app"],
            },
        ]
    }

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            deleted.append(request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(200, json={})
        if request.method == "GET" and request.url.path == "/v1/sessions":
            return httpx.Response(200, json=sessions)
        if request.method == "POST":
            return httpx.Response(200, json={"session_id": "s-1"})
        return httpx.Response(200, json=_session_response())

    monkeypatch.setattr(devin_module, "_last_orphan_sweep", float("-inf"))
    provider = _provider(monkeypatch, httpx.MockTransport(handle))
    result = await provider.extract(_request())
    assert result == _Output(status="ok")
    # 's-1' is the normal post-extract termination; the sweep must reap
    # only the stale tagged session — never fresh, running, or foreign.
    assert "old-blocked" in deleted
    assert "foreign-blocked" not in deleted
    assert "fresh-blocked" not in deleted
    assert "live-running" not in deleted
    assert "done" not in deleted


@pytest.mark.asyncio
async def test_quota_error_triggers_sweep_then_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A quota 429 sweeps orphans once and retries session creation."""

    posts = 0
    swept = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal posts, swept
        if request.method == "POST":
            posts += 1
            if posts == 1:
                return httpx.Response(429, text="You have 5 SWE-2 sessions running")
            return httpx.Response(200, json={"session_id": "s-1"})
        if request.method == "GET" and request.url.path == "/v1/sessions":
            swept += 1
            return httpx.Response(200, json={"sessions": []})
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        return httpx.Response(200, json=_session_response())

    monkeypatch.setattr(devin_module, "_last_orphan_sweep", float("-inf"))
    provider = _provider(monkeypatch, httpx.MockTransport(handle))
    assert await provider.extract(_request()) == _Output(status="ok")
    assert posts == 2
    assert swept >= 1
