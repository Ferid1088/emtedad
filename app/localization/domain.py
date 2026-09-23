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
