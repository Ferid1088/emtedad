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


class StageHealth(StrEnum):
    """Truthful per-stage health derived only from persisted artifacts.

    A stage is READY/APPROVED only when its own artifact exists in a valid
    completion state — never inferred from a later stage's existence.
    """

    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"  # artifact exists but not yet complete
    READY = "READY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"  # artifact exists, open findings
    FAILED = "FAILED"  # artifact run failed; needs owner attention
    APPROVED = "APPROVED"
    # Built from an older version of its upstream artifact (e.g. the
    # argument was rebuilt after this narrative) — must be rebuilt.
    STALE = "STALE"


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


class ReviewRunStatus(StrEnum):
    """Lifecycle of one persisted critic pass over an exact draft hash."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CriticRole(StrEnum):
    FACT = "FACT"
    LOGIC = "LOGIC"
    CHANNEL_SPECIFIC = "CHANNEL_SPECIFIC"
    RETENTION = "RETENTION"
    ORIGINALITY = "ORIGINALITY"
    PERSIAN_QUALITY = "PERSIAN_QUALITY"  # deterministic fa checks (writing/*)


SCRIPT_PROMPT_VERSION = "script_writer_v4"
CRITIC_PROMPT_VERSION = "critic_v2"
REVISION_PROMPT_VERSION = "revision_v1"
