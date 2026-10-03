"""Synchronous post-ingestion processing pipeline (Phase 21, §19).

Single entry point used by the manual Studio action and the background
scheduler alike:

    ensure structure → validate → ensure KnowledgeUnits → validate
    → concept mapping → retrieval indexing → READY

The caller awaits this synchronously today; future queue infrastructure can
call the same service without changing the pipeline semantics. State
transitions live on ``SourceProcessingState`` — the one authoritative
post-ingestion state machine.
"""

import logging
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select

from app.db.session import Database
from app.knowledge.llm.base import LLMProvider
from app.knowledge.models import SourceVersion
from app.knowledge.structure.domain import SourceProcessingStatus
from app.knowledge.structure.models import SourceProcessingState
from app.knowledge.structure.service import SourceStructureService
from app.knowledge.units.mapping_service import ConceptMappingService
from app.knowledge.units.service import KnowledgeUnitService
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.unit_retrieval import UnitEmbeddingService

logger = logging.getLogger(__name__)


class SourceProcessingService:
    """Drive one source through structure, units, concepts, and indexing."""

    def __init__(
        self,
        database: Database,
        provider: LLMProvider | None = None,
        *,
        model: str = "configured-default",
        window_size: int = 120,
        overlap: int = 16,
        batch_size: int = 10,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.database = database
        self.embedding_provider = embedding_provider
        self.structures = SourceStructureService(
            database,
            provider=provider,
            model=model,
            window_size=window_size,
            overlap=overlap,
        )
        self.units = KnowledgeUnitService(
            database,
            provider=provider,
            model=model,
            batch_size=batch_size,
        )
        self.concepts = ConceptMappingService(
            database,
            provider=provider,
            model=model,
        )

    async def process_source(
        self,
        source_id: UUID,
        *,
        force: bool = False,
        on_progress: Callable[[str], None] | None = None,
    ) -> SourceProcessingState:
        """Structure → units → concepts → index → READY.

        Every stage is idempotent: a retry reuses succeeded extraction
        runs and existing concept links, so a mapping/indexing failure
        leaves structure and units intact and re-runs only what is
        missing.
        """

        state = await self.structures.process_source(
            source_id, force=force, on_progress=on_progress
        )
        if state.status is not SourceProcessingStatus.STRUCTURED:
            return state
        await self._mark_unit_extraction_pending(source_id)
        state = await self.units.extract_for_source(source_id)
        if state.status is not SourceProcessingStatus.READY:
            return state
        return await self._concepts_and_index(source_id, on_progress)

    async def _concepts_and_index(
        self,
        source_id: UUID,
        on_progress: Callable[[str], None] | None,
    ) -> SourceProcessingState:
        """Map unit concepts and refresh the dense index after READY.

        A provider failure here must not destroy structure or units; the
        state is marked FAILED so the scheduler's bounded retry (and
        quota classification) applies, then the caller sees the state.
        """

        async with self.database.transaction() as session:
            version_id = await session.scalar(
                select(SourceVersion.id)
                .where(SourceVersion.source_id == source_id)
                .order_by(SourceVersion.created_at.desc())
                .limit(1)
            )
        try:
            if on_progress is not None:
                on_progress("concepts")
            if version_id is not None:
                await self.concepts.map_source_units(version_id)
            if self.embedding_provider is not None and version_id is not None:
                if on_progress is not None:
                    on_progress("indexing")
                await UnitEmbeddingService(
                    self.database, self.embedding_provider
                ).build(version_id)
        except Exception as exc:
            logger.exception(
                "source_processing.concepts_failed",
                extra={"source_id": str(source_id)},
            )
            async with self.database.transaction() as session:
                failed = await session.get(SourceProcessingState, source_id)
                if failed is not None:
                    failed.status = SourceProcessingStatus.FAILED
                    failed.last_error = str(exc)[:2000]
                    failed.attempt_count += 1
                    return failed
            raise

        async with self.database.transaction() as session:
            state = await session.get(SourceProcessingState, source_id)
            if state is None:
                raise LookupError(f"Missing processing state for {source_id}")
            return state

    async def _mark_unit_extraction_pending(self, source_id: UUID) -> None:
        async with self.database.transaction() as session:
            state = await session.get(SourceProcessingState, source_id)
            if state is not None:
                state.status = SourceProcessingStatus.UNIT_EXTRACTION_PENDING
