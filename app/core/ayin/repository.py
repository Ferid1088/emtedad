"""Persistence queries for Ayin data; repositories never commit."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ayin.models import (
    AyinConcept,
    AyinDistinction,
    AyinOpenQuestion,
    AyinPrinciple,
    AyinRelation,
    CanonDocument,
    CanonPassage,
    CanonVersion,
)
from app.core.terminology.models import Term


class AyinRepository:
    """Focused Ayin reads and identity lookups within a caller transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def document_by_slug(self, slug: str) -> CanonDocument | None:
        result = await self.session.execute(
            select(CanonDocument).where(CanonDocument.slug == slug)
        )
        return result.scalar_one_or_none()

    async def version_by_import_identity(
        self, document_id: object, source_hash: str, importer_version: str
    ) -> CanonVersion | None:
        result = await self.session.execute(
            select(CanonVersion).where(
                CanonVersion.document_id == document_id,
                CanonVersion.source_file_hash == source_hash,
                CanonVersion.importer_version == importer_version,
            )
        )
        return result.scalar_one_or_none()

    async def list_documents(self) -> Sequence[CanonDocument]:
        result = await self.session.scalars(
            select(CanonDocument).order_by(CanonDocument.created_at)
        )
        return result.all()

    async def document(self, document_id: object) -> CanonDocument | None:
        return await self.session.get(CanonDocument, document_id)

    async def list_concepts(self) -> Sequence[AyinConcept]:
        result = await self.session.scalars(
            select(AyinConcept).order_by(AyinConcept.stable_key)
        )
        return result.all()

    async def concept(self, stable_key: str) -> AyinConcept | None:
        result = await self.session.execute(
            select(AyinConcept).where(AyinConcept.stable_key == stable_key)
        )
        return result.scalar_one_or_none()

    async def list_distinctions(self) -> Sequence[AyinDistinction]:
        result = await self.session.scalars(
            select(AyinDistinction).order_by(AyinDistinction.stable_key)
        )
        return result.all()

    async def list_relations(self) -> Sequence[AyinRelation]:
        result = await self.session.scalars(
            select(AyinRelation).order_by(
                AyinRelation.subject_concept_id,
                AyinRelation.object_concept_id,
            )
        )
        return result.all()

    async def list_principles(self) -> Sequence[AyinPrinciple]:
        result = await self.session.scalars(
            select(AyinPrinciple).order_by(AyinPrinciple.stable_key)
        )
        return result.all()

    async def list_open_questions(self) -> Sequence[AyinOpenQuestion]:
        result = await self.session.scalars(
            select(AyinOpenQuestion).order_by(AyinOpenQuestion.stable_key)
        )
        return result.all()

    async def list_terms(self) -> Sequence[Term]:
        result = await self.session.scalars(select(Term).order_by(Term.stable_key))
        return result.all()

    async def passage_count(self, version_id: object) -> int:
        result = await self.session.scalars(
            select(CanonPassage.id).where(CanonPassage.canon_version_id == version_id)
        )
        return len(result.all())
