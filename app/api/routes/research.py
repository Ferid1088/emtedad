"""Research Engine HTTP boundary for Phase 7."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request

from app.db.session import Database
from app.research.schemas import (
    AyinSpineBuildRequest,
    AyinSpineRead,
    ResearchPackageBuildRequest,
    ResearchPackageBuildResult,
    ResearchPackageRead,
    ResearchPlanCreate,
    ResearchPlanRead,
    ResearchProjectCreate,
    ResearchProjectRead,
    ResearchValidationReport,
)
from app.research.service import ResearchEngineService
from app.retrieval.embeddings import EmbeddingProvider

router = APIRouter(prefix="/research", tags=["research"])


def _service(request: Request) -> ResearchEngineService:
    return ResearchEngineService(
        cast(Database, request.app.state.database),
        cast(EmbeddingProvider, request.app.state.embedding_provider),
    )


@router.post("/projects", response_model=ResearchProjectRead)
async def create_project(
    payload: ResearchProjectCreate, request: Request
) -> ResearchProjectRead:
    return await _service(request).create_project(payload)


@router.get("/projects", response_model=list[ResearchProjectRead])
async def projects(request: Request) -> list[ResearchProjectRead]:
    return await _service(request).projects()


@router.post("/spines", response_model=AyinSpineRead)
async def build_spine(
    payload: AyinSpineBuildRequest, request: Request
) -> AyinSpineRead:
    return await _service(request).build_spine(payload)


@router.get("/spines/{spine_id}", response_model=AyinSpineRead)
async def spine(spine_id: UUID, request: Request) -> AyinSpineRead:
    return await _service(request).spine(spine_id)


@router.post("/plans", response_model=ResearchPlanRead)
async def create_plan(
    payload: ResearchPlanCreate, request: Request
) -> ResearchPlanRead:
    return await _service(request).create_plan(payload)


@router.get("/plans/{plan_id}", response_model=ResearchPlanRead)
async def plan(plan_id: UUID, request: Request) -> ResearchPlanRead:
    return await _service(request).plan(plan_id)


@router.post("/packages/build", response_model=ResearchPackageBuildResult)
async def build_package(
    payload: ResearchPackageBuildRequest, request: Request
) -> ResearchPackageBuildResult:
    return await _service(request).build_package(payload)


@router.get("/packages", response_model=list[ResearchPackageRead])
async def packages(request: Request) -> list[ResearchPackageRead]:
    return await _service(request).packages()


@router.get("/packages/{package_id}", response_model=ResearchPackageRead)
async def package(package_id: UUID, request: Request) -> ResearchPackageRead:
    return await _service(request).package(package_id)


@router.get("/validate", response_model=ResearchValidationReport)
async def validate(request: Request) -> ResearchValidationReport:
    return await _service(request).validate()
