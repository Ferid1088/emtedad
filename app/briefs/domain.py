"""ContentBrief vocabulary."""

from enum import StrEnum


class BriefStatus(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    LOCKED = "LOCKED"
    ARCHIVED = "ARCHIVED"
