"""Replaceable multilingual embedding boundary and idempotent persistence."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import select

from app.core.ayin.provenance import configuration_hash
from app.db.session import Database
from app.retrieval.domain import BuildStatus, DistanceMetric
from app.retrieval.models import (
    Chunk,
    ChunkEmbedding,
    EmbeddingModel,
    EmbeddingRun,
)

DEFAULT_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_REVISION = "614241f"
DEFAULT_DIMENSIONS = 384


class EmbeddingProvider(Protocol):
    provider_name: str
    model_name: str
    revision: str
    dimensions: int

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed source text in stable input order."""

    async def embed_query(self, text: str) -> list[float]:
        """Embed one search query."""


class SentenceTransformerEmbeddingProvider:
    """Pinned multilingual E5 provider with normalized cosine vectors."""

    provider_name = "sentence-transformers"

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_MODEL,
        revision: str = DEFAULT_REVISION,
        dimensions: int = DEFAULT_DIMENSIONS,
        cache_folder: Path | None = None,
        batch_size: int = 32,
    ) -> None:
        self.model_name = model_name
        self.revision = revision
        self.dimensions = dimensions
        self._cache_folder = cache_folder
        self._batch_size = batch_size
        self._model: object | None = None

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await asyncio.to_thread(
            self._encode, [f"passage: {value}" for value in texts]
        )

    async def embed_query(self, text: str) -> list[float]:
        values = await asyncio.to_thread(self._encode, [f"query: {text}"])
        return values[0]

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        from sentence_transformers import SentenceTransformer

        if self._model is None:
            self._model = SentenceTransformer(
                self.model_name,
                revision=self.revision,
                cache_folder=str(self._cache_folder) if self._cache_folder else None,
                trust_remote_code=False,
            )
        model = cast(SentenceTransformer, self._model)
        encoded = model.encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        vectors = cast(list[list[float]], encoded.tolist())
        if any(len(vector) != self.dimensions for vector in vectors):
            raise ValueError("embedding provider returned an unexpected dimension")
        return vectors


@dataclass(frozen=True, slots=True)
class EmbeddingBuildResult:
    run_id: UUID
    model_id: UUID
    embedded_count: int
    cache_hit_count: int
    created: bool


class EmbeddingService:
    def __init__(
        self,
        database: Database,
        provider: EmbeddingProvider,
        *,
        batch_size: int = 32,
    ) -> None:
        self._database = database
        self._provider = provider
        self._batch_size = batch_size

    async def build(self, chunking_run_id: UUID) -> EmbeddingBuildResult:
        model_id = await self._ensure_model()
        configuration: dict[str, object] = {
            "batch_size": self._batch_size,
            "query_prefix": "query: ",
            "document_prefix": "passage: ",
            "normalize_embeddings": True,
        }
        config_hash = configuration_hash(configuration)
        async with self._database.transaction() as session:
            existing_run = await session.scalar(
                select(EmbeddingRun).where(
                    EmbeddingRun.chunking_run_id == chunking_run_id,
                    EmbeddingRun.embedding_model_id == model_id,
                    EmbeddingRun.configuration_hash == config_hash,
                )
            )
            if (
                existing_run is not None
                and existing_run.status == BuildStatus.SUCCEEDED
            ):
                return EmbeddingBuildResult(
                    existing_run.id,
                    model_id,
                    existing_run.embedded_count,
                    existing_run.cache_hit_count,
                    False,
                )
            if existing_run is None:
                run = EmbeddingRun(
                    chunking_run_id=chunking_run_id,
                    embedding_model_id=model_id,
                    configuration_hash=config_hash,
                    configuration=configuration,
                    status=BuildStatus.RUNNING,
                )
                session.add(run)
            else:
                run = existing_run
                run.status = BuildStatus.RUNNING
            await session.flush()
            run_id = run.id
            chunks = list(
                await session.scalars(
                    select(Chunk)
                    .where(Chunk.chunking_run_id == chunking_run_id)
                    .order_by(Chunk.ordinal)
                )
            )

        async with self._database.transaction() as session:
            completed_chunk_ids = set(
                await session.scalars(
                    select(ChunkEmbedding.chunk_id).where(
                        ChunkEmbedding.embedding_run_id == run_id
                    )
                )
            )

        cache_hits = 0
        misses: list[Chunk] = []
        async with self._database.transaction() as session:
            for chunk in chunks:
                if chunk.id in completed_chunk_ids:
                    continue
                cached = await session.scalar(
                    select(ChunkEmbedding).where(
                        ChunkEmbedding.embedding_model_id == model_id,
                        ChunkEmbedding.content_hash == chunk.content_hash,
                        ChunkEmbedding.chunk_id != chunk.id,
                    )
                )
                if cached is None:
                    misses.append(chunk)
                    continue
                cache_hits += 1
                session.add(
                    ChunkEmbedding(
                        chunk_id=chunk.id,
                        embedding_model_id=model_id,
                        embedding_run_id=run_id,
                        content_hash=chunk.content_hash,
                        embedding=list(cached.embedding),
                    )
                )

        embedded = len(completed_chunk_ids)
        for start in range(0, len(misses), self._batch_size):
            batch = misses[start : start + self._batch_size]
            try:
                vectors = await self._provider.embed_documents(
                    [item.normalized_text for item in batch]
                )
            except Exception:
                await self._mark_failed(run_id)
                raise
            if len(vectors) != len(batch):
                await self._mark_failed(run_id)
                raise ValueError("embedding provider changed batch cardinality")
            try:
                async with self._database.transaction() as session:
                    session.add_all(
                        [
                            ChunkEmbedding(
                                chunk_id=chunk.id,
                                embedding_model_id=model_id,
                                embedding_run_id=run_id,
                                content_hash=chunk.content_hash,
                                embedding=vector,
                            )
                            for chunk, vector in zip(batch, vectors, strict=True)
                        ]
                    )
            except Exception:
                await self._mark_failed(run_id)
                raise
            embedded += len(batch)

        async with self._database.transaction() as session:
            completed_run = await session.get(EmbeddingRun, run_id)
            if completed_run is None:
                raise RuntimeError("embedding run disappeared")
            completed_run.embedded_count = embedded
            completed_run.cache_hit_count = cache_hits
            completed_run.status = BuildStatus.SUCCEEDED
            completed_run.completed_at = datetime.now(UTC)
        return EmbeddingBuildResult(run_id, model_id, embedded, cache_hits, True)

    async def _mark_failed(self, run_id: UUID) -> None:
        async with self._database.transaction() as session:
            run = await session.get(EmbeddingRun, run_id)
            if run is not None:
                run.status = BuildStatus.FAILED
                run.completed_at = datetime.now(UTC)

    async def _ensure_model(self) -> UUID:
        async with self._database.transaction() as session:
            model = await session.scalar(
                select(EmbeddingModel).where(
                    EmbeddingModel.provider == self._provider.provider_name,
                    EmbeddingModel.model_name == self._provider.model_name,
                    EmbeddingModel.revision == self._provider.revision,
                )
            )
            if model is None:
                model = EmbeddingModel(
                    provider=self._provider.provider_name,
                    model_name=self._provider.model_name,
                    revision=self._provider.revision,
                    dimensions=self._provider.dimensions,
                    distance_metric=DistanceMetric.COSINE,
                    language_capabilities=["fa", "en", "ar"],
                    parameters={"normalized": True, "prefixes": "e5"},
                    license="MIT",
                )
                session.add(model)
                await session.flush()
            elif model.dimensions != self._provider.dimensions:
                raise ValueError(
                    "registered embedding dimensions do not match provider"
                )
            return model.id
