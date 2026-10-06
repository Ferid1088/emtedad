"""Unit tests for the deterministic patch engine (§47–49).

Covers hash-verified splicing, stale/overlap rejection, untouched-section
preservation, section budgets, deterministic length planning, and the
monotonic candidate ordering — all without LLM calls.
"""

from __future__ import annotations

from app.content_engine.patching import (
    PatchOp,
    PatchSetOutput,
    apply_patches,
    budget_map,
    build_section_plan,
    candidate_rank,
    is_better_candidate,
    join_sections,
    labeled_script,
    length_repair_plan,
    restore_sections,
    section_provenance,
    sections_from_paragraph_groups,
    split_paragraphs,
)


def _sections(*texts: str):
    # Bucket size 4 → each 3-word paragraph becomes its own section.
    return sections_from_paragraph_groups("\n\n".join(texts), max_section_words=4)


def test_apply_single_patch_verifies_hash() -> None:
    sections = _sections("alpha one two", "beta three four", "gamma five six")
    target = sections[1]
    result = apply_patches(
        sections,
        PatchSetOutput(
            patches=[
                PatchOp(
                    section_id=target.section_id,
                    expected_original_hash=target.sha256,
                    replacement_text="beta rewritten",
                    finding_ids=["F1"],
                    reason="fix it",
                )
            ]
        ),
    )
    assert len(result.applied) == 1
    assert not result.rejected
    assert result.sections[1].text == "beta rewritten"
    # Untouched sections byte-identical.
    assert result.sections[0].text == sections[0].text
    assert result.sections[2].text == sections[2].text


def test_stale_hash_rejected() -> None:
    sections = _sections("alpha", "beta")
    result = apply_patches(
        sections,
        PatchSetOutput(
            patches=[
                PatchOp(
                    section_id="s01",
                    expected_original_hash="0" * 64,
                    replacement_text="changed",
                )
            ]
        ),
    )
    assert not result.applied
    assert result.rejected[0].reason == "STALE_PATCH"
    assert result.sections[0].text == sections[0].text


def test_missing_section_rejected() -> None:
    sections = _sections("alpha")
    result = apply_patches(
        sections,
        PatchSetOutput(
            patches=[
                PatchOp(
                    section_id="s99",
                    expected_original_hash="x",
                    replacement_text="changed",
                )
            ]
        ),
    )
    assert not result.applied
    assert result.rejected[0].reason == "MISSING_SECTION"


def test_duplicate_section_second_rejected() -> None:
    sections = _sections("alpha", "beta")
    op = PatchOp(
        section_id="s01",
        expected_original_hash=sections[0].sha256,
        replacement_text="new",
    )
    result = apply_patches(
        sections,
        PatchSetOutput(patches=[op, op.model_copy(update={"replacement_text": "x"})]),
    )
    assert len(result.applied) == 1
    assert result.rejected[0].reason == "OVERLAP"


def test_untouched_sections_unchanged_across_multi_patch() -> None:
    texts = [f"paragraph {i} with several words here" for i in range(6)]
    sections = _sections(*texts)
    patch = PatchOp(
        section_id="s02",
        expected_original_hash=sections[1].sha256,
        replacement_text="replaced section two",
    )
    result = apply_patches(sections, PatchSetOutput(patches=[patch]))
    unchanged = [s.text for i, s in enumerate(result.sections) if i != 1]
    expected = [t for i, t in enumerate(texts) if i != 1]
    # Every unpatched section is byte-identical to its source paragraph.
    assert unchanged == [e for e in expected]
    assert result.sections[1].text == "replaced section two"


def test_full_rewrite_flag_propagates() -> None:
    sections = _sections("alpha")
    result = apply_patches(
        sections,
        PatchSetOutput(full_rewrite_required=True, rewrite_reason="broken"),
    )
    assert result.full_rewrite_required
    assert result.rewrite_reason == "broken"
    assert not result.applied


def test_split_paragraphs_and_join_roundtrip() -> None:
    text = "Para one.\n\nPara two.\n\n\nPara three."
    parts = split_paragraphs(text)
    assert parts == ["Para one.", "Para two.", "Para three."]
    sections = sections_from_paragraph_groups(text, max_section_words=100)
    assert join_sections(sections) == "Para one.\n\nPara two.\n\nPara three."


def test_labeled_script_marks_sections() -> None:
    sections = _sections("alpha text", "beta text")
    labeled = labeled_script(sections)
    assert "[SECTION s01" in labeled
    assert "alpha text" in labeled


def test_section_provenance_restore_roundtrip() -> None:
    sections = _sections("alpha words here", "beta words there")
    text = join_sections(sections)
    provenance = section_provenance(sections)
    restored = restore_sections(provenance, text)
    assert [s.section_id for s in restored] == [s.section_id for s in sections]
    assert [s.sha256 for s in restored] == [s.sha256 for s in sections]


def test_restore_falls_back_when_provenance_stale() -> None:
    sections = _sections("alpha words here")
    provenance = section_provenance(sections)
    # Tampered provenance disagrees with the text → deterministic fallback.
    restored = restore_sections(provenance, "completely different text")
    assert restored != sections
    assert join_sections(restored) == "completely different text"


def test_build_section_plan_uses_narrative_seconds() -> None:
    budgets = build_section_plan(
        narrative_sections=[
            {"narrative_role": "COLD_OPEN", "purpose": "hook", "target_seconds": 150},
            {"narrative_role": "DEEPENING", "purpose": "core", "target_seconds": 900},
            {"narrative_role": "OUTRO", "purpose": "close", "target_seconds": 150},
        ],
        source_text="x " * 3000,
        target_min=3250,
        target_max=3900,
        wpm=130,
    )
    assert [b.section_id for b in budgets] == ["s01", "s02", "s03"]
    assert budgets[1].target_words > budgets[0].target_words
    # Plan reconciles to the band midpoint.
    total = sum(b.target_words for b in budgets)
    assert abs(total - 3575) < 300
    for b in budgets:
        assert b.min_words < b.target_words < b.max_words


def test_build_section_plan_falls_back_to_paragraph_groups() -> None:
    text = "\n\n".join(f"para {i} " + "word " * 200 for i in range(6))
    budgets = build_section_plan(
        narrative_sections=[],
        source_text=text,
        target_min=3250,
        target_max=3900,
        wpm=130,
    )
    assert budgets
    assert all(b.section_id.startswith("s") for b in budgets)


def test_length_repair_plan_compress() -> None:
    sections = sections_from_paragraph_groups(
        "\n\n".join("word " * 800 for _ in range(6)), max_section_words=900
    )
    budgets = budget_map(
        build_section_plan(
            narrative_sections=[
                {"narrative_role": f"r{i}", "purpose": "", "target_seconds": 60}
                for i in range(6)
            ],
            source_text="x",
            target_min=3250,
            target_max=3900,
            wpm=130,
        )
    )
    plan = length_repair_plan(sections, budgets, target_min=3250, target_max=3900)
    assert plan  # ~4800 words > 3900 → compression required
    assert all(t.direction == "compress" for t in plan)
    assert all(t.target_words_max < t.current_words for t in plan)


def test_length_repair_plan_expand() -> None:
    sections = sections_from_paragraph_groups(
        "\n\n".join("word " * 300 for _ in range(6)), max_section_words=350
    )
    plan = length_repair_plan(sections, {}, target_min=3250, target_max=3900)
    assert plan
    assert all(t.direction == "expand" for t in plan)
    assert all(t.target_words_min > t.current_words for t in plan)


def test_length_repair_plan_in_band_is_empty() -> None:
    sections = sections_from_paragraph_groups("word " * 3500)
    assert length_repair_plan(sections, {}, target_min=3250, target_max=3900) == []


def test_candidate_rank_hard_ordering() -> None:
    clean = candidate_rank(
        blockers=0,
        warnings=0,
        fidelity_failed=False,
        duration_in_band=True,
        encoding_clean=True,
        total_findings=0,
    )
    blocker = candidate_rank(
        blockers=1,
        warnings=0,
        fidelity_failed=False,
        duration_in_band=True,
        encoding_clean=True,
        total_findings=1,
    )
    assert is_better_candidate(clean, blocker)
    assert not is_better_candidate(blocker, clean)
    # A prettier candidate (fewer warnings) loses to fewer blockers.
    pretty_but_blocked = (1, 0, 0, 0, 0, 1)
    plainer_clean = (0, 2, 0, 0, 0, 2)
    assert is_better_candidate(plainer_clean, pretty_but_blocked)
    # Out-of-band duration loses to in-band at equal blocker counts.
    assert is_better_candidate(
        (0, 0, 0, 0, 0, 0),
        (0, 0, 0, 1, 0, 0),
    )
    # Ties keep the incumbent.
    assert not is_better_candidate(clean, clean)
