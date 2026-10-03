"""Deterministic novelty scoring against prior candidates' concept sets."""

from uuid import UUID


def jaccard(left: set[UUID], right: set[UUID]) -> float:
    if not left and not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def novelty_score(concept_ids: set[UUID], existing: list[set[UUID]]) -> float:
    """1 - max Jaccard overlap with any existing candidate's concepts."""

    if not concept_ids or not existing:
        return 1.0
    return round(1.0 - max(jaccard(concept_ids, prior) for prior in existing), 4)
