"""Thin liveness and readiness HTTP routes."""

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.db.health import ReadinessService

router = APIRouter(prefix="/health", tags=["system"])


class HealthResponse(BaseModel):
    """Stable public health response without infrastructure details."""

    status: Literal["live", "ready", "not_ready"]


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    """Report process liveness without checking dependencies."""

    return HealthResponse(status="live")


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse}},
)
async def ready(request: Request) -> HealthResponse | JSONResponse:
    """Report readiness after the database service validates dependencies."""

    readiness_service: ReadinessService = request.app.state.readiness_service
    result = await readiness_service.check()
    if result.ready:
        return HealthResponse(status="ready")
    return JSONResponse(status_code=503, content={"status": "not_ready"})
