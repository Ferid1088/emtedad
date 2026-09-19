"""Typed states for external knowledge ingestion and review."""

from enum import StrEnum


class SourceType(StrEnum):
    YOUTUBE_VIDEO = "youtube_video"
    PODCAST_EPISODE = "podcast_episode"
    PDF = "pdf"
    BOOK = "book"
    PAPER = "paper"
    ARTICLE = "article"
    WEBPAGE = "webpage"
    LECTURE = "lecture"
    MANUAL_UPLOAD = "manual_upload"


class IngestionStatus(StrEnum):
    DISCOVERED = "discovered"
    INGESTED = "ingested"
    PARTIAL = "partial"
    FAILED = "failed"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WindowStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EntityType(StrEnum):
    PERSON = "person"
    WORK = "work"
    ORGANIZATION = "organization"
    CONCEPT = "concept"


class WorkType(StrEnum):
    BOOK = "book"
    PAPER = "paper"
    STUDY = "study"
    ARTICLE = "article"
    CHAPTER = "chapter"
    REPORT = "report"
    LECTURE = "lecture"
    OTHER = "other"


class IdentifierScheme(StrEnum):
    DOI = "doi"
    ISBN = "isbn"
    OPENALEX = "openalex"
    OPENLIBRARY = "openlibrary"
    WIKIDATA = "wikidata"
    ORCID = "orcid"
    YOUTUBE = "youtube"


class ResolutionProvider(StrEnum):
    CROSSREF = "crossref"
    OPENALEX = "openalex"
    OPENLIBRARY = "openlibrary"
    WIKIDATA = "wikidata"


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    REVIEW = "review"
    UNRESOLVED = "unresolved"
    REJECTED = "rejected"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    ATTRIBUTED_ONLY = "attributed_only"
    SUPPORTED = "supported"
    MIXED = "mixed"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"
    NOT_APPLICABLE = "not_applicable"


class EvidenceRelation(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXTUALIZES = "contextualizes"
    MENTIONS = "mentions"
    BACKGROUND = "background"
    UNCLEAR = "unclear"


class MediaType(StrEnum):
    COVER = "cover"
    PAPER_PDF = "paper_pdf"
    FIRST_PAGE = "first_page"
    PORTRAIT = "portrait"
    THUMBNAIL = "thumbnail"


class MediaStatus(StrEnum):
    AVAILABLE = "available"
    UNKNOWN_RIGHTS = "unknown_rights"
    NO_ACCESSIBLE_PDF = "no_accessible_pdf_found"
    INVALID = "invalid"
    FAILED = "failed"


class ReviewReason(StrEnum):
    AMBIGUOUS_PERSON = "ambiguous_person"
    AMBIGUOUS_WORK = "ambiguous_work"
    UNCERTAIN_TITLE = "uncertain_title"
    UNRESOLVED_REFERENCE = "unresolved_reference"
    MULTIPLE_HIGH_SCORING_MATCHES = "multiple_high_scoring_matches"
    POTENTIAL_DUPLICATE_ENTITY = "potential_duplicate_entity"
    TRANSCRIPT_ANOMALY = "transcript_anomaly"
    EXTRACTION_ANOMALY = "extraction_anomaly"
    UNSUPPORTED_METADATA = "unsupported_metadata"
    MEDIA_RIGHTS_UNCERTAINTY = "media_rights_uncertainty"


class KnowledgeReviewStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class LabelKind(StrEnum):
    CANONICAL = "canonical"
    ALIAS = "alias"
    TRANSLATION = "translation"
    TRANSLITERATION = "transliteration"
