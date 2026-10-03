"""Deterministic epistemic classification for evidence-bearing units.

Combines a unit's structural type, claim type, and evidence level into a
controlled vocabulary. UNKNOWN stays UNKNOWN when nothing supports a
classification — it is a visible signal, never silently upgraded.
"""

from enum import StrEnum

from app.knowledge.units.domain import (
    ClaimType,
    EvidenceLevel,
    KnowledgeUnitType,
)


class EpistemicStatus(StrEnum):
    ESTABLISHED_SCIENCE = "ESTABLISHED_SCIENCE"
    STRONG_EVIDENCE = "STRONG_EVIDENCE"
    LIMITED_EVIDENCE = "LIMITED_EVIDENCE"
    HYPOTHESIS = "HYPOTHESIS"
    CONTESTED = "CONTESTED"
    OPEN_QUESTION = "OPEN_QUESTION"
    SPECULATION = "SPECULATION"
    PHILOSOPHICAL_INTERPRETATION = "PHILOSOPHICAL_INTERPRETATION"
    ANECDOTAL = "ANECDOTAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


def classify_epistemic(
    *,
    unit_type: KnowledgeUnitType,
    claim_type: ClaimType,
    evidence_level: EvidenceLevel,
) -> EpistemicStatus:
    """Classify one unit's epistemic status from its persisted signals.

    Structural type dominates: a story is anecdotal regardless of how
    confidently it is told; an open question stays open.
    """

    if unit_type in {KnowledgeUnitType.STORY, KnowledgeUnitType.CASE_STUDY}:
        return EpistemicStatus.ANECDOTAL
    if unit_type is KnowledgeUnitType.OPEN_QUESTION:
        return EpistemicStatus.OPEN_QUESTION
    if unit_type is KnowledgeUnitType.COUNTERARGUMENT:
        return EpistemicStatus.CONTESTED
    if unit_type is KnowledgeUnitType.DEFINITION:
        return EpistemicStatus.NOT_APPLICABLE
    if claim_type is ClaimType.UNKNOWN:
        return EpistemicStatus.UNKNOWN
    if claim_type in {ClaimType.OPINION, ClaimType.NORMATIVE}:
        return EpistemicStatus.PHILOSOPHICAL_INTERPRETATION
    if claim_type is ClaimType.INTERPRETATION:
        return (
            EpistemicStatus.LIMITED_EVIDENCE
            if unit_type is KnowledgeUnitType.EXPERIMENT
            else EpistemicStatus.PHILOSOPHICAL_INTERPRETATION
        )
    # claim_type FACT:
    if unit_type is KnowledgeUnitType.EXPERIMENT:
        return EpistemicStatus.STRONG_EVIDENCE
    if evidence_level is EvidenceLevel.PRIMARY:
        return EpistemicStatus.STRONG_EVIDENCE
    if evidence_level is EvidenceLevel.SECONDARY:
        return EpistemicStatus.LIMITED_EVIDENCE
    if evidence_level is EvidenceLevel.ANECDOTAL:
        return EpistemicStatus.ANECDOTAL
    return EpistemicStatus.LIMITED_EVIDENCE


def unknown_evidence_warnings(
    items: list[tuple[str, str]], *, channel_slug: str
) -> list[str]:
    """Flag important UNKNOWN evidence for epistemically strict channels.

    ``items`` are (ordinal_label, epistemic_status) pairs. Science &
    Mystery productions get an explicit REVIEW_REQUIRED warning per
    UNKNOWN claim — UNKNOWN is never silently treated as strong evidence.
    """

    if channel_slug != "science-mystery":
        return []
    return [
        f"REVIEW_REQUIRED: evidence item {label} has UNKNOWN epistemic status"
        for label, status in items
        if status == EpistemicStatus.UNKNOWN.value
    ]
