"""Typed API/CLI result structures for provenance-complete retrieval."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.core.ayin.domain import CorpusZone
from app.retrieval.domain import QueryLanguage, RetrievalLane, RetrievalSourceKind


class RetrievalProvenance(BaseModel):
    corpus_zone: CorpusZone
    lane: RetrievalLane
    source_kind: RetrievalSourceKind
    source_type: str
    source_id: UUID
    source_version_id: UUID
    source_title: str
    creator: str | None = None
    source_url: str | None
    record_ids: list[UUID]
    page_start: int | None = None
    page_end: int | None = None
    timestamp_start: float | None = None
    timestamp_end: float | None = None
    source_status: str
    editorial_status: str | None = None


class SearchResult(BaseModel):
    chunk_id: UUID
    chunk_content_hash: str
    text: str
    normalized_text: str
    language: str
    section_title: str | None
    matched_entities: list[str]
    lexical_rank: int | None
    lexical_score: float | None
    dense_rank: int | None
    dense_score: float | None
    entity_rank: int | None
    entity_score: float | None
    fusion_score: float
    reranker_score: float
    final_rank: int = Field(gt=0)
    expanded_context: list[dict[str, object]]
    provenance: RetrievalProvenance


class SearchResponse(BaseModel):
    retrieval_run_id: UUID
    chunking_run_id: UUID
    embedding_model_id: UUID
    retrieval_configuration_id: UUID
    query: str
    language: QueryLanguage
    elapsed_ms: int
    results: list[SearchResult]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    language: QueryLanguage
    chunking_run_id: UUID
    embedding_model_id: UUID
    lanes: list[RetrievalLane] | None = None
