"""Pure-function coverage for the generic Semantic Master builder."""

from app.content_engine.models import NarrativePlan, NarrativePlanSection
from app.lecture.domain import SectionRole
from app.lecture.generic_service import (
    _NARRATIVE_ROLE_MAP,
    CHANNEL_SEMANTIC_CONSTRAINTS,
    GenericMasterService,
    _section_role,
)


def test_every_channel_seed_slug_has_semantic_constraints() -> None:
    expected = {
        "emtedad",
        "science-mystery",
        "history-human-stories",
        "pop-psychology-relationships",
        "psychology-evolution",
    }
    assert set(CHANNEL_SEMANTIC_CONSTRAINTS) == expected
    assert all(constraints for constraints in CHANNEL_SEMANTIC_CONSTRAINTS.values())


def test_narrative_role_map_only_targets_real_section_roles() -> None:
    assert set(_NARRATIVE_ROLE_MAP.values()) <= set(SectionRole)


def test_known_narrative_roles_map_to_canonical_section_roles() -> None:
    assert _section_role("COLD_OPEN") is SectionRole.HUMAN_ENTRY
    assert _section_role("counterargument") is SectionRole.COUNTERARGUMENT
    assert _section_role("ENDING") is SectionRole.LIFE_RETURN


def test_unmapped_narrative_role_falls_back_to_narrative_beat() -> None:
    assert _section_role("BRAND_NEW_BEAT") is SectionRole.NARRATIVE_BEAT


def test_ending_mode_uses_last_section_method_or_open() -> None:
    plan = NarrativePlan(
        sections=[
            NarrativePlanSection(ordinal=1, ending_method=""),
            NarrativePlanSection(ordinal=2, ending_method="resolved"),
        ]
    )
    assert GenericMasterService._ending_mode(plan) == "RESOLVED"
    assert GenericMasterService._ending_mode(NarrativePlan(sections=[])) == "OPEN"
