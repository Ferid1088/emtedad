"""Concept mapping service: units -> ExternalConcept links and relations."""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.knowledge.llm.factory import resolve_llm_provider
from app.knowledge.models import ExternalConcept
from app.knowledge.units.concepts import (
    CONCEPT_INSTRUCTIONS,
    CONCEPT_PROMPT_VERSION,
    UnitConceptBatch,
    normalize_concept_name,
    resolve_concept,
)
from app.knowledge.units.models import (
    ConceptRelationship,
    ConceptRelationType,
    KnowledgeUnit,
    KnowledgeUnitConcept,
)

logger = logging.getLogger(__name__)


class ConceptMappingService:
    """Map units to shared concepts; build co-occurrence relationships."""

    def __init__(
        self,
        database: Database,
        provider: LLMProvider | None = None,
        *,
        model: str = "configured-default",
    ) -> None:
        self.database = database
        self.provider = provider or resolve_llm_provider()
        self.model = model

    async def map_source_units(self, source_version_id: UUID) -> dict[str, int]:
        """Extract concepts for every unit of one source version.

        Idempotent: existing unit-concept links are reused, new concepts are
        resolved by normalized name so multiple sources converge on one
        shared concept row.
        """

        async with self.database.transaction() as session:
            units = list(
                await session.scalars(
                    select(KnowledgeUnit).where(
                        KnowledgeUnit.source_version_id == source_version_id
                    )
                )
            )
            linked = 0
            for unit in units:
                linked += await self._map_unit(session, unit)
            return {"units": len(units), "links": linked}

    async def _map_unit(self, session: AsyncSession, unit: KnowledgeUnit) -> int:
        request = StructuredExtractionRequest(
            task="unit_concept_mapping",
            prompt_version=CONCEPT_PROMPT_VERSION,
            model=self.model,
            instructions=CONCEPT_INSTRUCTIONS,
            input_text=f"{unit.title}\n\n{unit.summary}\n\n{unit.full_text[:4000]}",
            output_model=UnitConceptBatch,
        )
        result = await self.provider.extract(request)
        batch = UnitConceptBatch.model_validate(result.model_dump())
        linked = 0
        concepts: list[ExternalConcept] = []
        for proposal in batch.concepts:
            concept = await resolve_concept(session, proposal.canonical_name)
            concepts.append(concept)
            existing = await session.scalar(
                select(KnowledgeUnitConcept).where(
                    KnowledgeUnitConcept.knowledge_unit_id == unit.id,
                    KnowledgeUnitConcept.concept_id == concept.id,
                    KnowledgeUnitConcept.relation_role == proposal.relation_role,
                )
            )
            if existing is None:
                session.add(
                    KnowledgeUnitConcept(
                        knowledge_unit_id=unit.id,
                        concept_id=concept.id,
                        confidence=proposal.confidence,
                        relation_role=proposal.relation_role,
                    )
                )
                linked += 1
        await self._link_cooccurrence(session, unit, concepts)
        return linked

    async def _link_cooccurrence(
        self,
        session: AsyncSession,
        unit: KnowledgeUnit,
        concepts: list[ExternalConcept],
    ) -> None:
        for left_index, left in enumerate(concepts):
            for right in concepts[left_index + 1 :]:
                await self.relate(
                    session,
                    left.id,
                    right.id,
                    ConceptRelationType.RELATED_TO,
                    confidence=0.5,
                    provenance={"knowledge_unit_id": str(unit.id)},
                )

    @staticmethod
    async def relate(
        session: AsyncSession,
        from_concept_id: UUID,
        to_concept_id: UUID,
        relation_type: ConceptRelationType,
        *,
        confidence: float = 0.5,
        provenance: dict[str, object] | None = None,
    ) -> ConceptRelationship:
        existing = await session.scalar(
            select(ConceptRelationship).where(
                ConceptRelationship.from_concept_id == from_concept_id,
                ConceptRelationship.to_concept_id == to_concept_id,
                ConceptRelationship.relation_type == relation_type,
            )
        )
        if existing is not None:
            return existing
        relation = ConceptRelationship(
            from_concept_id=from_concept_id,
            to_concept_id=to_concept_id,
            relation_type=relation_type,
            confidence=confidence,
            provenance_json=provenance or {},
        )
        session.add(relation)
        await session.flush()
        return relation

    async def unit_concepts(
        self, unit_id: UUID
    ) -> list[tuple[ExternalConcept, str, float]]:
        async with self.database.transaction() as session:
            rows = (
                await session.execute(
                    select(
                        ExternalConcept,
                        KnowledgeUnitConcept.relation_role,
                        KnowledgeUnitConcept.confidence,
                    )
                    .join(
                        KnowledgeUnitConcept,
                        KnowledgeUnitConcept.concept_id == ExternalConcept.id,
                    )
                    .where(KnowledgeUnitConcept.knowledge_unit_id == unit_id)
                )
            ).all()
            return [(row[0], row[1], row[2]) for row in rows]

    async def concept_units(self, concept_id: UUID) -> list[KnowledgeUnit]:
        async with self.database.transaction() as session:
            return list(
                await session.scalars(
                    select(KnowledgeUnit)
                    .join(
                        KnowledgeUnitConcept,
                        KnowledgeUnitConcept.knowledge_unit_id == KnowledgeUnit.id,
                    )
                    .where(KnowledgeUnitConcept.concept_id == concept_id)
                )
            )


__all__ = [
    "ConceptMappingService",
    "CONCEPT_PROMPT_VERSION",
    "UnitConceptBatch",
    "normalize_concept_name",
]
