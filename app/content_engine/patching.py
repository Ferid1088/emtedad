"""Deterministic script sections, patch splicing, and length planning.

Replaces whole-script correction with surgical repair: a script is a
sequence of stable sections (derived from the NarrativePlan when one
exists, else deterministic paragraph groups). Repair models return
*patch operations* — never full text — and the engine splices verified
replacements only:

- a patch must name an existing ``section_id`` and echo the section's
  current sha256 (``expected_original_hash``); mismatch → STALE_PATCH.
- two patches on one section → the second is rejected (OVERLAP).
- untouched sections stay byte-identical by construction — the model
  never sees them in a writable form.

No fuzzy text replacement exists anywhere: identity is section_id +
content hash, not approximate matching.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

SECTION_LABEL_RE = re.compile(r"\[\s*SECTION\s+s\d{2,}\s*[^\]]*\]", re.IGNORECASE)
_PARA_SPLIT_RE = re.compile(r"\n\s*\n")


def split_paragraphs(text: str) -> list[str]:
    """Paragraphs of a script — the deterministic splice atom."""

    return [p.strip() for p in _PARA_SPLIT_RE.split(text) if p.strip()]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class ScriptSection:
    """One stable script section with deterministic identity."""

    section_id: str
    title: str
    text: str
    sha256: str
    words: int

    @staticmethod
    def build(section_id: str, title: str, text: str) -> ScriptSection:
        return ScriptSection(
            section_id=section_id,
            title=title,
            text=text,
            sha256=_sha(text),
            words=len(text.split()),
        )


def sections_from_output(
    items: list[tuple[str, str]], *, titles: dict[str, str] | None = None
) -> list[ScriptSection]:
    """Sections from an ordered (section_id, text) model output."""

    return [
        ScriptSection.build(sid, (titles or {}).get(sid, ""), text)
        for sid, text in items
    ]


def sections_from_paragraph_groups(
    text: str, *, max_section_words: int = 550
) -> list[ScriptSection]:
    """Deterministically group existing prose into patchable sections.

    Used when a draft was not written against a section plan (legacy
    Persian drafts, coverage translations): consecutive paragraphs merge
    until the group approaches ``max_section_words`` — never split mid-
    paragraph, so every section boundary is a real paragraph boundary.
    """

    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return []
    sections: list[ScriptSection] = []
    bucket: list[str] = []
    bucket_words = 0
    for para in paragraphs:
        words = len(para.split())
        if bucket and bucket_words + words > max_section_words:
            sections.append(
                ScriptSection.build(
                    f"s{len(sections) + 1:02d}", "", "\n\n".join(bucket)
                )
            )
            bucket, bucket_words = [], 0
        bucket.append(para)
        bucket_words += words
    if bucket:
        sections.append(
            ScriptSection.build(f"s{len(sections) + 1:02d}", "", "\n\n".join(bucket))
        )
    return sections


def join_sections(sections: list[ScriptSection]) -> str:
    return "\n\n".join(s.text for s in sections)


def labeled_script(sections: list[ScriptSection]) -> str:
    """Critic-facing render: labeled sections so findings can cite IDs."""

    parts = []
    for s in sections:
        label = f"[SECTION {s.section_id}"
        if s.title:
            label += f" — {s.title}"
        label += f", ~{s.words} words]"
        parts.append(f"{label}\n{s.text}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------
# Writer-facing section budgets (§13–14)
# ---------------------------------------------------------------------


class SectionBudget(BaseModel):
    """Per-section word contract handed to the native writers."""

    model_config = ConfigDict(extra="forbid")

    section_id: str
    title: str = ""
    role: str = ""
    purpose: str = ""
    target_words: int
    min_words: int
    max_words: int


def _scaled_budgets(
    weights: list[float],
    titles: list[str],
    roles: list[str],
    purposes: list[str],
    *,
    target_min: int,
    target_max: int,
) -> list[SectionBudget]:
    """Turn relative weights into word budgets reconciled to the band."""

    total = sum(weights) or float(len(weights))
    midpoint = (target_min + target_max) / 2
    budgets: list[SectionBudget] = []
    for i, weight in enumerate(weights):
        target = max(40, int(round(midpoint * weight / total)))
        budgets.append(
            SectionBudget(
                section_id=f"s{i + 1:02d}",
                title=titles[i],
                role=roles[i],
                purpose=purposes[i],
                target_words=target,
                min_words=max(30, int(round(target * 0.8))),
                max_words=int(math.ceil(target * 1.25)),
            )
        )
    return budgets


def build_section_plan(
    *,
    narrative_sections: list[dict[str, object]],
    source_text: str,
    target_min: int,
    target_max: int,
    wpm: int,
) -> list[SectionBudget]:
    """Allocate word budgets across stable sections (§13).

    Narrative-plan sections carry ``target_seconds`` — the canonical
    pacing signal — so budgets are seconds × wpm, rescaled so the plan
    total reconciles to the duration band. Without a plan, consecutive
    source paragraphs group into ~550-source-word sections and budgets
    follow each group's share of the source.
    """

    if narrative_sections:
        weights = [
            float(str(s.get("target_seconds") or 60)) for s in narrative_sections
        ]
        titles = [
            str(s.get("narrative_role") or f"Part {i + 1}")
            for i, s in enumerate(narrative_sections)
        ]
        roles = [str(s.get("narrative_role") or "") for s in narrative_sections]
        purposes = [str(s.get("purpose") or "") for s in narrative_sections]
        return _scaled_budgets(
            weights,
            titles,
            roles,
            purposes,
            target_min=target_min,
            target_max=target_max,
        )
    groups = sections_from_paragraph_groups(source_text)
    weights = [float(s.words) for s in groups]
    return _scaled_budgets(
        weights,
        [f"Part {i + 1}" for i in range(len(groups))],
        [""] * len(groups),
        [""] * len(groups),
        target_min=target_min,
        target_max=target_max,
    )


def budget_map(budgets: list[SectionBudget]) -> dict[str, SectionBudget]:
    return {b.section_id: b for b in budgets}


# ---------------------------------------------------------------------
# Patch operations (§6–8)
# ---------------------------------------------------------------------


class PatchOp(BaseModel):
    """One surgical replacement: a whole-section rewrite, hash-verified."""

    model_config = ConfigDict(extra="forbid")

    section_id: str = Field(min_length=1)
    expected_original_hash: str = Field(min_length=1)
    replacement_text: str = Field(min_length=1)
    finding_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class PatchSetOutput(BaseModel):
    """Repair output: patch ops only — never the whole script."""

    model_config = ConfigDict(extra="forbid")

    patches: list[PatchOp] = Field(default_factory=list)
    # The model may declare the text unrepairable by patches; the caller
    # then takes the explicit FULL_REWRITE path (§11) — never implicitly.
    full_rewrite_required: bool = False
    rewrite_reason: str = ""


@dataclass(frozen=True)
class PatchRejection:
    section_id: str
    reason: str  # MISSING_SECTION | STALE_PATCH | OVERLAP


@dataclass
class PatchResult:
    sections: list[ScriptSection]
    applied: list[PatchOp] = field(default_factory=list)
    rejected: list[PatchRejection] = field(default_factory=list)
    full_rewrite_required: bool = False
    rewrite_reason: str = ""


def apply_patches(sections: list[ScriptSection], output: PatchSetOutput) -> PatchResult:
    """Verify-then-splice: every rejection is explicit, never silent."""

    result = PatchResult(
        sections=list(sections),
        full_rewrite_required=output.full_rewrite_required,
        rewrite_reason=output.rewrite_reason,
    )
    seen: set[str] = set()
    for op in output.patches:
        idx = next(
            (i for i, s in enumerate(result.sections) if s.section_id == op.section_id),
            None,
        )
        if idx is None:
            result.rejected.append(PatchRejection(op.section_id, "MISSING_SECTION"))
            continue
        if op.section_id in seen:
            result.rejected.append(PatchRejection(op.section_id, "OVERLAP"))
            continue
        current = result.sections[idx]
        if current.sha256 != op.expected_original_hash:
            result.rejected.append(PatchRejection(op.section_id, "STALE_PATCH"))
            continue
        seen.add(op.section_id)
        result.sections[idx] = ScriptSection.build(
            current.section_id, current.title, op.replacement_text
        )
        result.applied.append(op)
    return result


def section_provenance(sections: list[ScriptSection]) -> list[dict[str, object]]:
    """Persisted per-draft section truth: id, hash, size, text."""

    return [
        {
            "section_id": s.section_id,
            "title": s.title,
            "words": s.words,
            "sha256": s.sha256,
            "text": s.text,
        }
        for s in sections
    ]


def restore_sections(raw: object, text: str) -> list[ScriptSection]:
    """Rebuild sections from persisted provenance; fallback = one section."""

    if isinstance(raw, list) and raw:
        restored: list[ScriptSection] = []
        for item in raw:
            if not isinstance(item, dict):
                return sections_from_paragraph_groups(text)
            sid = str(item.get("section_id") or "")
            sect_text = str(item.get("text") or "")
            if not sid or not sect_text:
                return sections_from_paragraph_groups(text)
            restored.append(
                ScriptSection.build(sid, str(item.get("title") or ""), sect_text)
            )
        if join_sections(restored) == text:
            return restored
        # Provenance disagrees with the draft text — never trust it.
        return sections_from_paragraph_groups(text)
    return sections_from_paragraph_groups(text)


# ---------------------------------------------------------------------
# Deterministic length repair planning (§16)
# ---------------------------------------------------------------------


class SectionLengthTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str
    current_words: int
    target_words_min: int
    target_words_max: int
    direction: str  # "compress" | "expand"


def length_repair_plan(
    sections: list[ScriptSection],
    budgets: dict[str, SectionBudget],
    *,
    target_min: int,
    target_max: int,
) -> list[SectionLengthTarget]:
    """Allocate the total word delta across sections deterministically.

    Compression draws from the most over-budget sections first;
    expansion fills under-budget headroom first (capped so no section
    may grow past its max budget). The LLM receives explicit per-section
    word targets — code, not the model, decides the arithmetic.
    """

    total = sum(s.words for s in sections)
    if target_min <= total <= target_max:
        return []
    targets: list[SectionLengthTarget] = []
    if total > target_max:
        delta = total - target_max

        def _over(s: ScriptSection) -> int:
            budget = budgets.get(s.section_id)
            return s.words - (budget.target_words if budget else 0)

        ranked = sorted(sections, key=_over, reverse=True)
        remaining = delta
        for s in ranked:
            if remaining <= 0:
                break
            budget = budgets.get(s.section_id)
            floor = int(budget.min_words) if budget else max(60, int(s.words * 0.5))
            room = max(0, s.words - floor)
            take = min(room, remaining)
            if take <= 0:
                continue
            remaining -= take
            new_hi = s.words - take
            new_lo = max(floor, new_hi - max(20, int(new_hi * 0.08)))
            targets.append(
                SectionLengthTarget(
                    section_id=s.section_id,
                    current_words=s.words,
                    target_words_min=new_lo,
                    target_words_max=new_hi,
                    direction="compress",
                )
            )
    else:
        delta = target_min - total

        def _under(s: ScriptSection) -> int:
            budget = budgets.get(s.section_id)
            return (budget.target_words - s.words) if budget else s.words

        ranked = sorted(sections, key=_under, reverse=True)
        remaining = delta
        for s in ranked:
            if remaining <= 0:
                break
            budget = budgets.get(s.section_id)
            ceiling = int(budget.max_words) if budget else int(s.words * 1.6) + 40
            room = max(0, ceiling - s.words)
            take = min(room, remaining)
            if take <= 0:
                continue
            remaining -= take
            new_lo = s.words + take
            new_hi = new_lo + max(20, int(new_lo * 0.08))
            targets.append(
                SectionLengthTarget(
                    section_id=s.section_id,
                    current_words=s.words,
                    target_words_min=new_lo,
                    target_words_max=new_hi,
                    direction="expand",
                )
            )
    return targets


# ---------------------------------------------------------------------
# Monotonic candidate ranking (§3) — shared by both pipelines
# ---------------------------------------------------------------------


def candidate_rank(
    *,
    blockers: int,
    warnings: int,
    fidelity_failed: bool,
    duration_in_band: bool,
    encoding_clean: bool,
    total_findings: int,
) -> tuple[int, int, int, int, int, int]:
    """Hard ordering: blockers → majors → fidelity → duration → encoding.

    The last element is the soft tie-breaker (total findings proxies
    native/narrative quality when hard gates tie). Strictly-lower wins.
    """

    return (
        blockers,
        warnings,
        1 if fidelity_failed else 0,
        0 if duration_in_band else 1,
        0 if encoding_clean else 1,
        total_findings,
    )


def is_better_candidate(candidate: tuple[int, ...], incumbent: tuple[int, ...]) -> bool:
    """Promotion requires a strictly better rank — ties keep the incumbent."""

    return candidate < incumbent
