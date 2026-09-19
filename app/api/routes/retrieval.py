"""Thin HTTP boundary for pinned, provenance-complete hybrid search."""

from fastapi import APIRouter, Request

from app.retrieval.schemas import SearchRequest, SearchResponse
from app.retrieval.service import HybridRetrievalService

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post("/search", response_model=SearchResponse)
async def search(payload: SearchRequest, request: Request) -> SearchResponse:
    service = HybridRetrievalService(
        request.app.state.database,
        request.app.state.embedding_provider,
    )
    return await service.search(
        payload.query,
        payload.language,
        chunking_run_id=payload.chunking_run_id,
        embedding_model_id=payload.embedding_model_id,
        lanes=payload.lanes,
    )
