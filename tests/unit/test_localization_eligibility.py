"""Localization eligibility vs historical approval (§30–33, §50).

A Persian master may be historically owner-approved AND fail today's
localization prerequisites — approval is never rewritten, eligibility
is derived fresh per run.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

from app.localization.gate import evaluate_localization_eligibility


def _draft(text: str, *, content_hash: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        language="fa",
        content_hash=content_hash or hashlib.sha256(text.encode()).hexdigest(),
    )


def test_eligible_in_band_master() -> None:
    draft = _draft("کلمه " * 3000)  # 3000 words ≈ 27 min at 110 wpm
    result = evaluate_localization_eligibility(
        draft, min_minutes=25, max_minutes=30, wpm=110
    )
    assert result.eligible
    assert not result.reasons


def test_legacy_short_master_blocked() -> None:
    """fc62e56f-class master: ~7 min → recertification required."""

    draft = _draft("کلمه " * 800)  # ≈7.3 min
    result = evaluate_localization_eligibility(
        draft, min_minutes=25, max_minutes=30, wpm=110
    )
    assert not result.eligible
    assert any("DURATION_TOO_SHORT" in r for r in result.reasons)


def test_oversized_master_blocked() -> None:
    draft = _draft("کلمه " * 4500)  # ≈41 min
    result = evaluate_localization_eligibility(
        draft, min_minutes=25, max_minutes=30, wpm=110
    )
    assert not result.eligible
    assert any("DURATION_TOO_LONG" in r for r in result.reasons)


def test_encoding_corruption_blocked() -> None:
    draft = _draft("کلمه " * 3000 + "\ufffd")
    result = evaluate_localization_eligibility(
        draft, min_minutes=25, max_minutes=30, wpm=110
    )
    assert not result.eligible
    assert any("ENCODING_CORRUPTION" in r for r in result.reasons)


def test_control_chars_blocked() -> None:
    draft = _draft("کلمه " * 3000 + "\x00")
    result = evaluate_localization_eligibility(
        draft, min_minutes=25, max_minutes=30, wpm=110
    )
    assert not result.eligible
    assert any("CONTROL_CHARS" in r for r in result.reasons)


def test_malformed_hash_blocked() -> None:
    draft = _draft("کلمه " * 3000, content_hash="not-a-hash")
    result = evaluate_localization_eligibility(
        draft, min_minutes=25, max_minutes=30, wpm=110
    )
    assert not result.eligible
    assert any("PROVENANCE" in r for r in result.reasons)


def test_supported_material_collects_authority_surface() -> None:
    """Empty claim_ledger is legitimate — repair context must still list
    the package's supported material (§patch-repair source authority)."""
    from app.localization.native_pipeline import _supported_material

    package = {
        "thesis": "Loss aversion drives sunk-cost behaviour.",
        "claim_ledger": [],
        "causal_constraints": [{"rule": "never stronger certainty"}],
        "counterarguments": [{"counter": "habit, not loss aversion"}],
        "story_facts": [{"fact": "the ticket example"}],
        "unresolved_ambiguities": [{"ambiguity": "scope of effect"}],
    }
    material = _supported_material(package)
    assert material[0] == {"thesis": "Loss aversion drives sunk-cost behaviour."}
    assert {"rule": "never stronger certainty"} in material
    assert {"counter": "habit, not loss aversion"} in material
    assert {"fact": "the ticket example"} in material
    assert {"ambiguity": "scope of effect"} in material


def test_supported_material_uses_claim_ledger_when_present() -> None:
    from app.localization.native_pipeline import _supported_material

    material = _supported_material({"claim_ledger": [{"claim": "c1"}], "thesis": "t"})
    assert material[0] == {"thesis": "t"}
    assert {"claim": "c1"} in material


def test_supported_material_handles_missing_or_malformed_fields() -> None:
    from app.localization.native_pipeline import _supported_material

    assert _supported_material({}) == []
    # Non-list payloads are ignored rather than crashing the repair call.
    assert _supported_material({"claim_ledger": "oops", "thesis": "t"}) == [
        {"thesis": "t"}
    ]
