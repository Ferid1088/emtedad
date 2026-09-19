"""Typed Ayin states and version policies."""

from enum import StrEnum


class CorpusZone(StrEnum):
    """Authority zones kept distinct throughout the platform."""

    AYIN_CANON = "AYIN_CANON"
    AYIN_WORKING = "AYIN_WORKING"
    MANASEK_CANON = "MANASEK_CANON"
    MANASEK_WORKING = "MANASEK_WORKING"
    EXTERNAL_PRIMARY = "EXTERNAL_PRIMARY"
    EXTERNAL_DERIVED = "EXTERNAL_DERIVED"
    GENERATED_CONTENT = "GENERATED_CONTENT"


class EditorialStatus(StrEnum):
    """Editorial lifecycle shared by versioned Ayin records."""

    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"


class DiscourseType(StrEnum):
    """The four source-defined Ayin discourse categories."""

    CONCEPTUAL = "CONCEPTUAL"
    DESCRIPTIVE = "DESCRIPTIVE"
    ETHICAL = "ETHICAL"
    OPTIONAL_METAPHYSICAL = "OPTIONAL_METAPHYSICAL"


class DistinctionRelation(StrEnum):
    """Explicit relations that embeddings must not be asked to preserve."""

    IS_NOT = "IS_NOT"
    DISTINCT_FROM = "DISTINCT_FROM"
    DOES_NOT_IMPLY = "DOES_NOT_IMPLY"
    CAN_COEXIST_WITH = "CAN_COEXIST_WITH"
    DEPENDS_ON = "DEPENDS_ON"
    OPEN_RELATION = "OPEN_RELATION"


class OpenQuestionStatus(StrEnum):
    """Lifecycle for questions Ayin deliberately leaves unresolved."""

    OPEN = "open"
    UNDER_REVIEW = "under_review"
    PARTIALLY_ADDRESSED = "partially_addressed"
    RETIRED = "retired"


class LanguageCode(StrEnum):
    """Languages supported by the initial terminology registry."""

    FA = "fa"
    EN = "en"
    AR = "ar"


class TermFormType(StrEnum):
    """Editorial role of one term form."""

    PREFERRED = "preferred"
    TRANSLITERATION = "transliteration"
    EXPLANATORY_GLOSS = "explanatory_gloss"
    ALIAS = "alias"
    HISTORICAL = "historical"
    DEPRECATED = "deprecated"
    FORBIDDEN_EQUIVALENT = "forbidden_equivalent"


class ReviewStatus(StrEnum):
    """State of an extraction/editorial review item."""

    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ReviewKind(StrEnum):
    """Typed reasons for Ayin import review."""

    EXTRACTION_AMBIGUITY = "extraction_ambiguity"
    STRUCTURE_AMBIGUITY = "structure_ambiguity"
    SEED_PROVENANCE = "seed_provenance"


class ReviewReason(StrEnum):
    """Specific extraction conditions requiring later editorial inspection."""

    SUSPICIOUS_EXTRACTION = "suspicious_extraction"
    HEADING_UNCERTAINTY = "heading_uncertainty"
    BROKEN_PARAGRAPH = "broken_paragraph"
    CHARACTER_CORRUPTION = "character_corruption"
    PAGE_LAYOUT_AMBIGUITY = "page_layout_ambiguity"
    POSSIBLE_MISSING_CONTENT = "possible_missing_content"
    SEED_PROVENANCE = "seed_provenance"


APPROVAL_REQUIRED_FIELDS = (
    "semantic_version",
    "approved_by",
    "approved_at",
    "effective_from",
)


def status_allowed_in_zone(zone: CorpusZone, status: EditorialStatus) -> bool:
    """Return whether an Ayin version state is valid for its authority zone."""

    if zone is CorpusZone.AYIN_WORKING:
        return status in {
            EditorialStatus.DRAFT,
            EditorialStatus.REVIEW,
            EditorialStatus.DEPRECATED,
        }
    if zone is CorpusZone.AYIN_CANON:
        return status in {
            EditorialStatus.APPROVED,
            EditorialStatus.SUPERSEDED,
            EditorialStatus.DEPRECATED,
        }
    return False
