"""Content engine vocabulary."""

from enum import StrEnum


class PlanStatus(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    SUPERSEDED = "SUPERSEDED"


class ProductionStage(StrEnum):
    BRIEF = "BRIEF"
    THESIS = "THESIS"
    RESEARCH = "RESEARCH"
    EVIDENCE = "EVIDENCE"
    ARGUMENT = "ARGUMENT"
    NARRATIVE = "NARRATIVE"
    MASTER = "MASTER"
    SCRIPT = "SCRIPT"
    REVIEW = "REVIEW"
    APPROVED = "APPROVED"
    LOCALIZATION = "LOCALIZATION"
    VOICE = "VOICE"
    PUBLISHED = "PUBLISHED"


ARGUMENT_PROMPT_VERSION = "argument_architect_v1"
NARRATIVE_PROMPT_VERSION = "narrative_architect_v1"


class DraftStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    REVISED = "REVISED"
    APPROVED = "APPROVED"
    ARCHIVED = "ARCHIVED"


class FindingSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKER = "BLOCKER"


class FindingStatus(StrEnum):
    OPEN = "OPEN"
    ADDRESSED = "ADDRESSED"
    WAIVED = "WAIVED"


class CriticRole(StrEnum):
    FACT = "FACT"
    LOGIC = "LOGIC"
    CHANNEL_SPECIFIC = "CHANNEL_SPECIFIC"
    RETENTION = "RETENTION"
    ORIGINALITY = "ORIGINALITY"
    PERSIAN_QUALITY = "PERSIAN_QUALITY"  # deterministic fa checks (writing/*)


SCRIPT_PROMPT_VERSION = "script_writer_v1"
CRITIC_PROMPT_VERSION = "critic_v1"
REVISION_PROMPT_VERSION = "revision_v1"
