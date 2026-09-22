"""Read, proposal, counterevidence, and explicit review HTTP boundary."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request

from app.db.session import Database
from app.dialogue.classifier import EvidenceRoleClassifier
from app.dialogue.domain import RelationType
from app.dialogue.schemas import (
    CounterevidenceRequest,
    ProposalResult,
    ProposeRequest,
    RelationRead,
    ReviewQueueRead,
    ReviewRequest,
)
from app.dialogue.service import DialogueService
from app.knowledge.llm.codex import CodexCliProvider
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.schemas import SearchResult

router = APIRouter(prefix="/dialogue", tags=["dialogue"])


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def _service(request: Request, model: str = "configured-default") -> DialogueService:
    return DialogueService(
        _database(request),
        cast(EmbeddingProvider, request.app.state.embedding_provider),
        EvidenceRoleClassifier(CodexCliProvider(), model=model),
    )


@router.get("/relations", response_model=list[RelationRead])
async def relations(
    request: Request, relation_type: RelationType | None = None
) -> list[RelationRead]:
    return await _service(request).relations(relation_type=relation_type)


@router.get("/relations/{relation_id}", response_model=RelationRead)
async def relation(request: Request, relation_id: UUID) -> RelationRead:
    return await _service(request).relation(relation_id)


@router.get("/ayin/{concept_id}/relations", response_model=list[RelationRead])
async def concept_relations(request: Request, concept_id: UUID) -> list[RelationRead]:
    return await _service(request).relations(concept_id=concept_id)


@router.get("/review-queue", response_model=list[ReviewQueueRead])
async def review_queue(request: Request) -> list[ReviewQueueRead]:
    return await _service(request).review_queue()


@router.post("/propose", response_model=ProposalResult)
async def propose(payload: ProposeRequest, request: Request) -> ProposalResult:
    return await _service(request, payload.model).propose(payload)


@router.post("/counterevidence", response_model=list[SearchResult])
async def counterevidence(
    payload: CounterevidenceRequest, request: Request
) -> list[SearchResult]:
    return await _service(request).counterevidence(payload)


@router.post("/relations/{relation_id}/review", response_model=RelationRead)
async def review(
    relation_id: UUID, payload: ReviewRequest, request: Request
) -> RelationRead:
    return await _service(request).review(relation_id, payload)
