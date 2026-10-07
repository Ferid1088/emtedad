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


class FailureClass(StrEnum):
    """Retry classification for a persisted processing error."""

    QUOTA = "quota"  # provider quota/billing — retry later, unbounded
    RATE_LIMIT = "rate_limit"  # provider concurrency/throttling — retry later
    # Setup problem (missing/rejected API key, retired provider, routing):
    # not the source's fault — retried later without consuming attempts.
    CONFIGURATION = "configuration"
    FAILED = "failed"  # real analysis failure — counted against max attempts


def classify_failure(error: str | None) -> FailureClass:
    """Bucket a persisted processing error into a retry class."""

    text = (error or "").lower()
    if (
        "out_of_quota" in text
        or "provider_quota_exhausted" in text
        or "kontingent" in text
        or "billing" in text
    ):
        return FailureClass.QUOTA
    if "429" in text or "rate limit" in text or "parallele sessions" in text:
        return FailureClass.RATE_LIMIT
    if any(
        marker in text
        for marker in (
            "routingconfiguration",
            "routing is off",
            "llm_routing",
            "devin",
            "api key is not configured",
            "apimastermissingkey",
            "apimasterautherror",
            "rejected the api key",
            "model_not_found",
        )
    ):
        return FailureClass.CONFIGURATION
    return FailureClass.FAILED


STRUCTURE_TASK = "source_structure"
LOCAL_PASS_PROMPT_VERSION = "source_structure_local_v1"
MERGE_PASS_PROMPT_VERSION = "source_structure_merge_v2"
