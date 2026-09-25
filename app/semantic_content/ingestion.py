"""End-to-end preparation of newly ingested external sources for semantic RAG."""

from dataclasses import dataclass
from uuid import UUID

from app.db.session import Database
from app.knowledge.adapters.base import SourceAdapter
from app.knowledge.importer import ExternalImportResult, ExternalKnowledgeImporter
from app.knowledge.llm.base import LLMProvider
from app.knowledge.media import MediaService
from app.retrieval.chunking import ChunkBuilder, ChunkingResult
from app.retrieval.embeddings import (
    EmbeddingBuildResult,
    EmbeddingProvider,
    EmbeddingService,
)
from app.semantic_content.schemas import SemanticStructureRequest
from app.semantic_content.structuring import SemanticStructureService


@dataclass(frozen=True, slots=True)
class SemanticKnowledgePreparationResult:
    """Stable IDs produced while preparing one external source for generation."""

    source_id: UUID
    source_version_id: UUID
    semantic_structure_run_id: UUID
    semantic_node_count: int
    chunking_run_id: UUID
    embedding_model_id: UUID
    failed_extraction_windows: int


class SemanticKnowledgePipeline:
    """Ingest a source, build its semantic tree, and refresh the searchable index."""

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
        imported = await ExternalKnowledgeImporter(
            self._database,
            self._adapter,
            self._llm,
            model=self._model,
            window_size=self._extraction_window_size,
            overlap=self._extraction_overlap,
            media_service=self._media,
        ).ingest(locator)
        return await self.prepare(imported)

    async def prepare(
        self, imported: ExternalImportResult
    ) -> SemanticKnowledgePreparationResult:
        semantic = await SemanticStructureService(
            self._database, self._llm
        ).build(
            imported.source_version_id,
            SemanticStructureRequest(
                model=self._model,
                max_window_characters=self._semantic_window_characters,
                overlap_segments=self._semantic_overlap_segments,
                make_preferred=True,
            ),
        )
        chunks: ChunkingResult = await ChunkBuilder(self._database).build()
        embeddings: EmbeddingBuildResult = await EmbeddingService(
            self._database, self._embedding
        ).build(chunks.run_id)
        return SemanticKnowledgePreparationResult(
            source_id=imported.source_id,
            source_version_id=imported.source_version_id,
            semantic_structure_run_id=semantic.run.id,
            semantic_node_count=semantic.run.node_count,
            chunking_run_id=chunks.run_id,
            embedding_model_id=embeddings.model_id,
            failed_extraction_windows=imported.failed_windows,
        )
