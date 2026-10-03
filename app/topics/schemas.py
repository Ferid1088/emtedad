"""Structured output for topic mining."""

from pydantic import BaseModel, ConfigDict, Field


class TopicCandidateProposal(BaseModel):
    """One proposed video topic, grounded in labeled unit references."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=1024)
    video_question: str = Field(min_length=1)
    tentative_thesis: str = Field(min_length=1)
    angle: str = Field(min_length=1)
    supporting_unit_refs: list[str] = Field(default_factory=list)
    supporting_concepts: list[str] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)
    channel_fit_reason: str = ""
    curiosity: float = Field(default=0.5, ge=0, le=1)
    emotional_relevance: float = Field(default=0.5, ge=0, le=1)
    practical_value: float = Field(default=0.5, ge=0, le=1)
    channel_fit: float = Field(default=0.5, ge=0, le=1)


class TopicMiningBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topics: list[TopicCandidateProposal] = Field(default_factory=list)
