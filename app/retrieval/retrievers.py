"""Lexical, dense, entity-aware, fusion, reranking, and expansion primitives."""

from dataclasses import dataclass, replace
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ayin.models import AyinConcept
from app.core.terminology.models import Term, TermForm
from app.knowledge.models import EntityLabel
from app.retrieval.domain import RetrievalLane
from app.retrieval.models import (
    Chunk,
    ChunkAyinConcept,
    ChunkEmbedding,
    ChunkExternalEntity,
)
from app.retrieval.normalization import normalize_search_text, search_tokens


@dataclass(frozen=True, slots=True)
class Candidate:
    chunk_id: UUID
    lane: RetrievalLane
    lexical_rank: int | None = None
    lexical_score: float | None = None
    dense_rank: int | None = None
    dense_score: float | None = None
    entity_rank: int | None = None
    entity_score: float | None = None
    fusion_score: float = 0.0
    reranker_score: float = 0.0


class LexicalRetriever:
    async def search(
        self,
        session: AsyncSession,
        query: str,
        *,
        chunking_run_id: UUID,
        lane: RetrievalLane,
        limit: int,
    ) -> list[Candidate]:
        tokens = search_tokens(query)
        if not tokens:
            return []
        tsquery = func.to_tsquery("simple", " | ".join(tokens))
        score = func.ts_rank_cd(Chunk.search_vector, tsquery).label("score")
        rows = await session.execute(
            select(Chunk.id, score)
            .where(
                Chunk.chunking_run_id == chunking_run_id,
                Chunk.lane == lane,
                Chunk.search_vector.op("@@")(tsquery),
            )
            .order_by(score.desc(), Chunk.ordinal)
            .limit(limit)
        )
        return [
            Candidate(chunk_id, lane, lexical_rank=rank, lexical_score=float(value))
            for rank, (chunk_id, value) in enumerate(rows, 1)
        ]


class DenseRetriever:
    async def search(
        self,
        session: AsyncSession,
        query_vector: list[float],
        *,
        chunking_run_id: UUID,
        embedding_model_id: UUID,
        lane: RetrievalLane,
        limit: int,
    ) -> list[Candidate]:
        distance = ChunkEmbedding.embedding.cosine_distance(query_vector).label(
            "distance"
        )
        rows = await session.execute(
            select(Chunk.id, distance)
            .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
            .where(
                Chunk.chunking_run_id == chunking_run_id,
                Chunk.lane == lane,
                ChunkEmbedding.embedding_model_id == embedding_model_id,
            )
            .order_by(distance, Chunk.ordinal)
            .limit(limit)
        )
        return [
            Candidate(
                chunk_id,
                lane,
                dense_rank=rank,
                dense_score=max(0.0, 1.0 - float(value)),
            )
            for rank, (chunk_id, value) in enumerate(rows, 1)
        ]


class EntityRetriever:
    async def search(
        self,
        session: AsyncSession,
        query: str,
        *,
        chunking_run_id: UUID,
        lane: RetrievalLane,
        limit: int,
    ) -> list[Candidate]:
        tokens = [item for item in search_tokens(query) if len(item) > 1]
        if not tokens:
            return []
        chunk_ids: list[UUID] = []
        if lane is RetrievalLane.AYIN:
            normalized_query = normalize_search_text(query)
            concept_ids = {
                concept_id
                for concept_id, stable_key in await session.execute(
                    select(AyinConcept.id, AyinConcept.stable_key)
                )
                if _label_matches(stable_key, normalized_query, tokens)
            }
            concept_ids.update(
                concept_id
                for concept_id, form in await session.execute(
                    select(Term.concept_id, TermForm.form)
                    .join(TermForm, TermForm.term_id == Term.id)
                    .where(Term.concept_id.is_not(None))
                )
                if concept_id is not None
                and _label_matches(form, normalized_query, tokens)
            )
            if concept_ids:
                chunk_ids = list(
                    await session.scalars(
                        select(ChunkAyinConcept.chunk_id)
                        .join(Chunk, Chunk.id == ChunkAyinConcept.chunk_id)
                        .where(
                            Chunk.chunking_run_id == chunking_run_id,
                            ChunkAyinConcept.concept_id.in_(concept_ids),
                        )
                        .order_by(Chunk.ordinal)
                        .limit(limit)
                    )
                )
        elif lane is RetrievalLane.EXTERNAL:
            labels = list(
                await session.scalars(
                    select(EntityLabel).where(
                        or_(
                            *[
                                func.lower(EntityLabel.normalized_label).contains(token)
                                for token in tokens
                            ]
                        )
                    )
                )
            )
            conditions = []
            for label in labels:
                if label.person_id:
                    conditions.append(ChunkExternalEntity.person_id == label.person_id)
                if label.work_id:
                    conditions.append(ChunkExternalEntity.work_id == label.work_id)
                if label.organization_id:
                    conditions.append(
                        ChunkExternalEntity.organization_id == label.organization_id
                    )
                if label.concept_id:
                    conditions.append(
                        ChunkExternalEntity.concept_id == label.concept_id
                    )
            if conditions:
                chunk_ids = list(
                    await session.scalars(
                        select(ChunkExternalEntity.chunk_id)
                        .join(Chunk, Chunk.id == ChunkExternalEntity.chunk_id)
                        .where(
                            Chunk.chunking_run_id == chunking_run_id,
                            or_(*conditions),
                        )
                        .distinct()
                        .order_by(Chunk.ordinal)
                        .limit(limit)
                    )
                )
        else:
            chunk_ids = list(
                await session.scalars(
                    select(Chunk.id)
                    .where(
                        Chunk.chunking_run_id == chunking_run_id,
                        Chunk.lane == lane,
                        or_(
                            *[Chunk.normalized_text.contains(token) for token in tokens]
                        ),
                    )
                    .order_by(Chunk.ordinal)
                    .limit(limit)
                )
            )
        return [
            Candidate(value, lane, entity_rank=rank, entity_score=1.0 / rank)
            for rank, value in enumerate(dict.fromkeys(chunk_ids), 1)
        ]


def _label_matches(label: str, query: str, tokens: list[str]) -> bool:
    normalized = normalize_search_text(label)
    return bool(normalized) and (
        normalized in query
        or any(normalized in token or token in normalized for token in tokens)
    )


class FusionService:
    def __init__(self, *, rrf_k: int = 60) -> None:
        if rrf_k <= 0:
            raise ValueError("rrf_k must be positive")
        self._k = rrf_k

    def fuse(self, lists: list[list[Candidate]], limit: int) -> list[Candidate]:
        merged: dict[UUID, Candidate] = {}
        for candidates in lists:
            for item in candidates:
                current = merged.get(item.chunk_id, Candidate(item.chunk_id, item.lane))
                score = current.fusion_score
                for rank in (item.lexical_rank, item.dense_rank, item.entity_rank):
                    if rank is not None:
                        score += 1.0 / (self._k + rank)
                merged[item.chunk_id] = replace(
                    current,
                    lexical_rank=item.lexical_rank or current.lexical_rank,
                    lexical_score=item.lexical_score
                    if item.lexical_score is not None
                    else current.lexical_score,
                    dense_rank=item.dense_rank or current.dense_rank,
                    dense_score=item.dense_score
                    if item.dense_score is not None
                    else current.dense_score,
                    entity_rank=item.entity_rank or current.entity_rank,
                    entity_score=item.entity_score
                    if item.entity_score is not None
                    else current.entity_score,
                    fusion_score=score,
                )
        return sorted(
            merged.values(), key=lambda item: (-item.fusion_score, str(item.chunk_id))
        )[:limit]


class DeterministicReranker:
    """Rerank fused candidates without hidden model or network side effects."""

    async def rerank(
        self,
        session: AsyncSession,
        query: str,
        candidates: list[Candidate],
        *,
        limit: int,
    ) -> list[Candidate]:
        if not candidates:
            return []
        query_tokens = set(search_tokens(query))
        chunks = {
            item.id: item
            for item in await session.scalars(
                select(Chunk).where(
                    Chunk.id.in_([value.chunk_id for value in candidates])
                )
            )
        }
        max_fusion = max(value.fusion_score for value in candidates) or 1.0
        output: list[Candidate] = []
        for item in candidates:
            chunk_tokens = set(search_tokens(chunks[item.chunk_id].normalized_text))
            overlap = len(query_tokens & chunk_tokens) / max(1, len(query_tokens))
            signals = [
                value
                for value in (item.lexical_score, item.dense_score, item.entity_score)
                if value is not None
            ]
            signal = max(signals, default=0.0)
            score = (
                0.55 * (item.fusion_score / max_fusion) + 0.25 * overlap + 0.20 * signal
            )
            output.append(replace(item, reranker_score=score))
        return sorted(
            output, key=lambda item: (-item.reranker_score, str(item.chunk_id))
        )[:limit]
