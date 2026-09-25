"""Hierarchy-aware expansion of external retrieval hits."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.semantic_content.domain import ContextExpansionMode
from app.semantic_content.models import (
    PreferredSemanticStructureRun,
    SemanticNode,
    SemanticNodeSegment,
)


@dataclass(frozen=True, slots=True)
class ExpandedSemanticContext:
    hit_node_id: UUID | None
    hit_path: str | None
    root_node_id: UUID | None
    root_path: str | None
    nodes: list[dict[str, object]]


class SemanticContextExpander:
    """Map raw segment hits to the preferred hierarchy and expand their family."""

    async def expand(
        self,
        session: AsyncSession,
        *,
        source_version_id: UUID,
        source_segment_ids: list[UUID],
        mode: ContextExpansionMode,
    ) -> ExpandedSemanticContext:
        preferred = await session.get(PreferredSemanticStructureRun, source_version_id)
        if preferred is None or not source_segment_ids:
            return ExpandedSemanticContext(None, None, None, None, [])
        candidates = list(
            await session.scalars(
                select(SemanticNode)
                .join(
                    SemanticNodeSegment,
                    SemanticNodeSegment.semantic_node_id == SemanticNode.id,
                )
                .where(
                    SemanticNode.semantic_structure_run_id
                    == preferred.semantic_structure_run_id,
                    SemanticNodeSegment.source_segment_id.in_(source_segment_ids),
                )
                .order_by(SemanticNode.depth.desc(), SemanticNode.ordinal)
            )
        )
        if not candidates:
            return ExpandedSemanticContext(None, None, None, None, [])
        hit = candidates[0]
        if mode is ContextExpansionMode.HIT_ONLY:
            selected = [hit]
            root = hit
        else:
            lineage = await self._lineage(session, hit)
            root = lineage[0]
            if mode is ContextExpansionMode.ANCESTORS:
                selected = lineage
            else:
                selected = list(
                    await session.scalars(
                        select(SemanticNode)
                        .where(
                            SemanticNode.semantic_structure_run_id
                            == preferred.semantic_structure_run_id,
                            or_(
                                SemanticNode.path == root.path,
                                SemanticNode.path.startswith(f"{root.path}."),
                            ),
                        )
                        .order_by(SemanticNode.ordinal)
                    )
                )
        return ExpandedSemanticContext(
            hit_node_id=hit.id,
            hit_path=hit.path,
            root_node_id=root.id,
            root_path=root.path,
            nodes=[self._node_payload(item) for item in selected],
        )

    @staticmethod
    async def _lineage(session: AsyncSession, node: SemanticNode) -> list[SemanticNode]:
        result = [node]
        current = node
        while current.parent_id is not None:
            parent = await session.get(SemanticNode, current.parent_id)
            if parent is None:
                break
            result.append(parent)
            current = parent
        result.reverse()
        return result

    @staticmethod
    def _node_payload(node: SemanticNode) -> dict[str, object]:
        return {
            "id": str(node.id),
            "path": node.path,
            "depth": node.depth,
            "title": node.title,
            "summary": node.summary,
            "main_idea": node.main_idea,
            "claims": node.claims,
            "definitions": node.definitions,
            "examples": node.examples,
            "qualifications": node.qualifications,
            "start_seconds": float(node.start_seconds),
            "end_seconds": float(node.end_seconds),
        }
