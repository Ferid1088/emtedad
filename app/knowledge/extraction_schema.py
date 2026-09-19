"""Strict structured-output boundary for external knowledge extraction."""

from pydantic import BaseModel, ConfigDict, Field

from app.knowledge.domain import EntityType


class ExtractedMention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: EntityType
    surface_text: str = Field(min_length=1)
    normalized_candidate: str = Field(min_length=1)
    start_segment_sequence: int = Field(gt=0)
    end_segment_sequence: int = Field(gt=0)
    context: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class ExtractedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_text: str = Field(min_length=1)
    claim_domain: str = Field(min_length=1)
    claim_type: str = Field(min_length=1)
    source_segment_sequence: int = Field(gt=0)
    confidence: float = Field(ge=0, le=1)


class WindowExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mentions: list[ExtractedMention]
    claims: list[ExtractedClaim]
