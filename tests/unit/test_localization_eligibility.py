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
