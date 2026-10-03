"""Persistence queries for source structure nodes and processing state."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.models import Source, SourceSegment, SourceVersion
from app.knowledge.structure.models import (
    SourceProcessingState,
    SourceStructureNode,
)


class SourceStructureRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def latest_version(self, source_id: UUID) -> SourceVersion | None:
        result: SourceVersion | None = await self.session.scalar(
            select(SourceVersion)
            .where(SourceVersion.source_id == source_id)
            .order_by(SourceVersion.created_at.desc())
            .limit(1)
        )
        return result

    async def segments(self, source_version_id: UUID) -> list[SourceSegment]:
        return list(
            await self.session.scalars(
                select(SourceSegment)
                .where(SourceSegment.source_version_id == source_version_id)
                .order_by(SourceSegment.sequence)
            )
        )

    async def nodes(self, source_version_id: UUID) -> list[SourceStructureNode]:
        return list(
            await self.session.scalars(
                select(SourceStructureNode)
                .where(SourceStructureNode.source_version_id == source_version_id)
                .order_by(
                    SourceStructureNode.level,
                    SourceStructureNode.ordinal,
                )
            )
        )

    async def node(self, node_id: UUID) -> SourceStructureNode | None:
        return await self.session.get(SourceStructureNode, node_id)

    async def node_segments(self, node: SourceStructureNode) -> list[SourceSegment]:
        start = await self.session.get(SourceSegment, node.start_segment_id)
        end = await self.session.get(SourceSegment, node.end_segment_id)
        if start is None or end is None:
            return []
        return list(
            await self.session.scalars(
                select(SourceSegment)
                .where(
                    SourceSegment.source_version_id == node.source_version_id,
                    SourceSegment.sequence >= start.sequence,
                    SourceSegment.sequence <= end.sequence,
                )
                .order_by(SourceSegment.sequence)
            )
        )

    async def replace_nodes(self, source_version_id: UUID) -> None:
        await self.session.execute(
            delete(SourceStructureNode).where(
                SourceStructureNode.source_version_id == source_version_id
            )
        )

    async def processing_state(self, source_id: UUID) -> SourceProcessingState | None:
        return await self.session.get(SourceProcessingState, source_id)

    async def ensure_processing_state(
        self, source: Source, source_version_id: UUID | None
    ) -> SourceProcessingState:
        state = await self.session.get(SourceProcessingState, source.id)
        if state is None:
            state = SourceProcessingState(
                source_id=source.id, source_version_id=source_version_id
            )
            self.session.add(state)
            await self.session.flush()
        else:
            state.source_version_id = source_version_id
        return state

    def build_tree(
        self, nodes: Sequence[SourceStructureNode]
    ) -> list[dict[str, object]]:
        by_parent: dict[UUID | None, list[SourceStructureNode]] = {}
        for node in nodes:
            by_parent.setdefault(node.parent_id, []).append(node)

        def build(node: SourceStructureNode) -> dict[str, object]:
            return {
                "id": node.id,
                "title": node.title,
                "summary": node.summary,
                "node_type": node.node_type.value,
                "level": node.level,
                "ordinal": node.ordinal,
                "start_seconds": node.start_seconds,
                "end_seconds": node.end_seconds,
                "confidence": node.confidence,
                "children": [build(child) for child in by_parent.get(node.id, [])],
            }

        return [build(node) for node in by_parent.get(None, [])]
