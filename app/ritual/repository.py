"""Focused ritual identity lookups within caller-owned transactions."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ayin.domain import CorpusZone
from app.ritual.models import (
    RitualDocument,
    RitualExtractionRun,
    RitualSourceVersion,
)


class RitualRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def document_by_slug(self, slug: str) -> RitualDocument | None:
        result = await self.session.execute(
            select(RitualDocument).where(RitualDocument.slug == slug)
        )
        return result.scalar_one_or_none()

    async def version_by_source(
        self, document_id: UUID, source_hash: str
    ) -> RitualSourceVersion | None:
        result = await self.session.execute(
            select(RitualSourceVersion).where(
                RitualSourceVersion.document_id == document_id,
                RitualSourceVersion.source_file_hash == source_hash,
                RitualSourceVersion.corpus_zone == CorpusZone.MANASEK_WORKING,
                RitualSourceVersion.semantic_version.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def run_by_identity(
        self,
        source_version_id: UUID,
        *,
        importer_version: str,
        extractor_name: str,
        extractor_version: str,
        normalization_version: str,
        segmentation_version: str,
        configuration_hash: str,
    ) -> RitualExtractionRun | None:
        result = await self.session.execute(
            select(RitualExtractionRun).where(
                RitualExtractionRun.source_version_id == source_version_id,
                RitualExtractionRun.importer_version == importer_version,
                RitualExtractionRun.extractor_name == extractor_name,
                RitualExtractionRun.extractor_version == extractor_version,
                RitualExtractionRun.normalization_version == normalization_version,
                RitualExtractionRun.segmentation_version == segmentation_version,
                RitualExtractionRun.configuration_hash == configuration_hash,
            )
        )
        return result.scalar_one_or_none()
