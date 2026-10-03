"""Quality sprint: concept validation, unit flags, epistemic, telemetry."""

import pytest

from app.knowledge.units.concepts import (
    ConceptProposal,
    normalize_concept_name,
    normalize_role,
    validate_concept_proposal,
)
from app.knowledge.units.domain import ClaimType, EvidenceLevel, KnowledgeUnitType
from app.knowledge.units.quality import (
    SUMMARY_ROLE,
    span_overlap_ratio,
    unit_quality_flags,
)
from app.research.epistemic import (
    EpistemicStatus,
    classify_epistemic,
    unknown_evidence_warnings,
)


def test_span_overlap_ratio() -> None:
    assert span_overlap_ratio((1, 10), (3, 8)) == 1.0  # fully nested
    assert span_overlap_ratio((1, 4), (3, 6)) == 0.5
    assert span_overlap_ratio((1, 4), (5, 10)) == 0.0
    assert span_overlap_ratio((0.0, 416.0), (100.0, 200.0)) == 1.0


def test_quality_flags_oversized_parent_becomes_summary() -> None:
    flags = unit_quality_flags(
        full_text="word " * 1400,
        duration_seconds=400.0,
        atomic=False,
        has_unit_children=True,
    )
    assert flags["retrieval_role"] == SUMMARY_ROLE
    assert flags["size_warning"]["duration_seconds"] == 400.0


def test_quality_flags_oversized_atomic_never_summary() -> None:
    """Story atomicity gate: atomic units never get a SUMMARY role."""

    flags = unit_quality_flags(
        full_text="word " * 2000,
        duration_seconds=600.0,
        atomic=True,
        has_unit_children=False,
    )
    assert "retrieval_role" not in flags
    assert flags["size_warning"]  # still warned


def test_quality_flags_normal_unit_clean() -> None:
    assert (
        unit_quality_flags(
            full_text="short text",
            duration_seconds=30.0,
            atomic=False,
            has_unit_children=True,
        )
        == {}
    )


def test_concept_name_normalization() -> None:
    assert normalize_concept_name("Fear of Abandonment!") == "fear of abandonment"
    assert normalize_concept_name("  تستوسترون  ") == "تستوسترون"


def test_concept_role_normalization() -> None:
    assert normalize_role("PRIMARY_TOPIC") == "PRIMARY"
    assert normalize_role("MENTIONED") == "CONTEXT"
    assert normalize_role("garbage") == "CONTEXT"
    assert normalize_role("CONTRAST") == "CONTRAST"


@pytest.mark.parametrize(
    "name,reason",
    [
        ("   ", "empty"),
        ("people", "noise"),
        ("thing", "noise"),
        ("example", "noise"),
        ("the interesting way humans become jealous over time", "sentence_length"),
    ],
)
def test_concept_proposal_rejected(name: str, reason: str) -> None:
    assert validate_concept_proposal(ConceptProposal(canonical_name=name)) == reason


def test_concept_proposal_low_confidence_rejected() -> None:
    proposal = ConceptProposal(canonical_name="attachment", confidence=0.1)
    assert validate_concept_proposal(proposal) == "low_confidence"


def test_concept_proposal_accepted() -> None:
    proposal = ConceptProposal(canonical_name="fear of abandonment", confidence=0.9)
    assert validate_concept_proposal(proposal) is None


def test_epistemic_story_is_anecdotal_not_scientific() -> None:
    assert (
        classify_epistemic(
            unit_type=KnowledgeUnitType.STORY,
            claim_type=ClaimType.FACT,
            evidence_level=EvidenceLevel.PRIMARY,
        )
        == EpistemicStatus.ANECDOTAL
    )


def test_epistemic_experiment_fact_is_strong() -> None:
    assert (
        classify_epistemic(
            unit_type=KnowledgeUnitType.EXPERIMENT,
            claim_type=ClaimType.FACT,
            evidence_level=EvidenceLevel.SECONDARY,
        )
        == EpistemicStatus.STRONG_EVIDENCE
    )


def test_epistemic_interpretation_is_philosophical() -> None:
    assert (
        classify_epistemic(
            unit_type=KnowledgeUnitType.EXPLANATION,
            claim_type=ClaimType.INTERPRETATION,
            evidence_level=EvidenceLevel.SECONDARY,
        )
        == EpistemicStatus.PHILOSOPHICAL_INTERPRETATION
    )


def test_epistemic_unknown_stays_unknown() -> None:
    assert (
        classify_epistemic(
            unit_type=KnowledgeUnitType.EXPLANATION,
            claim_type=ClaimType.UNKNOWN,
            evidence_level=EvidenceLevel.NONE,
        )
        == EpistemicStatus.UNKNOWN
    )


def test_epistemic_counterargument_is_contested() -> None:
    assert (
        classify_epistemic(
            unit_type=KnowledgeUnitType.COUNTERARGUMENT,
            claim_type=ClaimType.FACT,
            evidence_level=EvidenceLevel.SECONDARY,
        )
        == EpistemicStatus.CONTESTED
    )


def test_unknown_warning_only_for_science_channel() -> None:
    items = [("1", "UNKNOWN"), ("2", "STRONG_EVIDENCE")]
    assert unknown_evidence_warnings(items, channel_slug="science-mystery") == [
        "REVIEW_REQUIRED: evidence item 1 has UNKNOWN epistemic status"
    ]
    assert unknown_evidence_warnings(items, channel_slug="emtedad") == []


@pytest.mark.asyncio
async def test_extractor_rejection_telemetry() -> None:
    """Invalid unit_type proposals are counted; the batch continues."""

    from unittest.mock import AsyncMock, MagicMock
    from uuid import uuid4

    from app.knowledge.units.extractor import KnowledgeUnitExtractor

    good_id, bad_id = str(uuid4()), str(uuid4())
    provider = MagicMock()
    provider.name = "fixture"
    provider.extract = AsyncMock(
        return_value=MagicMock(
            model_dump=lambda: {
                "units": [
                    {
                        "node_id": good_id,
                        "unit_type": "CLAIM",
                        "title": "t",
                        "summary": "s",
                    },
                    {
                        "node_id": bad_id,
                        "unit_type": "ARGUMENT",
                        "title": "t2",
                        "summary": "s2",
                    },
                ]
            }
        )
    )
    node = MagicMock()
    node.id = good_id
    node.node_type.value = "ARGUMENT"
    node.title = "t"
    node.summary = "s"
    node.start_segment_id = node.end_segment_id = None
    proposals, rejections = await KnowledgeUnitExtractor(provider).propose([node], {})
    assert good_id in proposals
    assert rejections == {"unit_type:ARGUMENT": 1}
