"""Typed states for chunking, embedding, and hybrid retrieval."""

from enum import StrEnum


class RetrievalLane(StrEnum):
    AYIN = "ayin"
    MANASEK = "manasek"
    EXTERNAL = "external"


class RetrievalSourceKind(StrEnum):
    AYIN_PASSAGE = "ayin_passage"
    RITUAL_PASSAGE = "ritual_passage"
    RITUAL_CONTENT = "ritual_content"
    EXTERNAL_SEGMENT = "external_segment"


class BuildStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class DistanceMetric(StrEnum):
    COSINE = "cosine"


class QueryLanguage(StrEnum):
    FA = "fa"
    EN = "en"
    AR = "ar"


class EvaluationQueryType(StrEnum):
    EXACT_CONCEPT = "exact_concept"
    PARAPHRASE = "paraphrase"
    NAME_OR_TITLE = "name_or_title"
    CROSS_LANGUAGE = "cross_language"
    DISTINCTION_TRAP = "distinction_trap"
    METAPHYSICAL_TRAP = "metaphysical_trap"
    RITUAL_SAFETY = "ritual_safety"
    EXTERNAL_EVIDENCE = "external_evidence"
