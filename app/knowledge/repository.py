"""Focused persistence helpers for external source identity and cache lookup."""

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.models import (
    Channel,
    Creator,
    ExtractionRun,
    ExtractionWindow,
    Source,
    SourceVersion,
    WindowResult,
)


class KnowledgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def source(self, platform: str, external_id: str) -> Source | None:
        return cast(
            Source | None,
            await self._session.scalar(
                select(Source).where(
                    Source.platform == platform, Source.external_id == external_id
                )
            ),
        )

    async def source_version(
        self, source_id: UUID, content_hash: str
    ) -> SourceVersion | None:
        return cast(
            SourceVersion | None,
            await self._session.scalar(
                select(SourceVersion).where(
                    SourceVersion.source_id == source_id,
                    SourceVersion.content_hash == content_hash,
                )
            ),
        )

    async def channel(self, platform: str, external_id: str) -> Channel | None:
        return cast(
            Channel | None,
            await self._session.scalar(
                select(Channel).where(
                    Channel.platform == platform, Channel.external_id == external_id
                )
            ),
        )

    async def creator(self, canonical_name: str) -> Creator | None:
        return cast(
            Creator | None,
            await self._session.scalar(
                select(Creator).where(Creator.canonical_name == canonical_name)
            ),
        )

    async def run(
        self,
        source_version_id: UUID,
        *,
        task: str,
        provider: str,
        model: str,
        prompt_version: str,
        configuration_hash: str,
    ) -> ExtractionRun | None:
        return cast(
            ExtractionRun | None,
            await self._session.scalar(
                select(ExtractionRun).where(
                    ExtractionRun.source_version_id == source_version_id,
                    ExtractionRun.task == task,
                    ExtractionRun.provider == provider,
                    ExtractionRun.model == model,
                    ExtractionRun.prompt_version == prompt_version,
                    ExtractionRun.configuration_hash == configuration_hash,
                )
            ),
        )

    async def window(
        self,
        source_version_id: UUID,
        sequence: int,
        window_size: int,
        overlap: int,
    ) -> ExtractionWindow | None:
        return cast(
            ExtractionWindow | None,
            await self._session.scalar(
                select(ExtractionWindow).where(
                    ExtractionWindow.source_version_id == source_version_id,
                    ExtractionWindow.sequence == sequence,
                    ExtractionWindow.window_size == window_size,
                    ExtractionWindow.overlap == overlap,
                )
            ),
        )

    async def result(
        self, extraction_run_id: UUID, window_id: UUID
    ) -> WindowResult | None:
        return cast(
            WindowResult | None,
            await self._session.scalar(
                select(WindowResult).where(
                    WindowResult.extraction_run_id == extraction_run_id,
                    WindowResult.window_id == window_id,
                )
            ),
        )
