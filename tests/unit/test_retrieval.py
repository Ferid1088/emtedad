"""Deterministic unit coverage for Phase 5 retrieval primitives."""

from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.retrieval import router
from app.cli import _parser
from app.core.ayin.domain import CorpusZone
from app.retrieval.domain import QueryLanguage, RetrievalLane, RetrievalSourceKind
from app.retrieval.evaluation import ranking_metrics
from app.retrieval.normalization import normalize_search_text, search_tokens
from app.retrieval.retrievers import Candidate, EntityRetriever, FusionService
from app.retrieval.schemas import RetrievalProvenance, SearchResponse, SearchResult
from app.retrieval.service import HybridRetrievalService, _integer_parameter


def _id(value: int) -> UUID:
    return UUID(int=value)


def test_multilingual_normalization_unifies_arabic_persian_variants() -> None:
    assert normalize_search_text("  يَك\u200c كلمه  ") == "یک کلمه"
    assert search_tokens("What is امتداد؟") == ["what", "is", "امتداد"]


def test_rrf_is_deterministic_and_combines_independent_rankers() -> None:
    lexical = [
        Candidate(_id(1), RetrievalLane.AYIN, lexical_rank=1, lexical_score=1.0),
        Candidate(_id(2), RetrievalLane.AYIN, lexical_rank=2, lexical_score=0.5),
    ]
    dense = [
        Candidate(_id(2), RetrievalLane.AYIN, dense_rank=1, dense_score=0.9),
        Candidate(_id(1), RetrievalLane.AYIN, dense_rank=2, dense_score=0.8),
    ]
    fused = FusionService(rrf_k=60).fuse([lexical, dense], 2)
    assert [item.chunk_id for item in fused] == [_id(1), _id(2)]
    assert fused[0].fusion_score == fused[1].fusion_score
    assert fused[0].lexical_rank == 1
    assert fused[0].dense_rank == 2


def test_lane_interleaving_preserves_explicit_authority_order() -> None:
    lanes = [RetrievalLane.AYIN, RetrievalLane.MANASEK, RetrievalLane.EXTERNAL]
    by_lane = {
        RetrievalLane.AYIN: [Candidate(_id(1), RetrievalLane.AYIN)],
        RetrievalLane.MANASEK: [Candidate(_id(2), RetrievalLane.MANASEK)],
        RetrievalLane.EXTERNAL: [
            Candidate(_id(3), RetrievalLane.EXTERNAL),
            Candidate(_id(4), RetrievalLane.EXTERNAL),
        ],
    }
    output = HybridRetrievalService._interleave(by_lane, lanes)
    assert [item.chunk_id for item in output] == [_id(1), _id(2), _id(3), _id(4)]


@pytest.mark.asyncio
async def test_external_entity_query_orders_distinct_rows_legally() -> None:
    statements: list[object] = []

    class FakeSession:
        async def scalars(self, statement: object) -> list[object]:
            statements.append(statement)
            if len(statements) == 1:
                return [
                    SimpleNamespace(
                        normalized_label="pattern",
                        person_id=None,
                        work_id=None,
                        organization_id=None,
                        concept_id=_id(8),
                    )
                ]
            return [_id(9)]

    results = await EntityRetriever().search(
        cast(AsyncSession, FakeSession()),
        "pattern",
        chunking_run_id=_id(1),
        lane=RetrievalLane.EXTERNAL,
        limit=5,
    )
    sql = str(statements[1])
    select_clause = sql.split("FROM", 1)[0]
    assert "chunks.ordinal" in select_clause
    assert [item.chunk_id for item in results] == [_id(9)]


def test_ranking_metrics_support_graded_gold_judgments() -> None:
    result = ranking_metrics([_id(2), _id(1), _id(3)], {_id(1): 3, _id(3): 1}, k=3)
    assert result["recall@3"] == 1.0
    assert result["mrr@3"] == 0.5
    assert 0.0 < result["ndcg@3"] < 1.0


def test_numeric_configuration_rejects_bool_and_negative_values() -> None:
    assert _integer_parameter({"value": 5}, "value") == 5
    with pytest.raises(ValueError):
        _integer_parameter({"value": True}, "value")
    with pytest.raises(ValueError):
        _integer_parameter({"value": -1}, "value")


def test_retrieval_cli_requires_pinned_run_and_model() -> None:
    args = _parser().parse_args(
        [
            "retrieval",
            "search",
            "امتداد",
            "--language",
            "fa",
            "--chunking-run-id",
            str(_id(1)),
            "--embedding-model-id",
            str(_id(2)),
        ]
    )
    assert args.chunking_run_id == _id(1)
    assert args.embedding_model_id == _id(2)


@pytest.mark.asyncio
async def test_search_api_returns_authority_and_complete_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = SearchResponse(
        retrieval_run_id=_id(9),
        chunking_run_id=_id(1),
        embedding_model_id=_id(2),
        retrieval_configuration_id=_id(8),
        query="امتداد",
        language=QueryLanguage.FA,
        elapsed_ms=12,
        results=[
            SearchResult(
                chunk_id=_id(3),
                chunk_content_hash="a" * 64,
                text="source text",
                normalized_text="source text",
                language="fa",
                section_title=None,
                matched_entities=["emtedad"],
                lexical_rank=1,
                lexical_score=1.0,
                dense_rank=2,
                dense_score=0.8,
                entity_rank=1,
                entity_score=1.0,
                fusion_score=0.04,
                reranker_score=0.9,
                final_rank=1,
                expanded_context=[],
                provenance=RetrievalProvenance(
                    corpus_zone=CorpusZone.AYIN_WORKING,
                    lane=RetrievalLane.AYIN,
                    source_kind=RetrievalSourceKind.AYIN_PASSAGE,
                    source_type="ayin_document",
                    source_id=_id(4),
                    source_version_id=_id(5),
                    source_title="Ayin Working",
                    source_url=None,
                    record_ids=[_id(6)],
                    page_start=132,
                    page_end=132,
                    source_status="draft",
                    editorial_status="draft",
                ),
            )
        ],
    )

    class FakeService:
        def __init__(self, _database: object, _provider: object) -> None:
            pass

        async def search(self, *_args: object, **_kwargs: object) -> SearchResponse:
            return response

    monkeypatch.setattr("app.api.routes.retrieval.HybridRetrievalService", FakeService)
    app = FastAPI()
    app.state.database = object()
    app.state.embedding_provider = object()
    app.include_router(router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            "/retrieval/search",
            json={
                "query": "امتداد",
                "language": "fa",
                "chunking_run_id": str(_id(1)),
                "embedding_model_id": str(_id(2)),
            },
        )
    assert result.status_code == 200
    assert result.json()["results"][0]["provenance"] == {
        "corpus_zone": "AYIN_WORKING",
        "lane": "ayin",
        "source_kind": "ayin_passage",
        "source_type": "ayin_document",
        "source_id": str(_id(4)),
        "source_version_id": str(_id(5)),
        "source_title": "Ayin Working",
        "creator": None,
        "source_url": None,
        "record_ids": [str(_id(6))],
        "page_start": 132,
        "page_end": 132,
        "timestamp_start": None,
        "timestamp_end": None,
        "source_status": "draft",
        "editorial_status": "draft",
    }
    assert result.json()["chunking_run_id"] == str(_id(1))
    assert result.json()["embedding_model_id"] == str(_id(2))
    assert result.json()["retrieval_configuration_id"] == str(_id(8))
