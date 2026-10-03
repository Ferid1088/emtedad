"""Structured output for Knowledge Unit metadata extraction."""

from pydantic import BaseModel, ConfigDict, Field

from app.knowledge.units.domain import (
    ClaimType,
    EvidenceLevel,
    KnowledgeUnitType,
)


class UnitMetadataProposal(BaseModel):
    """LLM-proposed metadata for one structure node.

    The span is never proposed — it is pinned by the structure node and the
    full text is reconstructed deterministically from the source segments.
    """

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    unit_type: KnowledgeUnitType
    title: str = Field(min_length=1, max_length=1024)
    summary: str = Field(min_length=1)
    evidence_level: EvidenceLevel = EvidenceLevel.NONE
    claim_type: ClaimType = ClaimType.UNKNOWN


class UnitMetadataBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    units: list[UnitMetadataProposal] = Field(default_factory=list)


class UnitValidationReport(BaseModel):
    errors: list[str] = Field(default_factory=list)
    unit_count: int = 0

    @property
    def valid(self) -> bool:
        return not self.errors
