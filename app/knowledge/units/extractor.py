"""LLM metadata extraction for Knowledge Units.

The model classifies each eligible structure node (unit type, title, summary,
evidence level, claim type). Spans and full text stay deterministic.
"""

import json
from uuid import UUID

from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.knowledge.models import SourceSegment
from app.knowledge.structure.models import SourceStructureNode
from app.knowledge.units.domain import UNIT_PROMPT_VERSION
from app.knowledge.units.schemas import (
    UnitMetadataBatch,
    UnitMetadataProposal,
)

UNIT_INSTRUCTIONS = """You classify structure nodes from a transcript into \
Knowledge Units.

For each node return: node_id (echo the given id), unit_type, title, summary, \
evidence_level, claim_type.

Rules:
- Do not invent information. Describe only what the transcript says.
- The summary describes the unit; it never replaces the original text.
- STORY and CASE_STUDY stay whole: one atomic unit per complete narrative.
- evidence_level reflects what the source itself provides (PRIMARY for \
first-hand material, SECONDARY for reported material, ANECDOTAL for \
personal accounts, NONE when no evidence is offered).
- claim_type reflects the statement kind (FACT, INTERPRETATION, OPINION, \
NORMATIVE, UNKNOWN).
""".strip()


class KnowledgeUnitExtractor:
    """Batch-classify eligible structure nodes into unit metadata."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str = "configured-default",
        batch_size: int = 10,
    ) -> None:
        self.provider = provider
        self.model = model
        self.batch_size = batch_size

    async def propose(
        self,
        nodes: list[SourceStructureNode],
        segments_by_id: dict[UUID, SourceSegment],
    ) -> dict[str, UnitMetadataProposal]:
        proposals: dict[str, UnitMetadataProposal] = {}
        for start in range(0, len(nodes), self.batch_size):
            batch = nodes[start : start + self.batch_size]
            payload = json.dumps(
                [
                    {
                        "node_id": str(node.id),
                        "node_type": node.node_type.value,
                        "title": node.title,
                        "summary": node.summary,
                        "transcript_excerpt": self._excerpt(node, segments_by_id),
                    }
                    for node in batch
                ],
                ensure_ascii=False,
            )
            request = StructuredExtractionRequest(
                task="knowledge_unit_metadata",
                prompt_version=UNIT_PROMPT_VERSION,
                model=self.model,
                instructions=UNIT_INSTRUCTIONS,
                input_text=payload,
                output_model=UnitMetadataBatch,
            )
            result = await self.provider.extract(request)
            parsed = UnitMetadataBatch.model_validate(result.model_dump())
            known = {str(node.id) for node in batch}
            for proposal in parsed.units:
                if proposal.node_id not in known:
                    raise ValueError(f"unknown node reference: {proposal.node_id}")
                proposals[proposal.node_id] = proposal
        return proposals

    @staticmethod
    def _excerpt(
        node: SourceStructureNode,
        segments_by_id: dict[UUID, SourceSegment],
        limit: int = 4000,
    ) -> str:
        start = segments_by_id.get(node.start_segment_id)
        end = segments_by_id.get(node.end_segment_id)
        if start is None or end is None:
            return ""
        texts = [
            segment.normalized_text
            for segment in segments_by_id.values()
            if start.sequence <= segment.sequence <= end.sequence
        ]
        joined = "\n".join(texts)
        return joined[:limit]
