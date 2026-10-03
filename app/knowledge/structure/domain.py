"""Vocabulary and lifecycle states for source structure extraction."""

from enum import StrEnum


class StructureNodeType(StrEnum):
    TOPIC = "TOPIC"
    SUBTOPIC = "SUBTOPIC"
    ARGUMENT = "ARGUMENT"
    EXPLANATION = "EXPLANATION"
    STORY = "STORY"
    CASE_STUDY = "CASE_STUDY"
    EXAMPLE = "EXAMPLE"
    EXPERIMENT = "EXPERIMENT"
    QUESTION = "QUESTION"
    ANSWER = "ANSWER"
    COUNTERARGUMENT = "COUNTERARGUMENT"
    DEFINITION = "DEFINITION"
    CONCLUSION = "CONCLUSION"
    OTHER = "OTHER"


class SourceProcessingStatus(StrEnum):
    """Post-ingestion processing lifecycle for one source version."""

    INGESTED = "INGESTED"
    STRUCTURE_PENDING = "STRUCTURE_PENDING"
    STRUCTURING = "STRUCTURING"
    STRUCTURED = "STRUCTURED"
    STRUCTURE_REVIEW_REQUIRED = "STRUCTURE_REVIEW_REQUIRED"
    UNIT_EXTRACTION_PENDING = "UNIT_EXTRACTION_PENDING"
    UNIT_EXTRACTING = "UNIT_EXTRACTING"
    UNIT_REVIEW_REQUIRED = "UNIT_REVIEW_REQUIRED"
    READY = "READY"
    FAILED = "FAILED"


ATOMIC_NODE_TYPES: frozenset[StructureNodeType] = frozenset(
    {StructureNodeType.STORY, StructureNodeType.CASE_STUDY}
)

STRUCTURE_TASK = "source_structure"
LOCAL_PASS_PROMPT_VERSION = "source_structure_local_v1"
MERGE_PASS_PROMPT_VERSION = "source_structure_merge_v1"
