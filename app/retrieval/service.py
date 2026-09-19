"""Lane-aware hybrid search with persisted runs and complete provenance."""

import time
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ayin.models import AyinConcept, CanonDocument, CanonPassage, CanonVersion
from app.core.ayin.provenance import configuration_hash
from app.db.session import Database
from app.knowledge.models import (
    ChannelCreator,
    Creator,
    EntityLabel,
    Source,
    SourceSegment,
    SourceVersion,
)
from app.retrieval.domain import QueryLanguage, RetrievalLane, RetrievalSourceKind
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.models import (
    Chunk,
    ChunkAyinConcept,
    ChunkCanonPassage,
    ChunkExternalEntity,
    ChunkExternalSegment,
    ChunkRitualPassage,
    ChunkRitualVersion,
    RetrievalConfiguration,
    RetrievalResult,
    RetrievalRun,
)
from app.retrieval.normalization import normalize_search_text
from app.retrieval.retrievers import (
    Candidate,
    DenseRetriever,
    DeterministicReranker,
    EntityRetriever,
    FusionService,
    LexicalRetriever,
)
from app.retrieval.schemas import RetrievalProvenance, SearchResponse, SearchResult
from app.ritual.models import (
    RitualDocument,
    RitualPassage,
    RitualSourceVersion,
    RitualVersion,
)

DEFAULT_PARAMETERS: dict[str, object] = {
    "lexical_top_n": 30,
    "dense_top_n": 30,
    "entity_top_n": 20,
    "fusion_top_n": 20,
    "lane_top_n": 5,
    "rrf_k": 60,
    "context_neighbors": 1,
    "lexical": "postgres-simple-or-v2",
    "dense": "exact-cosine-v1",
    "entity": "typed-label-v2",
    "fusion": "rrf-v1",
    "reranker": "deterministic-overlap-v1",
}


def _integer_parameter(config: dict[str, object], name: str) -> int:
    value = config[name]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


class HybridRetrievalService:
    def __init__(
        self,
        database: Database,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self._database = database
        self._provider = embedding_provider
        self._lexical = LexicalRetriever()
        self._dense = DenseRetriever()
        self._entity = EntityRetriever()
        self._reranker = DeterministicReranker()

    async def search(
        self,
        query: str,
        language: QueryLanguage,
        *,
        chunking_run_id: UUID,
        embedding_model_id: UUID,
        lanes: list[RetrievalLane] | None = None,
        parameters: dict[str, object] | None = None,
    ) -> SearchResponse:
        if not query.strip():
            raise ValueError("query cannot be empty")
        config = dict(DEFAULT_PARAMETERS)
        if parameters:
            config.update(parameters)
        requested_lanes = lanes or [
            RetrievalLane.AYIN,
            RetrievalLane.MANASEK,
            RetrievalLane.EXTERNAL,
        ]
        started = time.monotonic()
        vector = await self._provider.embed_query(normalize_search_text(query))
        await self._verify_embedding_model(embedding_model_id)
        configuration_id = await self._ensure_configuration(config)
        lane_results: dict[RetrievalLane, list[Candidate]] = {}
        async with self._database.transaction() as session:
            for lane in requested_lanes:
                lexical = await self._lexical.search(
                    session,
                    query,
                    chunking_run_id=chunking_run_id,
                    lane=lane,
                    limit=_integer_parameter(config, "lexical_top_n"),
                )
                dense = await self._dense.search(
                    session,
                    vector,
                    chunking_run_id=chunking_run_id,
                    embedding_model_id=embedding_model_id,
                    lane=lane,
                    limit=_integer_parameter(config, "dense_top_n"),
                )
                entity = await self._entity.search(
                    session,
                    query,
                    chunking_run_id=chunking_run_id,
                    lane=lane,
                    limit=_integer_parameter(config, "entity_top_n"),
                )
                fused = FusionService(rrf_k=_integer_parameter(config, "rrf_k")).fuse(
                    [lexical, dense, entity],
                    _integer_parameter(config, "fusion_top_n"),
                )
                lane_results[lane] = await self._reranker.rerank(
                    session,
                    query,
                    fused,
                    limit=_integer_parameter(config, "lane_top_n"),
                )

            ordered = self._interleave(lane_results, requested_lanes)
            run = RetrievalRun(
                chunking_run_id=chunking_run_id,
                embedding_model_id=embedding_model_id,
                configuration_id=configuration_id,
                query_text=query,
                normalized_query=normalize_search_text(query),
                language=language,
                filters={"lanes": [lane.value for lane in requested_lanes]},
                elapsed_ms=0,
            )
            session.add(run)
            await session.flush()
            results: list[SearchResult] = []
            for rank, candidate in enumerate(ordered, 1):
                result = await self._result(
                    session,
                    candidate,
                    rank,
                    context_neighbors=_integer_parameter(config, "context_neighbors"),
                )
                results.append(result)
                session.add(
                    RetrievalResult(
                        retrieval_run_id=run.id,
                        chunk_id=candidate.chunk_id,
                        lexical_rank=candidate.lexical_rank,
                        lexical_score=candidate.lexical_score,
                        dense_rank=candidate.dense_rank,
                        dense_score=candidate.dense_score,
                        entity_rank=candidate.entity_rank,
                        entity_score=candidate.entity_score,
                        fusion_score=candidate.fusion_score,
                        reranker_score=candidate.reranker_score,
                        final_rank=rank,
                        expanded_context=result.expanded_context,
                    )
                )
            elapsed_ms = int((time.monotonic() - started) * 1000)
            run.elapsed_ms = elapsed_ms
            return SearchResponse(
                retrieval_run_id=run.id,
                chunking_run_id=chunking_run_id,
                embedding_model_id=embedding_model_id,
                retrieval_configuration_id=configuration_id,
                query=query,
                language=language,
                elapsed_ms=elapsed_ms,
                results=results,
            )

    async def _ensure_configuration(self, parameters: dict[str, object]) -> UUID:
        digest = configuration_hash(parameters)
        async with self._database.transaction() as session:
            config = await session.scalar(
                select(RetrievalConfiguration).where(
                    RetrievalConfiguration.configuration_hash == digest
                )
            )
            if config is None:
                config = RetrievalConfiguration(
                    name="hybrid-lane-retrieval",
                    version=f"v1-{digest[:12]}",
                    parameters=parameters,
                    configuration_hash=digest,
                )
                session.add(config)
                await session.flush()
            return config.id

    @staticmethod
    def _interleave(
        by_lane: dict[RetrievalLane, list[Candidate]], lanes: list[RetrievalLane]
    ) -> list[Candidate]:
        output: list[Candidate] = []
        longest = max((len(by_lane.get(lane, [])) for lane in lanes), default=0)
        for index in range(longest):
            for lane in lanes:
                values = by_lane.get(lane, [])
                if index < len(values):
                    output.append(values[index])
        return output

    async def _result(
        self,
        session: AsyncSession,
        candidate: Candidate,
        rank: int,
        *,
        context_neighbors: int,
    ) -> SearchResult:
        chunk = await session.get(Chunk, candidate.chunk_id)
        if chunk is None:
            raise RuntimeError("retrieval chunk disappeared")
        context = await self._context(session, chunk, context_neighbors)
        provenance = await self._provenance(session, chunk)
        entities = await self._entity_labels(session, chunk)
        return SearchResult(
            chunk_id=chunk.id,
            chunk_content_hash=chunk.content_hash,
            text=chunk.text,
            normalized_text=chunk.normalized_text,
            language=chunk.language,
            section_title=chunk.section_title,
            matched_entities=entities,
            lexical_rank=candidate.lexical_rank,
            lexical_score=candidate.lexical_score,
            dense_rank=candidate.dense_rank,
            dense_score=candidate.dense_score,
            entity_rank=candidate.entity_rank,
            entity_score=candidate.entity_score,
            fusion_score=candidate.fusion_score,
            reranker_score=candidate.reranker_score,
            final_rank=rank,
            expanded_context=context,
            provenance=provenance,
        )

    async def _context(
        self, session: AsyncSession, chunk: Chunk, context_neighbors: int
    ) -> list[dict[str, object]]:
        neighbors = list(
            await session.scalars(
                select(Chunk)
                .where(
                    Chunk.chunking_run_id == chunk.chunking_run_id,
                    Chunk.lane == chunk.lane,
                    Chunk.source_kind == chunk.source_kind,
                    Chunk.ordinal.between(
                        chunk.ordinal - context_neighbors,
                        chunk.ordinal + context_neighbors,
                    ),
                )
                .order_by(Chunk.ordinal)
            )
        )
        identity = self._source_identity(chunk)
        return [
            {"chunk_id": str(item.id), "ordinal": item.ordinal, "text": item.text}
            for item in neighbors
            if self._source_identity(item) == identity
        ]

    @staticmethod
    def _source_identity(chunk: Chunk) -> str:
        first = chunk.metadata_json.get("first", {})
        if isinstance(first, dict):
            for key in ("canon_version_id", "source_version_id", "ritual_version_id"):
                value = first.get(key)
                if value:
                    return f"{key}:{value}"
        return str(chunk.id)

    async def _provenance(
        self, session: AsyncSession, chunk: Chunk
    ) -> RetrievalProvenance:
        if chunk.source_kind is RetrievalSourceKind.AYIN_PASSAGE:
            rows = list(
                await session.execute(
                    select(CanonPassage, CanonVersion, CanonDocument)
                    .join(
                        ChunkCanonPassage,
                        ChunkCanonPassage.canon_passage_id == CanonPassage.id,
                    )
                    .join(
                        CanonVersion, CanonVersion.id == CanonPassage.canon_version_id
                    )
                    .join(CanonDocument, CanonDocument.id == CanonVersion.document_id)
                    .where(ChunkCanonPassage.chunk_id == chunk.id)
                    .order_by(ChunkCanonPassage.sequence_in_chunk)
                )
            )
            passages = [row[0] for row in rows]
            version, document = rows[0][1], rows[0][2]
            return RetrievalProvenance(
                corpus_zone=version.corpus_zone,
                lane=chunk.lane,
                source_kind=chunk.source_kind,
                source_type="ayin_document",
                source_id=document.id,
                source_version_id=version.id,
                source_title=document.title,
                creator=None,
                source_url=None,
                record_ids=[item.id for item in passages],
                page_start=min(item.page_number for item in passages),
                page_end=max(item.page_number for item in passages),
                source_status=version.status.value,
                editorial_status=version.status.value,
            )
        if chunk.source_kind in {
            RetrievalSourceKind.RITUAL_PASSAGE,
            RetrievalSourceKind.RITUAL_CONTENT,
        }:
            if chunk.source_kind is RetrievalSourceKind.RITUAL_PASSAGE:
                rows = list(
                    await session.execute(
                        select(RitualPassage, RitualSourceVersion, RitualDocument)
                        .join(
                            ChunkRitualPassage,
                            ChunkRitualPassage.ritual_passage_id == RitualPassage.id,
                        )
                        .join(
                            RitualSourceVersion,
                            RitualSourceVersion.id == RitualPassage.source_version_id,
                        )
                        .join(
                            RitualDocument,
                            RitualDocument.id == RitualSourceVersion.document_id,
                        )
                        .where(ChunkRitualPassage.chunk_id == chunk.id)
                        .order_by(ChunkRitualPassage.sequence_in_chunk)
                    )
                )
                passages = [row[0] for row in rows]
                version, document = rows[0][1], rows[0][2]
                record_ids = [item.id for item in passages]
                page_start = min(item.page_number for item in passages)
                page_end = max(item.page_number for item in passages)
            else:
                row = (
                    await session.execute(
                        select(RitualVersion, RitualSourceVersion, RitualDocument)
                        .join(
                            ChunkRitualVersion,
                            ChunkRitualVersion.ritual_version_id == RitualVersion.id,
                        )
                        .join(
                            RitualSourceVersion,
                            RitualSourceVersion.id == RitualVersion.source_version_id,
                        )
                        .join(
                            RitualDocument,
                            RitualDocument.id == RitualSourceVersion.document_id,
                        )
                        .where(ChunkRitualVersion.chunk_id == chunk.id)
                    )
                ).one()
                ritual, version, document = row
                record_ids = [ritual.id]
                page_start = page_end = None
            return RetrievalProvenance(
                corpus_zone=version.corpus_zone,
                lane=chunk.lane,
                source_kind=chunk.source_kind,
                source_type="ritual_document",
                source_id=document.id,
                source_version_id=version.id,
                source_title=document.title,
                creator=None,
                source_url=None,
                record_ids=record_ids,
                page_start=page_start,
                page_end=page_end,
                source_status=version.status.value,
                editorial_status=version.status.value,
            )
        rows = list(
            await session.execute(
                select(SourceSegment, SourceVersion, Source)
                .join(
                    ChunkExternalSegment,
                    ChunkExternalSegment.source_segment_id == SourceSegment.id,
                )
                .join(
                    SourceVersion, SourceVersion.id == SourceSegment.source_version_id
                )
                .join(Source, Source.id == SourceVersion.source_id)
                .where(ChunkExternalSegment.chunk_id == chunk.id)
                .order_by(ChunkExternalSegment.sequence_in_chunk)
            )
        )
        segments = [row[0] for row in rows]
        version, source = rows[0][1], rows[0][2]
        creator = None
        if source.channel_id is not None:
            creator = await session.scalar(
                select(Creator.canonical_name)
                .join(ChannelCreator, ChannelCreator.creator_id == Creator.id)
                .where(ChannelCreator.channel_id == source.channel_id)
                .order_by(ChannelCreator.attribution_role, Creator.canonical_name)
                .limit(1)
            )
        return RetrievalProvenance(
            corpus_zone=version.corpus_zone,
            lane=chunk.lane,
            source_kind=chunk.source_kind,
            source_type=source.source_type.value,
            source_id=source.id,
            source_version_id=version.id,
            source_title=source.title,
            creator=creator,
            source_url=source.canonical_url,
            record_ids=[item.id for item in segments],
            timestamp_start=float(min(item.start_seconds for item in segments)),
            timestamp_end=float(max(item.end_seconds for item in segments)),
            source_status=source.ingestion_status.value,
            editorial_status=None,
        )

    async def _entity_labels(self, session: AsyncSession, chunk: Chunk) -> list[str]:
        labels: list[str] = []
        if chunk.lane is RetrievalLane.AYIN:
            labels.extend(
                await session.scalars(
                    select(AyinConcept.stable_key)
                    .join(
                        ChunkAyinConcept, ChunkAyinConcept.concept_id == AyinConcept.id
                    )
                    .where(ChunkAyinConcept.chunk_id == chunk.id)
                )
            )
        elif chunk.lane is RetrievalLane.EXTERNAL:
            entities = list(
                await session.scalars(
                    select(ChunkExternalEntity).where(
                        ChunkExternalEntity.chunk_id == chunk.id
                    )
                )
            )
            for entity in entities:
                conditions = []
                for field in ("person_id", "work_id", "organization_id", "concept_id"):
                    value = getattr(entity, field)
                    if value:
                        conditions.append(getattr(EntityLabel, field) == value)
                if conditions:
                    value = await session.scalar(
                        select(EntityLabel.label).where(or_(*conditions)).limit(1)
                    )
                    if value:
                        labels.append(value)
        return sorted(set(labels))

    async def _verify_embedding_model(self, embedding_model_id: UUID) -> None:
        from app.retrieval.models import EmbeddingModel

        async with self._database.transaction() as session:
            model = await session.get(EmbeddingModel, embedding_model_id)
            if model is None:
                raise ValueError("embedding model does not exist")
            expected = (
                self._provider.provider_name,
                self._provider.model_name,
                self._provider.revision,
                self._provider.dimensions,
            )
            actual = (
                model.provider,
                model.model_name,
                model.revision,
                model.dimensions,
            )
            if actual != expected:
                raise ValueError("embedding provider does not match persisted model")
