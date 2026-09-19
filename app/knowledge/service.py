"""Read services shared by the Phase 4 API and operator CLI."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ResourceNotFoundError
from app.knowledge.models import (
    ExternalClaim,
    Mention,
    Person,
    ReviewFlag,
    Source,
    SourceSegment,
    SourceVersion,
    Work,
)
from app.knowledge.schemas import (
    ClaimRead,
    EntityRead,
    MentionRead,
    ReviewFlagRead,
    SegmentRead,
    SourceRead,
    SourceVersionRead,
    WorkRead,
)


class KnowledgeReadService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def sources(self) -> list[SourceRead]:
        rows = await self._session.scalars(select(Source).order_by(Source.created_at))
        return [SourceRead.model_validate(row) for row in rows]

    async def source(self, source_id: UUID) -> SourceRead:
        row = await self._session.get(Source, source_id)
        if row is None:
            raise ResourceNotFoundError
        return SourceRead.model_validate(row)

    async def versions(self, source_id: UUID) -> list[SourceVersionRead]:
        rows = await self._session.scalars(
            select(SourceVersion)
            .where(SourceVersion.source_id == source_id)
            .order_by(SourceVersion.acquired_at)
        )
        return [SourceVersionRead.model_validate(row) for row in rows]

    async def segments(self, version_id: UUID) -> list[SegmentRead]:
        rows = await self._session.scalars(
            select(SourceSegment)
            .where(SourceSegment.source_version_id == version_id)
            .order_by(SourceSegment.sequence)
        )
        return [SegmentRead.model_validate(row) for row in rows]

    async def source_segments(self, source_id: UUID) -> list[SegmentRead]:
        rows = await self._session.scalars(
            select(SourceSegment)
            .join(SourceVersion, SourceVersion.id == SourceSegment.source_version_id)
            .where(SourceVersion.source_id == source_id)
            .order_by(SourceVersion.acquired_at, SourceSegment.sequence)
        )
        return [SegmentRead.model_validate(row) for row in rows]

    async def mentions(self, version_id: UUID | None = None) -> list[MentionRead]:
        statement = select(Mention).order_by(Mention.created_at)
        if version_id is not None:
            statement = statement.where(Mention.source_version_id == version_id)
        rows = await self._session.scalars(statement)
        return [MentionRead.model_validate(row) for row in rows]

    async def source_mentions(self, source_id: UUID) -> list[MentionRead]:
        rows = await self._session.scalars(
            select(Mention)
            .join(SourceVersion, SourceVersion.id == Mention.source_version_id)
            .where(SourceVersion.source_id == source_id)
            .order_by(Mention.created_at)
        )
        return [MentionRead.model_validate(row) for row in rows]

    async def claims(self, version_id: UUID | None = None) -> list[ClaimRead]:
        statement = select(ExternalClaim).order_by(ExternalClaim.created_at)
        if version_id is not None:
            statement = statement.where(ExternalClaim.source_version_id == version_id)
        rows = await self._session.scalars(statement)
        return [ClaimRead.model_validate(row) for row in rows]

    async def people(self) -> list[EntityRead]:
        rows = await self._session.scalars(
            select(Person).order_by(Person.canonical_name)
        )
        return [EntityRead.model_validate(row) for row in rows]

    async def works(self) -> list[WorkRead]:
        rows = await self._session.scalars(select(Work).order_by(Work.canonical_title))
        return [WorkRead.model_validate(row) for row in rows]

    async def person(self, person_id: UUID) -> EntityRead:
        row = await self._session.get(Person, person_id)
        if row is None:
            raise ResourceNotFoundError
        return EntityRead.model_validate(row)

    async def work(self, work_id: UUID) -> WorkRead:
        row = await self._session.get(Work, work_id)
        if row is None:
            raise ResourceNotFoundError
        return WorkRead.model_validate(row)

    async def review_queue(self) -> list[ReviewFlagRead]:
        rows = await self._session.scalars(
            select(ReviewFlag).order_by(ReviewFlag.status, ReviewFlag.created_at)
        )
        return [ReviewFlagRead.model_validate(row) for row in rows]
