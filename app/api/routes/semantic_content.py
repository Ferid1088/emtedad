"""HTTP boundary for semantic transcript structuring and automated long-form content."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request

from app.db.session import Database
from app.knowledge.llm.codex import CodexCliProvider
from app.retrieval.embeddings import EmbeddingProvider
from app.semantic_content.generation import AutomatedContentService
from app.semantic_content.schemas import (
    GenerateContentRequest,
    GeneratedContentRead,
    SemanticStructureRequest,
    SemanticTreeRead,
)
from app.semantic_content.structuring import SemanticStructureService

router = APIRouter(tags=["semantic-content"])


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


@router.post(
    "/knowledge/source-versions/{source_version_id}/semantic-structure",
    response_model=SemanticTreeRead,
)
async def build_semantic_structure(
    source_version_id: UUID,
    payload: SemanticStructureRequest,
    request: Request,
) -> SemanticTreeRead:
    service = SemanticStructureService(_database(request), CodexCliProvider())
    return await service.build(source_version_id, payload)


@router.get(
    "/knowledge/source-versions/{source_version_id}/semantic-structure",
    response_model=SemanticTreeRead,
)
async def semantic_structure(
    source_version_id: UUID,
    request: Request,
) -> SemanticTreeRead:
    service = SemanticStructureService(_database(request), CodexCliProvider())
    return await service.preferred_tree(source_version_id)


@router.post("/content/automated", response_model=GeneratedContentRead)
async def generate_content(
    payload: GenerateContentRequest,
    request: Request,
) -> GeneratedContentRead:
    service = AutomatedContentService(
        _database(request),
        cast(EmbeddingProvider, request.app.state.embedding_provider),
        CodexCliProvider(),
    )
    return await service.generate(payload)


@router.get("/content/automated/{project_id}", response_model=GeneratedContentRead)
async def generated_content(project_id: UUID, request: Request) -> GeneratedContentRead:
    service = AutomatedContentService(
        _database(request),
        cast(EmbeddingProvider, request.app.state.embedding_provider),
        CodexCliProvider(),
    )
    return await service.project(project_id)
