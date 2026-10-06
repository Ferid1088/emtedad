"""Closed vocabularies for localization and speech-readiness workflows."""

from enum import StrEnum


class LocalizationStatus(StrEnum):
    DRAFT = "DRAFT"
    SEMANTICALLY_APPROVED = "SEMANTICALLY_APPROVED"
    NOT_READY_FOR_VOICE = "NOT_READY_FOR_VOICE"
    READY_FOR_VOICE = "READY_FOR_VOICE"
    APPROVED = "APPROVED"
    FAILED = "FAILED"


class PronunciationStatus(StrEnum):
    NOT_PREPARED = "NOT_PREPARED"
    PREPARED = "PREPARED"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"


class SemanticValidationStatus(StrEnum):
    NOT_VALIDATED = "NOT_VALIDATED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class PronunciationCriticality(StrEnum):
    CRITICAL = "CRITICAL"
    IMPORTANT = "IMPORTANT"
    NORMAL = "NORMAL"


class PronunciationLexiconStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    DEPRECATED = "DEPRECATED"


class LocalizationPipelineStage(StrEnum):
    """Native-script localization progression (§47).

    Persisted on ``LocalizationPipelineRun`` — the truthful stage of one
    target-language production derived from one owner-approved Persian
    script. READY_FOR_VOICE is only reachable after every gate passed on
    the exact locked source hash.
    """

    PENDING = "PENDING"
    SEMANTIC_ALIGNED = "SEMANTIC_ALIGNED"
    COVERAGE_TRANSLATED = "COVERAGE_TRANSLATED"
    NATIVE_DRAFTED = "NATIVE_DRAFTED"
    NATIVE_REVIEW = "NATIVE_REVIEW"
    FIDELITY_REVIEW = "FIDELITY_REVIEW"
    FINAL_FIDELITY = "FINAL_FIDELITY"
    DURATION_READY = "DURATION_READY"
    READY_FOR_VOICE = "READY_FOR_VOICE"
    BLOCKED = "BLOCKED"
    # The Persian source changed after approval — downstream work is no
    # longer anchored to the locked draft and must be regenerated.
    STALE_SOURCE = "STALE_SOURCE"
    FAILED = "FAILED"
