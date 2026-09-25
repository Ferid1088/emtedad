"""Strict contracts for structured LLM output and validation reports."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LocalTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temporary_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    role: str = "TOPIC"
    segment_ids: list[UUID] = Field(default_factory=list)
    description: str | None = None
    related_to_previous: bool = False
    confidence: float = Field(default=0.5, ge=0, le=1)


class LocalTopicAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topics: list[LocalTopic] = Field(default_factory=list)


class OutlineSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temporary_id: str = Field(min_length=1)
    parent_temporary_id: str | None = None
    title: str = Field(min_length=1)
    summary: str | None = None
    role: str = "TOPIC"
    source_topic_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)
    sort_order: int = Field(default=0, ge=0)


class GlobalOutline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sections: list[OutlineSection] = Field(default_factory=list)


class ValidationReport(BaseModel):
    total_transcript_segments: int
    meaningful_transcript_segments: int
    assigned_meaningful_segments: int
    unassigned_meaningful_segments: int
    assignment_coverage_percent: float
    duplicated_primary_assignments: list[str] = Field(default_factory=list)
    invalid_source_segment_ids: list[str] = Field(default_factory=list)
    orphan_sections: list[str] = Field(default_factory=list)
    invalid_parent_links: list[str] = Field(default_factory=list)
    invalid_root_links: list[str] = Field(default_factory=list)
    empty_leaf_sections: list[str] = Field(default_factory=list)
    section_count: int
    maximum_hierarchy_depth: int
    low_confidence_sections: list[str] = Field(default_factory=list)
    low_confidence_mappings: list[str] = Field(default_factory=list)
    ready: bool
    status: Literal["READY", "REVIEW"]
