"""Knowledge Unit retrieval: lexical + dense + concept lanes with fusion.

Units are the atomic retrieval objects — a hit always returns the whole unit
(never an excerpt). Optional structural expansion adds sibling/ancestor units
from the source structure as context.
"""

import hashlib
import logging
from dataclasses import dataclass, field, replace
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.knowledge.models import (
    ExternalConcept,
    Source,
    SourceSegment,
    SourceVersion,
)
from app.knowledge.structure.models import SourceStructureNode
from app.knowledge.units.models import (
    KnowledgeUnit,
    KnowledgeUnitConcept,
)
from app.knowledge.units.quality import (
    SUMMARY_ROLE,
    span_overlap_ratio,
    unit_retrieval_role,
)
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.models import EmbeddingModel, KnowledgeUnitEmbedding
from app.retrieval.normalization import normalize_search_text, search_tokens

logger = logging.getLogger(__name__)


class ExpansionMode(StrEnum):
    NONE = "NONE"
    PARENT = "PARENT"
    PARENTS = "PARENTS"
    SIBLINGS = "SIBLINGS"
    FAMILY = "FAMILY"
    SUBTREE = "SUBTREE"


@dataclass(frozen=True, slots=True)
class UnitCandidate:
    unit_id: UUID
    lexical_rank: int | None = None
    lexical_score: float | None = None
    dense_rank: int | None = None
    dense_score: float | None = None
    concept_rank: int | None = None
    concept_score: float | None = None
    fusion_score: float = 0.0
    reranker_score: float = 0.0


@dataclass(frozen=True, slots=True)
class KnowledgeUnitSearchResult:
    knowledge_unit_id: UUID
    title: str
    summary: str
    full_text: str
    unit_type: str
    atomic: bool
    matched_concepts: tuple[str, ...]
    score_components: dict[str, float]
    source_id: UUID
    source_version_id: UUID
    source_title: str
    source_url: str
    start_seconds: object | None
    end_seconds: object | None
    structure_path: tuple[str, ...]
    expanded_context: tuple[dict[str, object], ...] = field(default_factory=tuple)


class UnitEmbeddingService:
    """Embed unit summary + full_text; idempotent via content hash."""

    def __init__(
        self,
        database: Database,
        provider: EmbeddingProvider,
        *,
        batch_size: int = 32,
    ) -> None:
        self.database = database
        self.provider = provider
        self.batch_size = batch_size

    async def ensure_model_id(self) -> UUID:
        async with self.database.transaction() as session:
            model = await session.scalar(
                select(EmbeddingModel).where(
                    EmbeddingModel.provider == self.provider.provider_name,
                    EmbeddingModel.model_name == self.provider.model_name,
                    EmbeddingModel.revision == self.provider.revision,
                )
            )
            return model.id if model else await self._create_model(session)

    async def _create_model(self, session: AsyncSession) -> UUID:
        from app.retrieval.domain import DistanceMetric

        model = EmbeddingModel(
            provider=self.provider.provider_name,
            model_name=self.provider.model_name,
            revision=self.provider.revision,
            dimensions=self.provider.dimensions,
            distance_metric=DistanceMetric.COSINE,
            language_capabilities=["fa", "de", "en", "ar"],
            parameters={"normalized": True, "prefixes": "e5"},
        )
        session.add(model)
        await session.flush()
        return model.id

    async def build(self, source_version_id: UUID | None = None) -> int:
        model_id = await self.ensure_model_id()
        async with self.database.transaction() as session:
            statement = select(KnowledgeUnit)
            if source_version_id is not None:
                statement = statement.where(
                    KnowledgeUnit.source_version_id == source_version_id
                )
            units = list(await session.scalars(statement))
            existing = {
                (unit_id, kind, digest)
                for unit_id, kind, digest in (
                    await session.execute(
                        select(
                            KnowledgeUnitEmbedding.knowledge_unit_id,
                            KnowledgeUnitEmbedding.kind,
                            KnowledgeUnitEmbedding.content_hash,
                        ).where(KnowledgeUnitEmbedding.embedding_model_id == model_id)
                    )
                ).all()
            }
            pending: list[tuple[UUID, str, str, str]] = []
            for unit in units:
                for kind, text in (
                    ("SUMMARY", unit.summary),
                    ("FULL_TEXT", unit.full_text),
                ):
                    digest = hashlib.sha256(text.encode()).hexdigest()
                    if (unit.id, kind, digest) not in existing:
                        pending.append((unit.id, kind, digest, text))
        created = 0
        for start in range(0, len(pending), self.batch_size):
            batch = pending[start : start + self.batch_size]
            vectors = await self.provider.embed_documents(
                [text for _unit, _kind, _digest, text in batch]
            )
            if len(vectors) != len(batch):
                raise ValueError("embedding provider changed batch cardinality")
            async with self.database.transaction() as session:
                session.add_all(
                    [
                        KnowledgeUnitEmbedding(
                            knowledge_unit_id=unit_id,
                            embedding_model_id=model_id,
                            kind=kind,
                            content_hash=digest,
                            embedding=vector,
                        )
                        for (unit_id, kind, digest, _text), vector in zip(
                            batch, vectors, strict=True
                        )
                    ]
                )
            created += len(batch)
        logger.info(
            "knowledge_units.embedded",
            extra={"created": created, "total": len(pending)},
        )
        return created


class KnowledgeUnitSearchService:
    """Hybrid retrieval over Knowledge Units with structural expansion."""

    def __init__(
        self,
        database: Database,
        embedding_provider: EmbeddingProvider | None = None,
        *,
        rrf_k: int = 60,
    ) -> None:
        self.database = database
        self.embedding_provider = embedding_provider
        self.rrf_k = rrf_k

    async def search(
        self,
        query: str,
        *,
        expansion: ExpansionMode = ExpansionMode.NONE,
        limit: int = 20,
    ) -> list[KnowledgeUnitSearchResult]:
        async with self.database.transaction() as session:
            lists = [await self._lexical(session, query, limit=limit)]
            dense = await self._dense(session, query, limit=limit)
            if dense:
                lists.append(dense)
            concept = await self._concept_lane(session, query, limit=limit)
            if concept:
                lists.append(concept)
            fused = self._fuse(lists, limit=limit)
            ranked = await self._rerank(session, query, fused, limit=limit)
            ranked = await self._dedup_nested(session, ranked)
            return await self._hydrate(session, ranked[:limit], expansion)

    async def _lexical(
        self, session: AsyncSession, query: str, *, limit: int
    ) -> list[UnitCandidate]:
        tokens = search_tokens(query)
        if not tokens:
            return []
        tsquery = func.to_tsquery("simple", " | ".join(tokens))
        score = func.ts_rank_cd(KnowledgeUnit.search_vector, tsquery).label("s")
        rows = await session.execute(
            select(KnowledgeUnit.id, score)
            .where(KnowledgeUnit.search_vector.op("@@")(tsquery))
            .order_by(score.desc())
            .limit(limit)
        )
        return [
            UnitCandidate(unit_id, lexical_rank=rank, lexical_score=float(value))
            for rank, (unit_id, value) in enumerate(rows, 1)
        ]

    async def _dense(
        self, session: AsyncSession, query: str, *, limit: int
    ) -> list[UnitCandidate]:
        if self.embedding_provider is None:
            return []
        model = await session.scalar(
            select(EmbeddingModel).where(
                EmbeddingModel.provider == self.embedding_provider.provider_name,
                EmbeddingModel.model_name == self.embedding_provider.model_name,
                EmbeddingModel.revision == self.embedding_provider.revision,
            )
        )
        if model is None:
            return []
        vector = await self.embedding_provider.embed_query(query)
        distance = KnowledgeUnitEmbedding.embedding.cosine_distance(vector).label("d")
        rows = await session.execute(
            select(KnowledgeUnitEmbedding.knowledge_unit_id, distance)
            .where(
                KnowledgeUnitEmbedding.embedding_model_id == model.id,
                KnowledgeUnitEmbedding.kind == "FULL_TEXT",
            )
            .order_by(distance)
            .limit(limit)
        )
        return [
            UnitCandidate(
                unit_id,
                dense_rank=rank,
                dense_score=max(0.0, 1.0 - float(value)),
            )
            for rank, (unit_id, value) in enumerate(rows, 1)
        ]

    async def _concept_lane(
        self, session: AsyncSession, query: str, *, limit: int
    ) -> list[UnitCandidate]:
        tokens = [token for token in search_tokens(query) if len(token) > 1]
        if not tokens:
            return []
        concepts = list(
            await session.scalars(
                select(ExternalConcept).where(
                    or_(
                        *[
                            func.lower(ExternalConcept.normalized_name).contains(token)
                            for token in tokens
                        ]
                    )
                )
            )
        )
        if not concepts:
            return []
        unit_ids = list(
            await session.scalars(
                select(KnowledgeUnitConcept.knowledge_unit_id)
                .where(
                    KnowledgeUnitConcept.concept_id.in_([item.id for item in concepts])
                )
                .distinct()
                .limit(limit)
            )
        )
        return [
            UnitCandidate(unit_id, concept_rank=rank, concept_score=1.0 / rank)
            for rank, unit_id in enumerate(unit_ids, 1)
        ]

    def _fuse(
        self, lists: list[list[UnitCandidate]], *, limit: int
    ) -> list[UnitCandidate]:
        merged: dict[UUID, UnitCandidate] = {}
        for candidates in lists:
            for item in candidates:
                current = merged.get(item.unit_id, UnitCandidate(item.unit_id))
                score = current.fusion_score
                for rank in (
                    item.lexical_rank,
                    item.dense_rank,
                    item.concept_rank,
                ):
                    if rank is not None:
                        score += 1.0 / (self.rrf_k + rank)
                merged[item.unit_id] = replace(
                    current,
                    lexical_rank=item.lexical_rank or current.lexical_rank,
                    lexical_score=item.lexical_score
                    if item.lexical_score is not None
                    else current.lexical_score,
                    dense_rank=item.dense_rank or current.dense_rank,
                    dense_score=item.dense_score
                    if item.dense_score is not None
                    else current.dense_score,
                    concept_rank=item.concept_rank or current.concept_rank,
                    concept_score=item.concept_score
                    if item.concept_score is not None
                    else current.concept_score,
                    fusion_score=score,
                )
        return sorted(
            merged.values(),
            key=lambda item: (-item.fusion_score, str(item.unit_id)),
        )[:limit]

    async def _rerank(
        self,
        session: AsyncSession,
        query: str,
        candidates: list[UnitCandidate],
        *,
        limit: int,
    ) -> list[UnitCandidate]:
        if not candidates:
            return []
        tokens = set(search_tokens(query))
        units = {
            item.id: item
            for item in await session.scalars(
                select(KnowledgeUnit).where(
                    KnowledgeUnit.id.in_([item.unit_id for item in candidates])
                )
            )
        }
        max_fusion = max(item.fusion_score for item in candidates) or 1.0
        output: list[UnitCandidate] = []
        for item in candidates:
            unit = units[item.unit_id]
            unit_tokens = set(search_tokens(f"{unit.title} {unit.summary}"))
            overlap = len(tokens & unit_tokens) / max(1, len(tokens))
            signals = [
                value
                for value in (
                    item.lexical_score,
                    item.dense_score,
                    item.concept_score,
                )
                if value is not None
            ]
            score = (
                0.55 * (item.fusion_score / max_fusion)
                + 0.25 * overlap
                + 0.20 * max(signals, default=0.0)
            )
            # Oversized parent units marked SUMMARY stay reachable through
            # structural expansion but lose as independent evidence — the
            # more specific child units are the writer-facing material.
            if unit_retrieval_role(unit.metadata_json) == SUMMARY_ROLE:
                score *= 0.15
            output.append(replace(item, reranker_score=score))
        return sorted(
            output,
            key=lambda item: (-item.reranker_score, str(item.unit_id)),
        )[:limit]

    async def _dedup_nested(
        self, session: AsyncSession, candidates: list[UnitCandidate]
    ) -> list[UnitCandidate]:
        """Prefer the most specific unit among ancestor/descendant pairs.

        When a parent unit and its child unit both match with ≥50%
        segment-span overlap, keep the descendant — the parent stays
        available through structural expansion. A SUMMARY-role
        descendant never displaces a regular unit ancestor. Spans are
        SourceSegment *sequences*, so the metric is identical for
        video, PDF, book, and article sources — timestamps are never
        required.
        """

        if len(candidates) < 2:
            return candidates
        units = {
            item.id: item
            for item in await session.scalars(
                select(KnowledgeUnit).where(
                    KnowledgeUnit.id.in_([item.unit_id for item in candidates])
                )
            )
        }
        segment_ids = {
            segment_id
            for unit in units.values()
            for segment_id in (unit.start_segment_id, unit.end_segment_id)
            if segment_id is not None
        }
        sequences = {
            segment_id: sequence
            for segment_id, sequence in await session.execute(
                select(SourceSegment.id, SourceSegment.sequence).where(
                    SourceSegment.id.in_(segment_ids)
                )
            )
        }
        nodes = {
            item.id: item
            for item in await session.scalars(
                select(SourceStructureNode).where(
                    SourceStructureNode.id.in_(
                        [u.structure_node_id for u in units.values()]
                    )
                )
            )
        }
        all_nodes = {
            item.id: item
            for item in await session.scalars(
                select(SourceStructureNode).where(
                    SourceStructureNode.source_version_id.in_(
                        {u.source_version_id for u in units.values()}
                    )
                )
            )
        }

        def ancestors(node: SourceStructureNode) -> set[UUID]:
            chain: set[UUID] = set()
            current = node
            while current.parent_id and current.parent_id in all_nodes:
                current = all_nodes[current.parent_id]
                chain.add(current.id)
            return chain

        drop: set[UUID] = set()
        node_of = {
            item.unit_id: nodes.get(units[item.unit_id].structure_node_id)
            for item in candidates
            if item.unit_id in units
        }
        for index, item in enumerate(candidates):
            node = node_of.get(item.unit_id)
            if node is None or item.unit_id in drop:
                continue
            ancestor_ids = ancestors(node)
            for other in candidates[index + 1 :]:
                other_node = node_of.get(other.unit_id)
                if other_node is None or other.unit_id in drop:
                    continue
                if other_node.id in ancestor_ids:
                    ancestor_cand, child_cand = other, item
                elif node.id in ancestors(other_node):
                    ancestor_cand, child_cand = item, other
                else:
                    continue
                ancestor_span = self._unit_span(ancestor_cand, units, sequences)
                child_span = self._unit_span(child_cand, units, sequences)
                if ancestor_span is None or child_span is None:
                    continue
                overlap = span_overlap_ratio(ancestor_span, child_span)
                if overlap < 0.5:
                    continue
                ancestor_role = unit_retrieval_role(
                    units[ancestor_cand.unit_id].metadata_json
                )
                child_role = unit_retrieval_role(
                    units[child_cand.unit_id].metadata_json
                )
                # Prefer the specific descendant; a SUMMARY descendant
                # never displaces a regular ancestor unit.
                if child_role != SUMMARY_ROLE:
                    drop.add(ancestor_cand.unit_id)
                elif ancestor_role == SUMMARY_ROLE:
                    drop.add(child_cand.unit_id)
        return [item for item in candidates if item.unit_id not in drop]

    @staticmethod
    def _unit_span(
        candidate: UnitCandidate,
        units: dict[UUID, KnowledgeUnit],
        sequences: dict[UUID, int],
    ) -> tuple[int, int] | None:
        """Segment-sequence span of a candidate unit (generic metric)."""

        unit = units.get(candidate.unit_id)
        if unit is None:
            return None
        start = sequences.get(unit.start_segment_id)
        end = sequences.get(unit.end_segment_id)
        if start is None or end is None:
            return None
        return (start, end)

    async def _hydrate(
        self,
        session: AsyncSession,
        candidates: list[UnitCandidate],
        expansion: ExpansionMode,
    ) -> list[KnowledgeUnitSearchResult]:
        unit_ids = [item.unit_id for item in candidates]
        units = {
            item.id: item
            for item in await session.scalars(
                select(KnowledgeUnit).where(KnowledgeUnit.id.in_(unit_ids))
            )
        }
        nodes = {
            item.id: item
            for item in await session.scalars(
                select(SourceStructureNode).where(
                    SourceStructureNode.id.in_(
                        [u.structure_node_id for u in units.values()]
                    )
                )
            )
        }
        versions = {
            item.id: item
            for item in await session.scalars(
                select(SourceVersion).where(
                    SourceVersion.id.in_([u.source_version_id for u in units.values()])
                )
            )
        }
        sources = {
            item.id: item
            for item in await session.scalars(
                select(Source).where(
                    Source.id.in_([v.source_id for v in versions.values()])
                )
            )
        }
        concept_rows = (
            await session.execute(
                select(
                    KnowledgeUnitConcept.knowledge_unit_id,
                    ExternalConcept.canonical_name,
                )
                .join(
                    ExternalConcept,
                    ExternalConcept.id == KnowledgeUnitConcept.concept_id,
                )
                .where(KnowledgeUnitConcept.knowledge_unit_id.in_(unit_ids))
            )
        ).all()
        concepts_by_unit: dict[UUID, list[str]] = {}
        for unit_id, name in concept_rows:
            concepts_by_unit.setdefault(unit_id, []).append(name)

        all_nodes = await session.scalars(
            select(SourceStructureNode).where(
                SourceStructureNode.source_version_id.in_(
                    [v.id for v in versions.values()]
                )
            )
        )
        nodes_by_version: dict[UUID, dict[UUID, SourceStructureNode]] = {}
        for node in all_nodes:
            nodes_by_version.setdefault(node.source_version_id, {})[node.id] = node

        results: list[KnowledgeUnitSearchResult] = []
        for candidate in candidates:
            unit = units[candidate.unit_id]
            node = nodes[unit.structure_node_id]
            version = versions[unit.source_version_id]
            source = sources[version.source_id]
            context = await self._expand(
                session, unit, node, expansion, nodes_by_version
            )
            results.append(
                KnowledgeUnitSearchResult(
                    knowledge_unit_id=unit.id,
                    title=unit.title,
                    summary=unit.summary,
                    full_text=unit.full_text,
                    unit_type=unit.unit_type.value,
                    atomic=unit.atomic,
                    matched_concepts=tuple(sorted(concepts_by_unit.get(unit.id, []))),
                    score_components={
                        "lexical": candidate.lexical_score or 0.0,
                        "dense": candidate.dense_score or 0.0,
                        "concept": candidate.concept_score or 0.0,
                        "fusion": candidate.fusion_score,
                        "reranker": candidate.reranker_score,
                    },
                    source_id=source.id,
                    source_version_id=version.id,
                    source_title=source.title,
                    source_url=source.canonical_url,
                    start_seconds=node.start_seconds,
                    end_seconds=node.end_seconds,
                    structure_path=tuple(
                        self._path(node, nodes_by_version[version.id])
                    ),
                    expanded_context=context,
                )
            )
        return results

    def _path(
        self,
        node: SourceStructureNode,
        by_id: dict[UUID, SourceStructureNode],
    ) -> list[str]:
        parts = [node.title]
        current = node
        while current.parent_id and current.parent_id in by_id:
            current = by_id[current.parent_id]
            parts.append(current.title)
        return list(reversed(parts))

    async def _expand(
        self,
        session: AsyncSession,
        unit: KnowledgeUnit,
        node: SourceStructureNode,
        expansion: ExpansionMode,
        nodes_by_version: dict[UUID, dict[UUID, SourceStructureNode]],
    ) -> tuple[dict[str, object], ...]:
        if expansion is ExpansionMode.NONE:
            return ()
        by_id = nodes_by_version.get(node.source_version_id, {})
        related: list[SourceStructureNode] = []
        if expansion is ExpansionMode.PARENT:
            parent = by_id.get(node.parent_id or node.id)
            if parent is not None and parent.id != node.id:
                related = [parent]
        elif expansion is ExpansionMode.PARENTS:
            current = node
            while current.parent_id and current.parent_id in by_id:
                current = by_id[current.parent_id]
                related.append(current)
        elif expansion is ExpansionMode.SIBLINGS:
            related = [
                item
                for item in by_id.values()
                if item.parent_id == node.parent_id and item.id != node.id
            ]
        elif expansion is ExpansionMode.FAMILY:
            related = [
                item
                for item in by_id.values()
                if item.parent_id == node.parent_id and item.id != node.id
            ]
            if node.parent_id and node.parent_id in by_id:
                related.append(by_id[node.parent_id])
        elif expansion is ExpansionMode.SUBTREE:
            related = self._subtree(node, by_id)
        if not related:
            return ()
        related_units = (
            await session.execute(
                select(KnowledgeUnit, SourceStructureNode.title)
                .join(
                    SourceStructureNode,
                    SourceStructureNode.id == KnowledgeUnit.structure_node_id,
                )
                .where(
                    KnowledgeUnit.structure_node_id.in_([item.id for item in related])
                )
            )
        ).all()
        return tuple(
            {
                "knowledge_unit_id": str(item.id),
                "node_id": str(item.structure_node_id),
                "node_title": node_title,
                "title": item.title,
                "summary": item.summary,
                "atomic": item.atomic,
            }
            for item, node_title in related_units
        )

    @staticmethod
    def _subtree(
        node: SourceStructureNode,
        by_id: dict[UUID, SourceStructureNode],
    ) -> list[SourceStructureNode]:
        children: dict[UUID | None, list[SourceStructureNode]] = {}
        for item in by_id.values():
            children.setdefault(item.parent_id, []).append(item)
        result: list[SourceStructureNode] = []
        stack = list(children.get(node.id, []))
        while stack:
            current = stack.pop()
            result.append(current)
            stack.extend(children.get(current.id, []))
        return result


__all__ = [
    "ExpansionMode",
    "KnowledgeUnitSearchResult",
    "KnowledgeUnitSearchService",
    "UnitEmbeddingService",
    "normalize_search_text",
]
