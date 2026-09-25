"""Boundary contracts for semantic structuring and content automation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.retrieval.domain import QueryLanguage
from app.semantic_content.domain import ContextExpansionMode


class LocalOutlineNode(BaseModel):
    title: str
    summary: str
    main_idea: str
    start_sequence: int = Field(gt=0)
    end_sequence: int = Field(gt=0)
    claims: list[str] = Field(default_factory=list)
    definitions: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)


class LocalOutline(BaseModel):
    nodes: list[LocalOutlineNode]


class GlobalOutlineNode(BaseModel):
    title: str
    summary: str
    main_idea: str
    start_sequence: int = Field(gt=0)
    end_sequence: int = Field(gt=0)
    claims: list[str] = Field(default_factory=list)
    definitions: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    children: list["GlobalOutlineNode"] = Field(default_factory=list)


class GlobalOutline(BaseModel):
    title: str
    sections: list[GlobalOutlineNode]


class SemanticStructureRequest(BaseModel):
    model: str = "configured-default"
    prompt_version: str = "semantic-tree-v2"
    max_window_characters: int = Field(default=28000, ge=4000, le=60000)
    overlap_segments: int = Field(default=8, ge=0, le=50)
    make_preferred: bool = True


class SemanticNodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    parent_id: UUID | None
    path: str
    depth: int
    ordinal: int
    node_kind: str
    title: str
    summary: str
    main_idea: str
    claims: list[str]
    definitions: list[str]
    examples: list[str]
    qualifications: list[str]
    start_sequence: int
    end_sequence: int
    start_seconds: float
    end_seconds: float


class SemanticStructureRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_version_id: UUID
    prompt_version: str
    provider: str
    model: str
    status: str
    window_count: int
    node_count: int
    output_hash: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class SemanticTreeRead(BaseModel):
    run: SemanticStructureRunRead
    nodes: list[SemanticNodeRead]


class ResearchQuerySpec(BaseModel):
    query: str
    purpose: str


class GenerationPlanSpec(BaseModel):
    central_question: str
    thesis_direction: str
    research_queries: list[ResearchQuerySpec] = Field(min_length=3, max_length=10)
    must_cover: list[str] = Field(default_factory=list)
    avoid_repetition_of: list[str] = Field(default_factory=list)


class EvidenceReference(BaseModel):
    candidate_id: str
    source_id: str
    source_version_id: str
    source_title: str
    source_url: str | None = None
    timestamp_start: float | None = None
    timestamp_end: float | None = None
    chunk_id: str
    semantic_root_path: str | None = None
    semantic_hit_path: str | None = None


class SynthesisCluster(BaseModel):
    cluster_id: str
    title: str
    core_idea: str
    supporting_points: list[str]
    tensions_or_limits: list[str] = Field(default_factory=list)
    references: list[EvidenceReference] = Field(min_length=1)


class SynthesisSpec(BaseModel):
    clusters: list[SynthesisCluster]
    contradictions: list[str] = Field(default_factory=list)
    repeated_ideas_removed: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


class OutlineSectionSpec(BaseModel):
    title: str
    purpose: str
    transition_from_previous: str | None = None
    cluster_ids: list[str] = Field(min_length=1)
    target_word_count: int = Field(gt=100)


class ContentOutlineSpec(BaseModel):
    title: str
    opening_intent: str
    sections: list[OutlineSectionSpec] = Field(min_length=3, max_length=7)
    conclusion_intent: str


class SectionDraftSpec(BaseModel):
    text: str
    claims_used: list[str] = Field(default_factory=list)
    concepts_defined: list[str] = Field(default_factory=list)
    examples_used: list[str] = Field(default_factory=list)


class CoherenceIssue(BaseModel):
    code: str
    section_ordinal: int | None = None
    description: str
    suggested_fix: str


class CoherenceReportSpec(BaseModel):
    issues: list[CoherenceIssue] = Field(default_factory=list)
    strengths_to_preserve: list[str] = Field(default_factory=list)


class FinalRevisionSpec(BaseModel):
    revised_script: str
    changes_made: list[str] = Field(default_factory=list)


class GenerateContentRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=2000)
    language: QueryLanguage = QueryLanguage.FA
    chunking_run_id: UUID
    embedding_model_id: UUID
    target_duration_seconds: int = Field(default=1200, ge=300, le=3600)
    words_per_minute: int = Field(default=125, ge=80, le=190)
    context_expansion_mode: ContextExpansionMode = ContextExpansionMode.FULL_ROOT_FAMILY
    model: str = "configured-default"
    created_by: str = "operator"


class GeneratedContentSectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ordinal: int
    title: str
    purpose: str
    transition_from_previous: str | None
    target_word_count: int
    evidence_pack: dict[str, object]
    draft_text: str | None
    revision_notes: list[str]


class GeneratedContentRead(BaseModel):
    id: UUID
    topic: str
    language: str
    target_duration_seconds: int
    target_word_count: int
    status: str
    plan: dict[str, object]
    synthesis: dict[str, object]
    outline: dict[str, object]
    coherence_report: dict[str, object]
    final_script: str | None
    provenance_complete: bool
    sections: list[GeneratedContentSectionRead]
