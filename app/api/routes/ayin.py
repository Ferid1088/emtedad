"""Thin Phase 2 Ayin read endpoints."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request

from app.core.ayin.schemas import (
    ConceptRead,
    DistinctionRead,
    DocumentDetail,
    DocumentSummary,
    OpenQuestionRead,
    PrincipleRead,
    RelationRead,
    TermRead,
)
from app.core.ayin.service import AyinReadService
from app.db.session import Database

router = APIRouter(prefix="/ayin", tags=["ayin"])


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


@router.get("/documents", response_model=list[DocumentSummary])
async def list_documents(request: Request) -> list[DocumentSummary]:
    async with _database(request).transaction() as session:
        return await AyinReadService(session).documents()


@router.get("/documents/{document_id}", response_model=DocumentDetail)
async def get_document(request: Request, document_id: UUID) -> DocumentDetail:
    async with _database(request).transaction() as session:
        return await AyinReadService(session).document(document_id)


@router.get("/concepts", response_model=list[ConceptRead])
async def list_concepts(request: Request) -> list[ConceptRead]:
    async with _database(request).transaction() as session:
        return await AyinReadService(session).concepts()


@router.get("/concepts/{stable_key}", response_model=ConceptRead)
async def get_concept(request: Request, stable_key: str) -> ConceptRead:
    async with _database(request).transaction() as session:
        return await AyinReadService(session).concept(stable_key)


@router.get("/distinctions", response_model=list[DistinctionRead])
async def list_distinctions(request: Request) -> list[DistinctionRead]:
    async with _database(request).transaction() as session:
        return await AyinReadService(session).distinctions()


@router.get("/principles", response_model=list[PrincipleRead])
async def list_principles(request: Request) -> list[PrincipleRead]:
    async with _database(request).transaction() as session:
        return await AyinReadService(session).principles()


@router.get("/relations", response_model=list[RelationRead])
async def list_relations(request: Request) -> list[RelationRead]:
    async with _database(request).transaction() as session:
        return await AyinReadService(session).relations()


@router.get("/open-questions", response_model=list[OpenQuestionRead])
async def list_open_questions(request: Request) -> list[OpenQuestionRead]:
    async with _database(request).transaction() as session:
        return await AyinReadService(session).open_questions()


@router.get("/terms", response_model=list[TermRead])
async def list_terms(request: Request, query: str | None = None) -> list[TermRead]:
    async with _database(request).transaction() as session:
        return await AyinReadService(session).terms(query)
