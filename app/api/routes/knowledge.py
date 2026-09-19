"""Thin read-only endpoints for external-knowledge provenance."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request

from app.db.session import Database
from app.knowledge.schemas import (
    ClaimRead,
    EntityRead,
    MentionRead,
    ReviewFlagRead,
    SegmentRead,
    SourceRead,
    SourceVersionRead,
    WorkRead,
)
from app.knowledge.service import KnowledgeReadService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


@router.get("/sources", response_model=list[SourceRead])
async def sources(request: Request) -> list[SourceRead]:
    async with _database(request).transaction() as session:
        return await KnowledgeReadService(session).sources()


@router.get("/sources/{source_id}", response_model=SourceRead)
async def source(request: Request, source_id: UUID) -> SourceRead:
    async with _database(request).transaction() as session:
        return await KnowledgeReadService(session).source(source_id)


@router.get("/sources/{source_id}/versions", response_model=list[SourceVersionRead])
async def versions(request: Request, source_id: UUID) -> list[SourceVersionRead]:
    async with _database(request).transaction() as session:
        return await KnowledgeReadService(session).versions(source_id)


@router.get("/versions/{version_id}/segments", response_model=list[SegmentRead])
async def segments(request: Request, version_id: UUID) -> list[SegmentRead]:
    async with _database(request).transaction() as session:
        return await KnowledgeReadService(session).segments(version_id)


@router.get("/sources/{source_id}/segments", response_model=list[SegmentRead])
async def source_segments(request: Request, source_id: UUID) -> list[SegmentRead]:
    async with _database(request).transaction() as session:
        return await KnowledgeReadService(session).source_segments(source_id)


@router.get("/sources/{source_id}/mentions", response_model=list[MentionRead])
async def source_mentions(request: Request, source_id: UUID) -> list[MentionRead]:
    async with _database(request).transaction() as session:
        return await KnowledgeReadService(session).source_mentions(source_id)


@router.get("/mentions", response_model=list[MentionRead])
async def mentions(request: Request) -> list[MentionRead]:
    async with _database(request).transaction() as session:
        return await KnowledgeReadService(session).mentions()


@router.get("/claims", response_model=list[ClaimRead])
async def claims(request: Request) -> list[ClaimRead]:
    async with _database(request).transaction() as session:
        return await KnowledgeReadService(session).claims()


@router.get("/people", response_model=list[EntityRead])
async def people(request: Request) -> list[EntityRead]:
    async with _database(request).transaction() as session:
        return await KnowledgeReadService(session).people()


@router.get("/people/{person_id}", response_model=EntityRead)
async def person(request: Request, person_id: UUID) -> EntityRead:
    async with _database(request).transaction() as session:
        return await KnowledgeReadService(session).person(person_id)


@router.get("/works", response_model=list[WorkRead])
async def works(request: Request) -> list[WorkRead]:
    async with _database(request).transaction() as session:
        return await KnowledgeReadService(session).works()


@router.get("/works/{work_id}", response_model=WorkRead)
async def work(request: Request, work_id: UUID) -> WorkRead:
    async with _database(request).transaction() as session:
        return await KnowledgeReadService(session).work(work_id)


@router.get("/review-queue", response_model=list[ReviewFlagRead])
async def review_queue(request: Request) -> list[ReviewFlagRead]:
    async with _database(request).transaction() as session:
        return await KnowledgeReadService(session).review_queue()
