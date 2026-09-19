"""Structural validation for immutable chunks and complete source membership."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval.domain import RetrievalSourceKind
from app.retrieval.models import (
    Chunk,
    ChunkCanonPassage,
    ChunkEmbedding,
    ChunkExternalSegment,
    ChunkRitualPassage,
    ChunkRitualVersion,
)


@dataclass(frozen=True, slots=True)
class RetrievalValidationResult:
    valid: bool
    chunk_count: int
    embedding_count: int
    issues: list[str]


class RetrievalStructuralValidator:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def validate(
        self, chunking_run_id: UUID, embedding_model_id: UUID | None = None
    ) -> RetrievalValidationResult:
        chunks = list(
            await self._session.scalars(
                select(Chunk).where(Chunk.chunking_run_id == chunking_run_id)
            )
        )
        issues: list[str] = []
        for chunk in chunks:
            memberships = await self._membership_counts(chunk.id)
            valid_membership = {
                RetrievalSourceKind.AYIN_PASSAGE: (
                    memberships["ayin"] > 0
                    and memberships["ritual_passage"] == 0
                    and memberships["ritual_content"] == 0
                    and memberships["external"] == 0
                ),
                RetrievalSourceKind.RITUAL_PASSAGE: (
                    memberships["ayin"] == 0
                    and memberships["ritual_passage"] > 0
                    and memberships["external"] == 0
                ),
                RetrievalSourceKind.RITUAL_CONTENT: (
                    memberships["ayin"] == 0
                    and memberships["ritual_passage"] == 0
                    and memberships["ritual_content"] > 0
                    and memberships["external"] == 0
                ),
                RetrievalSourceKind.EXTERNAL_SEGMENT: (
                    memberships["ayin"] == 0
                    and memberships["ritual_passage"] == 0
                    and memberships["ritual_content"] == 0
                    and memberships["external"] > 0
                ),
            }[chunk.source_kind]
            if not valid_membership:
                issues.append(
                    f"chunk {chunk.id} has invalid typed membership {memberships}"
                )
        embedding_count = 0
        if embedding_model_id is not None:
            embedding_count = int(
                await self._session.scalar(
                    select(func.count(ChunkEmbedding.id))
                    .join(Chunk, Chunk.id == ChunkEmbedding.chunk_id)
                    .where(
                        Chunk.chunking_run_id == chunking_run_id,
                        ChunkEmbedding.embedding_model_id == embedding_model_id,
                    )
                )
                or 0
            )
            if embedding_count != len(chunks):
                issues.append(
                    f"expected {len(chunks)} embeddings, found {embedding_count}"
                )
        return RetrievalValidationResult(
            valid=not issues,
            chunk_count=len(chunks),
            embedding_count=embedding_count,
            issues=issues,
        )

    async def _membership_counts(self, chunk_id: UUID) -> dict[str, int]:
        ayin = await self._session.scalar(
            select(func.count(ChunkCanonPassage.chunk_id)).where(
                ChunkCanonPassage.chunk_id == chunk_id
            )
        )
        ritual_passage = await self._session.scalar(
            select(func.count(ChunkRitualPassage.chunk_id)).where(
                ChunkRitualPassage.chunk_id == chunk_id
            )
        )
        ritual_content = await self._session.scalar(
            select(func.count(ChunkRitualVersion.chunk_id)).where(
                ChunkRitualVersion.chunk_id == chunk_id
            )
        )
        external = await self._session.scalar(
            select(func.count(ChunkExternalSegment.chunk_id)).where(
                ChunkExternalSegment.chunk_id == chunk_id
            )
        )
        return {
            "ayin": int(ayin or 0),
            "ritual_passage": int(ritual_passage or 0),
            "ritual_content": int(ritual_content or 0),
            "external": int(external or 0),
        }
