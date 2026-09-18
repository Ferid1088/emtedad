"""Application factory, health, correlation, and error-boundary tests."""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.exceptions import ObjectNotFoundError
from app.db.health import ReadinessResult
from app.main import create_app


class StubReadinessService:
    """Deterministic readiness service for transport tests."""

    def __init__(self, *, ready: bool) -> None:
        self._ready = ready

    async def check(self) -> ReadinessResult:
        return ReadinessResult(ready=self._ready, checks={"stub": self._ready})


@asynccontextmanager
async def _client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        yield client


@pytest.mark.asyncio
async def test_liveness_does_not_depend_on_readiness(
    test_settings: Settings,
) -> None:
    app = create_app(
        test_settings,
        readiness_service=StubReadinessService(ready=False),
    )

    async with _client(app) as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "live"}


@pytest.mark.asyncio
async def test_readiness_uses_service_and_hides_details(
    test_settings: Settings,
) -> None:
    app = create_app(
        test_settings,
        readiness_service=StubReadinessService(ready=False),
    )

    async with _client(app) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


@pytest.mark.asyncio
async def test_ready_dependency_returns_ready(test_settings: Settings) -> None:
    app = create_app(
        test_settings,
        readiness_service=StubReadinessService(ready=True),
    )

    async with _client(app) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_correlation_id_is_preserved_or_safely_replaced(
    test_settings: Settings,
) -> None:
    app = create_app(
        test_settings,
        readiness_service=StubReadinessService(ready=True),
    )

    async with _client(app) as client:
        preserved = await client.get(
            "/health/live", headers={"X-Request-ID": "test-123"}
        )
        replaced = await client.get(
            "/health/live",
            headers={"X-Request-ID": "unsafe value with spaces"},
        )

    assert preserved.headers["X-Request-ID"] == "test-123"
    assert re.fullmatch(r"[0-9a-f]{32}", replaced.headers["X-Request-ID"])


@pytest.mark.asyncio
async def test_application_errors_have_stable_public_contract(
    test_settings: Settings,
) -> None:
    app: FastAPI = create_app(
        test_settings,
        readiness_service=StubReadinessService(ready=True),
    )

    @app.get("/test-error")
    async def raise_test_error() -> None:
        raise ObjectNotFoundError

    async with _client(app) as client:
        response = await client.get("/test-error")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "object_not_found",
            "message": "The stored object was not found.",
        }
    }
