"""Structured output contracts for source-structure extraction."""

from pydantic import BaseModel, ConfigDict, Field

from app.knowledge.structure.domain import StructureNodeType


class StructureNodeProposal(BaseModel):
    """One agent-proposed node; sequences resolve to real segment IDs."""

    model_config = ConfigDict(extra="forbid")

    temp_id: str = Field(min_length=1)
    parent_temp_id: str | None = None
    node_type: StructureNodeType = StructureNodeType.TOPIC
    title: str = Field(min_length=1, max_length=1024)
    summary: str = Field(min_length=1)
    start_segment_sequence: int = Field(ge=1)
    end_segment_sequence: int = Field(ge=1)
    ordinal: int = Field(default=1, ge=1)
    confidence: float = Field(default=0.5, ge=0, le=1)


class SourceStructureOutput(BaseModel):
    """Final merged hierarchy for one source version."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[StructureNodeProposal] = Field(default_factory=list)


class StructureValidationReport(BaseModel):
    """Blocking errors plus non-blocking structural warnings."""

    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    node_count: int = 0
    maximum_depth: int = 0
    coverage_percent: float = 0.0

    @property
    def valid(self) -> bool:
        return not self.errors
