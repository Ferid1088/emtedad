"""Typed states for hierarchical source semantics and automated content generation."""

from enum import StrEnum


class SemanticStructureStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class SemanticNodeKind(StrEnum):
    SECTION = "SECTION"
    SUBSECTION = "SUBSECTION"
    DETAIL = "DETAIL"


class ContentGenerationStatus(StrEnum):
    DRAFT = "DRAFT"
    PLANNING = "PLANNING"
    RETRIEVING = "RETRIEVING"
    SYNTHESIZING = "SYNTHESIZING"
    ARCHITECTING = "ARCHITECTING"
    WRITING = "WRITING"
    REVIEWING = "REVIEWING"
    READY = "READY"
    FAILED = "FAILED"


class ContextExpansionMode(StrEnum):
    """How a retrieval hit is expanded inside one source hierarchy."""

    HIT_ONLY = "HIT_ONLY"
    ANCESTORS = "ANCESTORS"
    FULL_ROOT_FAMILY = "FULL_ROOT_FAMILY"
