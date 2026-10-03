"""Structured outputs for the argument and narrative architects."""

from pydantic import BaseModel, ConfigDict, Field


class ArgumentSectionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordinal: int = Field(ge=1)
    role: str = Field(min_length=1, max_length=64)
    purpose: str = Field(min_length=1)
    evidence_item_refs: list[str] = Field(default_factory=list)
    story_unit_refs: list[str] = Field(default_factory=list)
    counterargument_refs: list[str] = Field(default_factory=list)
    transition_intent: str = ""
    must_include: list[str] = Field(default_factory=list)
    must_not_claim: list[str] = Field(default_factory=list)


class ArgumentPlanOutput(BaseModel):
    """Sections reference evidence items and story units by label."""

    model_config = ConfigDict(extra="forbid")

    sections: list[ArgumentSectionProposal] = Field(min_length=1)


class NarrativeSectionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ordinal: int = Field(ge=1)
    narrative_role: str = Field(min_length=1, max_length=64)
    purpose: str = Field(min_length=1)
    target_seconds: int = Field(default=60, ge=1)
    argument_section_refs: list[str] = Field(default_factory=list)
    story_unit_refs: list[str] = Field(default_factory=list)
    emotional_function: str = ""
    transition_in: str = ""
    transition_out: str = ""
    opening_method: str = ""
    ending_method: str = ""


class NarrativePlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[NarrativeSectionProposal] = Field(min_length=1)
