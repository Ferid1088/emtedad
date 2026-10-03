"""Synchronous post-ingestion processing pipeline (Phase 21, §19).

Single entry point used by the manual Studio action and the background
scheduler alike:

    ensure structure → validate → ensure KnowledgeUnits → validate → READY

The caller awaits this synchronously today; future queue infrastructure can
call the same service without changing the pipeline semantics. State
transitions live on ``SourceProcessingState`` — the one authoritative
post-ingestion state machine.
"""

import logging
from collections.abc import Callable
from uuid import UUID

from app.db.session import Database
from app.knowledge.llm.base import LLMProvider
from app.knowledge.structure.domain import SourceProcessingStatus
from app.knowledge.structure.models import SourceProcessingState
from app.knowledge.structure.service import SourceStructureService
from app.knowledge.units.service import KnowledgeUnitService

logger = logging.getLogger(__name__)


class SourceProcessingService:
    """Drive one source through structure extraction and unit extraction."""

    def __init__(
        self,
        database: Database,
        provider: LLMProvider | None = None,
        *,
        model: str = "configured-default",
        window_size: int = 120,
        overlap: int = 16,
        batch_size: int = 10,
    ) -> None:
        self.database = database
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

    async def process_source(
        self,
        source_id: UUID,
        *,
        force: bool = False,
        on_progress: Callable[[str], None] | None = None,
    ) -> SourceProcessingState:
        """Structure → units → READY; stops at review/failure states."""

        state = await self.structures.process_source(
            source_id, force=force, on_progress=on_progress
        )
        if state.status is not SourceProcessingStatus.STRUCTURED:
            return state
        await self._mark_unit_extraction_pending(source_id)
        return await self.units.extract_for_source(source_id)

    async def _mark_unit_extraction_pending(self, source_id: UUID) -> None:
        async with self.database.transaction() as session:
            state = await session.get(SourceProcessingState, source_id)
            if state is not None:
                state.status = SourceProcessingStatus.UNIT_EXTRACTION_PENDING
