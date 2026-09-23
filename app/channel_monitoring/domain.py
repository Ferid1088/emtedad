from enum import StrEnum


class CandidateStatus(StrEnum):
    NEW = "NEW"
    SELECTED = "SELECTED"
    IMPORTING = "IMPORTING"
    IMPORTED = "IMPORTED"
    IGNORED = "IGNORED"
    FAILED = "FAILED"
