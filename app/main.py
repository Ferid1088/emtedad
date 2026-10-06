"""FastAPI application factory and infrastructure lifecycle."""

import asyncio
import contextlib
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.routes.ayin import router as ayin_router
from app.api.routes.dialogue import router as dialogue_router
from app.api.routes.health import router as health_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.lecture import router as lecture_router
from app.api.routes.research import router as research_router
from app.api.routes.retrieval import router as retrieval_router
from app.api.routes.ritual import router as ritual_router
from app.core.config import Settings, get_settings
from app.core.exceptions import ApplicationError
from app.db.health import DatabaseReadinessService, ReadinessService
from app.db.session import Database, create_database
from app.knowledge.structure.scheduler import init_scheduler
from app.ops.logging import configure_logging
from app.retrieval.embeddings import SentenceTransformerEmbeddingProvider
from app.web.routes import router as web_router
from app.web.studio_routes import router as studio_router

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _host_name(value: str) -> str:
    """Host without port; IPv6 brackets removed."""

    if value.startswith("["):
        return value[1:].split("]", 1)[0].lower()
    return value.rsplit(":", 1)[0].lower() if value.count(":") == 1 else value.lower()


def _local_only_rejection(request: Request, allowed: frozenset[str]) -> str | None:
    """Reason to reject a request to this single-owner local app, if any."""

    if _host_name(request.headers.get("host", "")) not in allowed:
        return "host not allowed"
    if request.method in _UNSAFE_METHODS:
        origin = request.headers.get("origin")
        if origin is not None:
            origin_host = urlsplit(origin).hostname if origin != "null" else None
            if origin_host is None or origin_host.lower() not in allowed:
                return "cross-origin request blocked"
    return None


_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _request_id(request: Request) -> str:
    provided = request.headers.get("X-Request-ID", "")
    if _REQUEST_ID_PATTERN.fullmatch(provided):
        return provided
    return uuid4().hex


def create_app(
    settings: Settings | None = None,
    *,
    readiness_service: ReadinessService | None = None,
) -> FastAPI:
    """Build the application with explicit, testable infrastructure wiring."""

    resolved_settings = settings or get_settings()
    configure_logging(
        level=resolved_settings.log_level,
        json_logs=resolved_settings.log_json,
    )
    logger = structlog.get_logger(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database: Database | None = None
        if readiness_service is None:
            database = create_database(resolved_settings)
            app.state.database = database
            app.state.embedding_provider = SentenceTransformerEmbeddingProvider(
                cache_folder=resolved_settings.storage_root / "models"
            )
            app.state.readiness_service = DatabaseReadinessService(database.engine)
        else:
            app.state.readiness_service = readiness_service

        scanner_task: asyncio.Task[None] | None = None
        if database is not None:
            scheduler = init_scheduler(
                database,
                resolved_settings,
                embedding_provider=app.state.embedding_provider,
            )
            app.state.speech_scheduler = scheduler
            scanner_task = asyncio.create_task(
                scheduler.run_forever(
                    resolved_settings.speech_structure_scan_interval_seconds
                )
            )

        logger.info(
            "application.started",
            environment=resolved_settings.environment.value,
        )
        try:
            yield
        finally:
            if scanner_task is not None:
                scheduler.stop()
                scanner_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await scanner_task
            if database is not None:
                await database.dispose()
            logger.info("application.stopped")

    app = FastAPI(
        title="Ayin-e Emtedad Platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.include_router(health_router)
    app.include_router(ayin_router)
    app.include_router(ritual_router)
    app.include_router(knowledge_router)
    app.include_router(lecture_router)
    app.include_router(retrieval_router)
    app.include_router(research_router)
    app.include_router(dialogue_router)
    app.include_router(web_router)
    app.include_router(studio_router)
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "web" / "static"),
        name="owner-static",
    )

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _request_id(request)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started_at = time.monotonic()
        logger.info(
            "request.started",
            method=request.method,
            path=request.url.path,
        )
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "request.failed",
                error_type=type(exc).__name__,
                method=request.method,
                path=request.url.path,
            )
            raise
        finally:
            structlog.contextvars.unbind_contextvars("request_id")

        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request.completed",
            duration_ms=round((time.monotonic() - started_at) * 1000, 3),
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            request_id=request_id,
        )
        return response

    allowed_hosts = frozenset(h.lower() for h in resolved_settings.allowed_hosts)

    @app.middleware("http")
    async def local_only_guard(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        reason = _local_only_rejection(request, allowed_hosts)
        if reason is not None:
            logger.warning(
                "request.rejected",
                reason=reason,
                method=request.method,
                path=request.url.path,
            )
            return PlainTextResponse(f"Forbidden: {reason}", status_code=403)
        return await call_next(request)

    async def owner_error_page(request: Request, exc: Exception) -> Response:
        from html import escape

        from app.web.jobs import friendly_error

        back = request.headers.get("referer") or "/studio"
        body = (
            "<!doctype html><html lang='de'><head><meta charset='utf-8'>"
            "<title>Fehler</title><link rel='stylesheet' href='/static/owner.css'>"
            "<link rel='stylesheet' href='/static/studio.css'></head><body>"
            "<main style='max-width:720px;margin:3rem auto'>"
            "<h1>Das hat nicht geklappt</h1>"
            f"<p class='error'>{escape(friendly_error(exc))}</p>"
            f"<p><a class='button' href='{escape(back)}'>Zurück</a></p>"
            "</main></body></html>"
        )
        return HTMLResponse(body, status_code=502)

    from app.knowledge.llm.apimaster import APIMasterError
    from app.knowledge.llm.factory import RoutingConfigurationError

    app.add_exception_handler(APIMasterError, owner_error_page)
    app.add_exception_handler(RoutingConfigurationError, owner_error_page)

    @app.exception_handler(ApplicationError)
    async def application_error_handler(
        _request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.public_message,
                }
            },
        )

    return app
