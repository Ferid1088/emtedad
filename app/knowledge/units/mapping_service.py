"""Concept mapping service: units -> ExternalConcept links and relations."""

import json
import logging
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.knowledge.llm.factory import resolve_llm_provider
from app.knowledge.models import ExternalConcept
from app.knowledge.units.concepts import (
    CONCEPT_INSTRUCTIONS,
    CONCEPT_PROMPT_VERSION,
    ConceptProposal,
    UnitConceptMapping,
    UnitsConceptBatchRaw,
    normalize_concept_name,
    normalize_role,
    resolve_concept,
    validate_concept_proposal,
)
from app.knowledge.units.models import (
    ConceptRelationship,
    ConceptRelationType,
    KnowledgeUnit,
    KnowledgeUnitConcept,
)

logger = logging.getLogger(__name__)

_MAX_UNIT_CONCEPTS = 5


class ConceptMappingService:
    """Map units to shared concepts; build co-occurrence relationships."""

    def __init__(
        self,
        database: Database,
        provider: LLMProvider | None = None,
        *,
        model: str = "configured-default",
        batch_size: int = 10,
    ) -> None:
        self.database = database
        self.provider = provider or resolve_llm_provider()
        self.model = model
        self.batch_size = batch_size

    async def map_source_units(self, source_version_id: UUID) -> dict[str, int]:
        """Extract concepts for every unit of one source version.

        Idempotent: existing unit-concept links are reused, new concepts are
        resolved reuse-first (canonical name → alias label) so multiple
        sources converge on one shared concept row.
        """

        async with self.database.transaction() as session:
            units = list(
                await session.scalars(
                    select(KnowledgeUnit).where(
                        KnowledgeUnit.source_version_id == source_version_id
                    )
                )
            )
            stats = {"units": len(units), "links": 0, "rejected": 0, "reused": 0}
            for start in range(0, len(units), self.batch_size):
                batch_stats = await self._map_batch(
                    session, units[start : start + self.batch_size]
                )
                for key, value in batch_stats.items():
                    stats[key] = stats.get(key, 0) + value
            return stats

    async def _map_batch(
        self, session: AsyncSession, units: list[KnowledgeUnit]
    ) -> dict[str, int]:
        labels = {f"u{index}": unit for index, unit in enumerate(units, 1)}
        payload = json.dumps(
            [
                {
                    "unit_ref": ref,
                    "unit_type": unit.unit_type.value,
                    "title": unit.title,
                    "summary": unit.summary,
                    "excerpt": unit.full_text[:3000],
                }
                for ref, unit in labels.items()
            ],
            ensure_ascii=False,
        )
        request = StructuredExtractionRequest(
            task="unit_concept_mapping",
            prompt_version=CONCEPT_PROMPT_VERSION,
            model=self.model,
            instructions=CONCEPT_INSTRUCTIONS,
            input_text=payload,
            output_model=UnitsConceptBatchRaw,
        )
        result = await self.provider.extract(request)
        parsed = UnitsConceptBatchRaw.model_validate(result.model_dump())
        stats: dict[str, int] = {"links": 0, "rejected": 0, "reused": 0}
        for raw in parsed.mappings:
            try:
                mapping = UnitConceptMapping.model_validate(raw)
            except ValidationError:
                stats["rejected"] += 1
                logger.warning(
                    "concept_mapping.invalid_mapping",
                    extra={"prompt_version": CONCEPT_PROMPT_VERSION},
                )
                continue
            unit = labels.get(mapping.unit_ref)
            if unit is None:
                stats["rejected"] += 1
                logger.warning(
                    "concept_mapping.unknown_unit_ref",
                    extra={"unit_ref": mapping.unit_ref},
                )
                continue
            accepted: list[tuple[ConceptProposal, ExternalConcept]] = []
            for proposal in mapping.concepts[:_MAX_UNIT_CONCEPTS]:
                reason = validate_concept_proposal(proposal)
                if reason is not None:
                    stats["rejected"] += 1
                    logger.info(
                        "concept_mapping.proposal_rejected",
                        extra={
                            "reason": reason,
                            "concept_name": proposal.canonical_name[:80],
                        },
                    )
                    continue
                before = await session.scalar(
                    select(ExternalConcept.id).where(
                        ExternalConcept.normalized_name
                        == normalize_concept_name(proposal.canonical_name)
                    )
                )
                concept = await resolve_concept(
                    session, proposal.canonical_name, proposal.labels
                )
                if before is not None:
                    stats["reused"] += 1
                accepted.append((proposal, concept))
            for proposal, concept in accepted:
                role = normalize_role(proposal.relation_role)
                existing = await session.scalar(
                    select(KnowledgeUnitConcept).where(
                        KnowledgeUnitConcept.knowledge_unit_id == unit.id,
                        KnowledgeUnitConcept.concept_id == concept.id,
                        KnowledgeUnitConcept.relation_role == role,
                    )
                )
                if existing is None:
                    session.add(
                        KnowledgeUnitConcept(
                            knowledge_unit_id=unit.id,
                            concept_id=concept.id,
                            confidence=proposal.confidence,
                            relation_role=role,
                        )
                    )
                    stats["links"] += 1
            await self._link_cooccurrence(
                session, unit, [concept for _p, concept in accepted]
            )
        return stats

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
    "normalize_concept_name",
]
