"""Version-pinned multilingual retrieval evaluation and ranking metrics."""

import math
from dataclasses import dataclass
from statistics import mean
from uuid import UUID

from sqlalchemy import delete, select

from app.core.ayin.models import AyinConcept
from app.db.session import Database
from app.retrieval.domain import EvaluationQueryType, QueryLanguage, RetrievalLane
from app.retrieval.models import (
    Chunk,
    ChunkAyinConcept,
    EvaluationJudgment,
    EvaluationQuery,
    EvaluationRun,
    RetrievalRun,
)
from app.retrieval.service import HybridRetrievalService


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    run_id: UUID
    query_count: int
    passed: bool
    metrics: dict[str, object]


_AYIN_QUERIES = (
    ("emtedad", "fa", "امتداد چیست؟", EvaluationQueryType.EXACT_CONCEPT),
    ("emtedad", "en", "What is Emtedad?", EvaluationQueryType.CROSS_LANGUAGE),
    ("emtedad", "ar", "ما معنى امتداد؟", EvaluationQueryType.CROSS_LANGUAGE),
    (
        "bon",
        "fa",
        "بُن چیست و چه تفاوتی با روح دارد؟",
        EvaluationQueryType.DISTINCTION_TRAP,
    ),
    ("bon", "en", "Is Bon the same as soul?", EvaluationQueryType.DISTINCTION_TRAP),
    ("bon", "ar", "هل البُن هو الروح؟", EvaluationQueryType.DISTINCTION_TRAP),
    ("jan", "fa", "جان چه نسبتی با زنده بودن دارد؟", EvaluationQueryType.PARAPHRASE),
    (
        "jan",
        "en",
        "How does Jan relate to being alive?",
        EvaluationQueryType.CROSS_LANGUAGE,
    ),
    ("jan", "ar", "ما علاقة جان بالكائن الحي؟", EvaluationQueryType.CROSS_LANGUAGE),
)


def ranking_metrics(
    ranked_ids: list[UUID], relevance: dict[UUID, int], *, k: int = 5
) -> dict[str, float]:
    """Compute recall, reciprocal rank, and graded nDCG at k."""

    relevant = {item for item, grade in relevance.items() if grade > 0}
    top = ranked_ids[:k]
    hits = [item for item in top if item in relevant]
    recall = len(set(hits)) / len(relevant) if relevant else 0.0
    reciprocal_rank = next(
        (1.0 / rank for rank, item in enumerate(top, 1) if item in relevant), 0.0
    )
    dcg = sum(
        (2 ** relevance.get(item, 0) - 1) / math.log2(rank + 1)
        for rank, item in enumerate(top, 1)
    )
    ideal = sorted(relevance.values(), reverse=True)[:k]
    idcg = sum(
        (2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(ideal, 1)
    )
    return {
        f"recall@{k}": recall,
        f"mrr@{k}": reciprocal_rank,
        f"ndcg@{k}": dcg / idcg if idcg else 0.0,
    }


class RetrievalEvaluationService:
    """Seed reviewed source-backed queries and persist reproducible results."""

    def __init__(self, database: Database, retrieval: HybridRetrievalService) -> None:
        self._database = database
        self._retrieval = retrieval

    async def seed_ayin_queries(self, chunking_run_id: UUID) -> int:
        async with self._database.transaction() as session:
            count = 0
            for concept_key, language, text, query_type in _AYIN_QUERIES:
                chunk_ids = list(
                    await session.scalars(
                        select(ChunkAyinConcept.chunk_id)
                        .join(
                            AyinConcept,
                            AyinConcept.id == ChunkAyinConcept.concept_id,
                        )
                        .where(
                            AyinConcept.stable_key == concept_key,
                            Chunk.id == ChunkAyinConcept.chunk_id,
                            Chunk.chunking_run_id == chunking_run_id,
                        )
                    )
                )
                if not chunk_ids:
                    raise RuntimeError(
                        f"no source-backed chunk for concept {concept_key}"
                    )
                stable_key = f"ayin-{concept_key}"
                query = await session.scalar(
                    select(EvaluationQuery).where(
                        EvaluationQuery.stable_key == stable_key,
                        EvaluationQuery.language == QueryLanguage(language),
                    )
                )
                if query is None:
                    query = EvaluationQuery(
                        stable_key=stable_key,
                        language=QueryLanguage(language),
                        query_text=text,
                        query_type=query_type,
                        expected_lane=RetrievalLane.AYIN,
                        notes=(
                            "Gold target is linked to a reviewed Working concept seed."
                        ),
                    )
                    session.add(query)
                    await session.flush()
                else:
                    query.query_text = text
                    query.query_type = query_type
                    await session.execute(
                        delete(EvaluationJudgment).where(
                            EvaluationJudgment.evaluation_query_id == query.id
                        )
                    )
                session.add_all(
                    [
                        EvaluationJudgment(
                            evaluation_query_id=query.id,
                            chunk_id=chunk_id,
                            relevance=3,
                            rationale=(
                                "Chunk is explicitly linked to Ayin concept "
                                f"{concept_key}."
                            ),
                        )
                        for chunk_id in chunk_ids
                    ]
                )
                count += 1
            return count

    async def evaluate(
        self,
        *,
        chunking_run_id: UUID,
        embedding_model_id: UUID,
        k: int = 5,
        minimum_recall: float = 0.75,
        minimum_mrr: float = 0.5,
        minimum_ndcg: float = 0.6,
        maximum_p95_ms: int = 3000,
    ) -> EvaluationSummary:
        async with self._database.transaction() as session:
            rows = list(
                await session.scalars(
                    select(EvaluationQuery).order_by(
                        EvaluationQuery.language, EvaluationQuery.stable_key
                    )
                )
            )
            judgments = {
                query.id: {
                    item.chunk_id: item.relevance
                    for item in await session.scalars(
                        select(EvaluationJudgment).where(
                            EvaluationJudgment.evaluation_query_id == query.id
                        )
                    )
                }
                for query in rows
            }
        if not rows:
            raise RuntimeError("evaluation set is empty")

        warmup = await self._retrieval.search(
            rows[0].query_text,
            rows[0].language,
            chunking_run_id=chunking_run_id,
            embedding_model_id=embedding_model_id,
            lanes=[rows[0].expected_lane],
            parameters={"lane_top_n": 20},
        )
        samples: list[tuple[QueryLanguage, dict[str, dict[str, float]], int, UUID]] = []
        for query in rows:
            response = await self._retrieval.search(
                query.query_text,
                query.language,
                chunking_run_id=chunking_run_id,
                embedding_model_id=embedding_model_id,
                lanes=[query.expected_lane],
                parameters={"lane_top_n": 20},
            )
            rankings = {
                "lexical": [
                    item.chunk_id
                    for item in sorted(
                        response.results,
                        key=lambda value: value.lexical_rank or 10**9,
                    )
                    if item.lexical_rank is not None
                ],
                "dense": [
                    item.chunk_id
                    for item in sorted(
                        response.results,
                        key=lambda value: value.dense_rank or 10**9,
                    )
                    if item.dense_rank is not None
                ],
                "entity": [
                    item.chunk_id
                    for item in sorted(
                        response.results,
                        key=lambda value: value.entity_rank or 10**9,
                    )
                    if item.entity_rank is not None
                ],
                "rrf": [
                    item.chunk_id
                    for item in sorted(
                        response.results,
                        key=lambda value: (-value.fusion_score, str(value.chunk_id)),
                    )
                ],
                "hybrid": [item.chunk_id for item in response.results],
            }
            metrics = {
                name: ranking_metrics(ranked, judgments[query.id], k=k)
                for name, ranked in rankings.items()
            }
            samples.append(
                (
                    query.language,
                    metrics,
                    response.elapsed_ms,
                    response.retrieval_run_id,
                )
            )

        by_language: dict[str, object] = {}
        for language in QueryLanguage:
            selected = [item for item in samples if item[0] is language]
            by_language[language.value] = {
                name: mean(item[1]["hybrid"][name] for item in selected)
                for name in (f"recall@{k}", f"mrr@{k}", f"ndcg@{k}")
            }
        latencies = sorted(item[2] for item in samples)
        p95 = latencies[max(0, math.ceil(len(latencies) * 0.95) - 1)]
        overall = {
            name: mean(item[1]["hybrid"][name] for item in samples)
            for name in (f"recall@{k}", f"mrr@{k}", f"ndcg@{k}")
        }
        by_retriever = {
            retriever: {
                name: mean(item[1][retriever][name] for item in samples)
                for name in (f"recall@{k}", f"mrr@{k}", f"ndcg@{k}")
            }
            for retriever in ("lexical", "dense", "entity", "rrf", "hybrid")
        }
        passed = (
            overall[f"recall@{k}"] >= minimum_recall
            and overall[f"mrr@{k}"] >= minimum_mrr
            and overall[f"ndcg@{k}"] >= minimum_ndcg
            and p95 <= maximum_p95_ms
            and all(
                values[f"recall@{k}"] >= minimum_recall
                for values in by_language.values()
                if isinstance(values, dict)
            )
        )
        metrics_payload: dict[str, object] = {
            "overall": overall,
            "by_language": by_language,
            "by_retriever": by_retriever,
            "latency_ms": {
                "cold_start": warmup.elapsed_ms,
                "steady_state_p95": p95,
                "steady_state_samples": latencies,
            },
            "thresholds": {
                "minimum_recall": minimum_recall,
                "minimum_mrr": minimum_mrr,
                "minimum_ndcg": minimum_ndcg,
                "maximum_p95_ms": maximum_p95_ms,
            },
        }
        async with self._database.transaction() as session:
            retrieval_run = await session.get(RetrievalRun, samples[-1][3])
            if retrieval_run is None:
                raise RuntimeError("retrieval evaluation run disappeared")
            run = EvaluationRun(
                chunking_run_id=chunking_run_id,
                embedding_model_id=embedding_model_id,
                configuration_id=retrieval_run.configuration_id,
                metrics=metrics_payload,
                query_count=len(samples),
                passed=passed,
            )
            session.add(run)
            await session.flush()
            return EvaluationSummary(run.id, len(samples), passed, metrics_payload)
