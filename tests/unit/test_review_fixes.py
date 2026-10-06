"""Regression tests for the 2026-10-06 repository review fixes."""

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

import app.knowledge.llm.apimaster as apimaster_module
from app.channel_monitoring.service import ChannelDiscoveryService
from app.core.config import Settings
from app.db.health import ReadinessResult
from app.knowledge.llm.apimaster import (
    APIMasterConfig,
    APIMasterError,
    APIMasterProvider,
    bare_model_id,
    json_response_format,
)
from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.llm.pricing import ModelPrice, PriceSnapshot
from app.main import create_app


class _Output(BaseModel):
    status: str


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
    handler: object, monkeypatch: pytest.MonkeyPatch, *, retry_timeouts: bool
) -> APIMasterProvider:
    monkeypatch.setattr(apimaster_module, "_backoff_seconds", lambda *a: 0.0)
    return APIMasterProvider(
        APIMasterConfig(
            api_key="sk-apimaster-unit-test-key",
            model="openai/gpt-6-astra",
            max_retries=2,
            retry_timeouts=retry_timeouts,
        ),
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        agent_role="unit_role",
    )


# --- namespaced model IDs -------------------------------------------------


def test_bare_model_id_strips_namespace() -> None:
    assert bare_model_id("openai/gpt-6.1-sol") == "gpt-6.1-sol"
    assert bare_model_id("qwen3.8-flash") == "qwen3.8-flash"


def test_namespaced_gemini_still_uses_json_object_mode() -> None:
    assert json_response_format("google/gemini-3.8-flash", _Output) == {
        "type": "json_object"
    }


def test_price_lookup_accepts_namespaced_ids() -> None:
    price = ModelPrice(model="gpt-6.1-sol", input_per_mtok=1.0, output_per_mtok=2.0)
    snapshot = PriceSnapshot(
        retrieved_at="now",
        pricing_version="v",
        group="default",
        group_ratio=1.0,
        source="unit",
        models={"gpt-6.1-sol": price},
    )
    assert snapshot.price_for("openai/gpt-6.1-sol") is price
    assert snapshot.price_for("gpt-6.1-sol") is price
    assert snapshot.price_for("openai/unknown") is None


# --- premium timeout retries ----------------------------------------------


@pytest.mark.asyncio
async def test_edge_timeout_not_retried_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(524)

    provider = _provider(handler, monkeypatch, retry_timeouts=False)
    with pytest.raises(Exception) as excinfo:
        await provider.extract(_request())
    assert getattr(excinfo.value, "error_kind", None) == "timeout"
    assert calls == 1


@pytest.mark.asyncio
async def test_client_timeout_not_retried_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    provider = _provider(handler, monkeypatch, retry_timeouts=False)
    with pytest.raises(Exception) as excinfo:
        await provider.extract(_request())
    assert getattr(excinfo.value, "error_kind", None) == "timeout"
    assert calls == 1


@pytest.mark.asyncio
async def test_edge_timeout_still_retried_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(524)

    provider = _provider(handler, monkeypatch, retry_timeouts=True)
    with pytest.raises(APIMasterError):
        await provider.extract(_request())
    assert calls == 3


@pytest.mark.asyncio
async def test_other_upstream_errors_still_retried_for_premium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(502)

    provider = _provider(handler, monkeypatch, retry_timeouts=False)
    with pytest.raises(APIMasterError):
        await provider.extract(_request())
    assert calls == 3


def test_factory_disables_timeout_retries_for_premium_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings
    from app.knowledge.llm.factory import resolve_llm_provider
    from app.knowledge.llm.roles import AgentRole

    monkeypatch.setenv("EMTEDAD_APIMASTER_API_KEY", "sk-unit")
    get_settings.cache_clear()
    premium = resolve_llm_provider(role=AgentRole.PERSIAN_SCRIPT_WRITER)
    reasoning = resolve_llm_provider(role=AgentRole.FIDELITY_CRITIC)
    assert isinstance(premium, APIMasterProvider)
    assert isinstance(reasoning, APIMasterProvider)
    assert premium.config.retry_timeouts is False
    assert reasoning.config.retry_timeouts is True


# --- lazy LLM resolution --------------------------------------------------


def test_channel_service_does_not_need_llm_until_ingest() -> None:
    # Construction must not resolve an LLM provider (no API key needed).
    service = ChannelDiscoveryService(database=object(), adapter=object())  # type: ignore[arg-type]
    assert service._importer is None


# --- local-only guard -----------------------------------------------------


class _Ready:
    async def check(self) -> ReadinessResult:  # pragma: no cover
        raise NotImplementedError


@pytest.fixture
def client(test_settings: Settings) -> TestClient:
    return TestClient(create_app(test_settings, readiness_service=_Ready()))


def test_loopback_host_allowed(client: TestClient) -> None:
    response = client.get("/health/live", headers={"host": "127.0.0.1:8000"})
    assert response.status_code == 200


def test_foreign_host_rejected(client: TestClient) -> None:
    response = client.get("/health/live", headers={"host": "evil.example"})
    assert response.status_code == 403


def test_cross_site_post_rejected(client: TestClient) -> None:
    response = client.post(
        "/channels/check-all", headers={"origin": "https://evil.example"}
    )
    assert response.status_code == 403


def test_null_origin_post_rejected(client: TestClient) -> None:
    response = client.post("/channels/check-all", headers={"origin": "null"})
    assert response.status_code == 403


def test_same_origin_post_passes_guard(client: TestClient) -> None:
    response = client.post(
        "/does-not-exist", headers={"origin": "http://127.0.0.1:8000"}
    )
    assert response.status_code != 403
