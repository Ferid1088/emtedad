"""Narrative duration budgeting: the plan's total is a contract."""

from app.content_engine.schemas import NarrativeSectionProposal
from app.content_engine.service import _calibrate_target_seconds


def _section(seconds: int) -> NarrativeSectionProposal:
    return NarrativeSectionProposal(
        ordinal=1,
        narrative_role="explanation",
        purpose="test beat",
        target_seconds=seconds,
    )


def test_in_tolerance_distribution_preserved() -> None:
    sections = [_section(200), _section(400), _section(1000)]
    # 1600 vs 1650 target (~3% off) — keep the model's distribution.
    assert _calibrate_target_seconds(sections, 27.5) == [200, 400, 1000]


def test_underestimating_plan_rescaled_to_target() -> None:
    sections = [_section(120)] * 6  # 720s for a 27.5-min brief
    calibrated = _calibrate_target_seconds(sections, 27.5)
    assert sum(calibrated) == 1650
    assert all(s >= 15 for s in calibrated)


def test_overestimating_plan_rescaled_down() -> None:
    sections = [_section(600), _section(600), _section(600)]  # 30 min
    calibrated = _calibrate_target_seconds(sections, 20.0)
    assert sum(calibrated) == 1200


def test_proportions_survive_scaling() -> None:
    sections = [_section(60), _section(120), _section(240)]
    calibrated = _calibrate_target_seconds(sections, 27.5)
    assert sum(calibrated) == 1650
    # Largest beat stays largest; smallest stays smallest.
    assert calibrated[2] > calibrated[1] > calibrated[0]


def test_minimum_floor_enforced() -> None:
    sections = [_section(1), _section(4000)]
    calibrated = _calibrate_target_seconds(sections, 10.0)
    assert sum(calibrated) >= 600 - 1  # remainder folded into largest
    assert calibrated[0] >= 15
