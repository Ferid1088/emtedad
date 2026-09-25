"""End-to-end preparation of external sources for semantic RAG."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from app.db.session import Database
from app.knowledge.adapters.base import SourceAdapter
from app.knowledge.importer import ExternalImportResult, ExternalKnowledgeImporter
from app.knowledge.llm.base import LLMProvider
from app.knowledge.media import MediaService
from app.knowledge.models import SourceVersion
from app.retrieval.chunking import ChunkBuilder, ChunkingResult
from app.retrieval.embeddings import (
    EmbeddingBuildResult,
    EmbeddingProvider,
    EmbeddingService,
)
from app.semantic_content.schemas import SemanticStructureRequest, SemanticTreeRead
from app.semantic_content.structuring import SemanticStructureService


@dataclass(frozen=True, slots=True)
class SemanticSourcePreparationResult:
    """One source after immutable ingestion and semantic structuring."""

    source_id: UUID
    source_version_id: UUID
    semantic_structure_run_id: UUID
    semantic_node_count: int
    failed_extraction_windows: int


@dataclass(frozen=True, slots=True)
class SemanticKnowledgePreparationResult:
    """Stable IDs produced after one source and the retrieval index are ready."""

    source_id: UUID
    source_version_id: UUID
    semantic_structure_run_id: UUID
    semantic_node_count: int
    chunking_run_id: UUID
    embedding_model_id: UUID
    failed_extraction_windows: int


@dataclass(frozen=True, slots=True)
class SemanticBackfillResult:
    """Summary for preparing already stored transcript source versions."""

    attempted_source_versions: int
    succeeded_source_versions: int
    semantic_node_count: int
    failed_source_version_ids: tuple[UUID, ...]
    chunking_run_id: UUID
    embedding_model_id: UUID


class SemanticKnowledgePipeline:
    """Ingest/structure sources and refresh the searchable index efficiently."""

    def __init__(
        self,
        database: Database,
        adapter: SourceAdapter,
        llm_provider: LLMProvider,
        embedding_provider: EmbeddingProvider,
        *,
        model: str = "configured-default",
        extraction_window_size: int = 50,
        extraction_overlap: int = 8,
        semantic_window_characters: int = 28_000,
        semantic_overlap_segments: int = 8,
        media_service: MediaService | None = None,
    ) -> None:
        self._database = database
        self._adapter = adapter
        self._llm = llm_provider
        self._embedding = embedding_provider
        self._model = model
        self._extraction_window_size = extraction_window_size
        self._extraction_overlap = extraction_overlap
        self._semantic_window_characters = semantic_window_characters
        self._semantic_overlap_segments = semantic_overlap_segments
        self._media = media_service

    async def ingest(self, locator: str) -> SemanticKnowledgePreparationResult:
        """Prepare one source and refresh retrieval once."""

        source = await self.ingest_source(locator)
        chunks, embeddings = await self.refresh_index()
        return SemanticKnowledgePreparationResult(
            source_id=source.source_id,
            source_version_id=source.source_version_id,
            semantic_structure_run_id=source.semantic_structure_run_id,
            semantic_node_count=source.semantic_node_count,
            chunking_run_id=chunks.run_id,
            embedding_model_id=embeddings.model_id,
            failed_extraction_windows=source.failed_extraction_windows,
        )

    async def ingest_source(self, locator: str) -> SemanticSourcePreparationResult:
        """Ingest and semantically structure without rebuilding the global index."""

        imported = await ExternalKnowledgeImporter(
            self._database,
            self._adapter,
            self._llm,
            model=self._model,
            window_size=self._extraction_window_size,
            overlap=self._extraction_overlap,
            media_service=self._media,
        ).ingest(locator)
        return await self.structure_import(imported)

    async def structure_import(
        self, imported: ExternalImportResult
    ) -> SemanticSourcePreparationResult:
        """Build the preferred semantic tree for one already imported version."""

        semantic = await self._structure_version(imported.source_version_id)
        return SemanticSourcePreparationResult(
            source_id=imported.source_id,
            source_version_id=imported.source_version_id,
            semantic_structure_run_id=semantic.run.id,
            semantic_node_count=semantic.run.node_count,
            failed_extraction_windows=imported.failed_windows,
        )

    async def refresh_index(
        self,
    ) -> tuple[ChunkingResult, EmbeddingBuildResult]:
        """Rebuild logical chunks once; embedding cache prevents duplicate work."""

        chunks = await ChunkBuilder(self._database).build()
        embeddings = await EmbeddingService(
            self._database, self._embedding
        ).build(chunks.run_id)
        return chunks, embeddings

    async def backfill_existing(
        self, *, include_historical: bool = False
    ) -> SemanticBackfillResult:
        """Create semantic trees for stored transcripts, then refresh index once."""

        async with self._database.transaction() as session:
            versions = list(
                await session.scalars(
                    select(SourceVersion).order_by(
                        SourceVersion.source_id,
                        SourceVersion.acquired_at.desc(),
                        SourceVersion.created_at.desc(),
                    )
                )
            )
        if not versions:
            raise ValueError("no external source versions available")

        selected: list[SourceVersion] = []
        seen_sources: set[UUID] = set()
        for version in versions:
            if include_historical or version.source_id not in seen_sources:
                selected.append(version)
                seen_sources.add(version.source_id)

        succeeded = 0
        node_count = 0
        failures: list[UUID] = []
        for version in selected:
            try:
                semantic = await self._structure_version(version.id)
            except Exception:
                failures.append(version.id)
                continue
            succeeded += 1
            node_count += semantic.run.node_count

        chunks, embeddings = await self.refresh_index()
        return SemanticBackfillResult(
            attempted_source_versions=len(selected),
            succeeded_source_versions=succeeded,
            semantic_node_count=node_count,
            failed_source_version_ids=tuple(failures),
            chunking_run_id=chunks.run_id,
            embedding_model_id=embeddings.model_id,
        )

    async def _structure_version(self, source_version_id: UUID) -> SemanticTreeRead:
        return await SemanticStructureService(
            self._database, self._llm
        ).build(
            source_version_id,
            SemanticStructureRequest(
                model=self._model,
                max_window_characters=self._semantic_window_characters,
                overlap_segments=self._semantic_overlap_segments,
                make_preferred=True,
            ),
        )
