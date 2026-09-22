"""Phase 8 structured lecture-master HTTP boundary."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request

from app.db.session import Database
from app.lecture.schemas import (
    LectureBuildResult,
    LectureMasterRead,
    LectureProjectCreate,
    LectureProjectRead,
    SemanticLectureMasterExport,
)
from app.lecture.service import LectureMasterService

router = APIRouter(tags=["lectures"])


def _service(request: Request) -> LectureMasterService:
    return LectureMasterService(cast(Database, request.app.state.database))


@router.post("/lectures", response_model=LectureProjectRead)
async def create(payload: LectureProjectCreate, request: Request) -> LectureProjectRead:
    return await _service(request).create_project(payload)


@router.get("/lectures", response_model=list[LectureProjectRead])
async def projects(request: Request) -> list[LectureProjectRead]:
    return await _service(request).projects()


@router.post("/lectures/{lecture_id}/architect", response_model=LectureMasterRead)
async def architect(lecture_id: UUID, request: Request) -> LectureMasterRead:
    return await _service(request).architect(lecture_id)


@router.get("/lecture-masters/{master_id}", response_model=LectureMasterRead)
async def master(master_id: UUID, request: Request) -> LectureMasterRead:
    return await _service(request).master(master_id)


@router.post("/lecture-masters/{master_id}/validate", response_model=LectureBuildResult)
async def validate(master_id: UUID, request: Request) -> LectureBuildResult:
    return await _service(request).validate(master_id)


@router.post("/lecture-masters/{master_id}/freeze", response_model=LectureMasterRead)
async def freeze(master_id: UUID, request: Request) -> LectureMasterRead:
    return await _service(request).freeze(master_id)


@router.get(
    "/lecture-masters/{master_id}/export", response_model=SemanticLectureMasterExport
)
async def export(master_id: UUID, request: Request) -> SemanticLectureMasterExport:
    return await _service(request).export(master_id)
