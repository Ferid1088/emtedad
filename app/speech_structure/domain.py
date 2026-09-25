"""Stable values used by the speech-structure module."""

from enum import StrEnum


class StructureStatus(StrEnum):
    DRAFT = "DRAFT"
    PROCESSING = "PROCESSING"
    REVIEW = "REVIEW"
    READY = "READY"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class SectionRole(StrEnum):
    TOPIC = "TOPIC"
    SUBTOPIC = "SUBTOPIC"
    EXAMPLE = "EXAMPLE"
    STORY = "STORY"
    ARGUMENT = "ARGUMENT"
    EXPLANATION = "EXPLANATION"
    REFERENCE = "REFERENCE"
    DIGRESSION = "DIGRESSION"
    CONCLUSION = "CONCLUSION"


class SegmentRelation(StrEnum):
    PRIMARY = "PRIMARY"
    SUPPORTING = "SUPPORTING"
    EXAMPLE = "EXAMPLE"
    REFERENCE = "REFERENCE"
    CONTEXT = "CONTEXT"


LOCAL_PROMPT_VERSION = "speech_structure_local_topics_v1"
GLOBAL_PROMPT_VERSION = "speech_structure_global_outline_v1"
ASSIGNMENT_PROMPT_VERSION = "speech_structure_segment_assignment_v1"
VALIDATION_PROMPT_VERSION = "speech_structure_validation_review_v1"
