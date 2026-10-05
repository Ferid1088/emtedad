"""Deterministic generation validation — before formal review.

The writer contract is a *generation* contract: a draft that is far under
its spoken-duration budget, carries corrupted characters, or collapses the
narrative structure is a generation defect, not a review issue. These
checks run inside ``build_script`` before the draft is persisted for
review; failures trigger bounded corrective generation instead of
consuming the semantic revision budget.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from app.content_engine.writing.quality import (
    PersianDraftQualityValidator,
    word_count,
)


@dataclass(frozen=True)
class GenerationCheck:
    code: str
    message: str
    blocking: bool = True


@dataclass(frozen=True)
class GenerationReport:
    """Outcome of the pre-review generation validation for one attempt."""

    passed: bool
    word_count: int
    duration_minutes: float
    band_min_words: int
    band_max_words: int
    checks: tuple[GenerationCheck, ...] = field(default_factory=tuple)

    def payload(self) -> dict[str, Any]:
        """JSON-safe shape persisted in ``draft.provenance_json``."""

        return {
            "passed": self.passed,
            "word_count": self.word_count,
            "duration_minutes": round(self.duration_minutes, 2),
            "band_min_words": self.band_min_words,
            "band_max_words": self.band_max_words,
            "failed_checks": list(
                dict.fromkeys(c.code for c in self.checks if c.blocking)
            ),
        }


def validate_generation(
    text: str,
    *,
    language: str,
    target_minutes: float,
    wpm: int,
    section_count: int,
    min_ratio: float,
    max_ratio: float,
    evidence_texts: list[str] | None = None,
) -> GenerationReport:
    """Hard generation-contract checks on a raw writer output.

    - encoding: U+FFFD replacement chars mean corrupted provider output —
      repair/regenerate, never persist as clean content.
    - duration: word count inside the first-draft tolerance band around
      ``target_minutes * wpm`` (ratios are configurable; ~0.85–1.15).
    - structure: a multi-beat narrative cannot collapse into a couple of
      paragraphs; require a minimum paragraph floor.
    - Persian drafts additionally run the deterministic draft-quality
      validator (scaffolding leakage, evidence dumps, duplicated
      paragraphs, non-Persian prose).
    """

    checks: list[GenerationCheck] = []
    words = word_count(text)
    minutes = words / wpm if wpm else 0.0
    band_min = round(target_minutes * wpm * min_ratio)
    band_max = round(target_minutes * wpm * max_ratio)

    if "\ufffd" in text:
        checks.append(
            GenerationCheck(
                "ENCODING_CORRUPTION",
                "Replacement characters (U+FFFD) remain in generated output.",
            )
        )
    if words < band_min:
        checks.append(
            GenerationCheck(
                "DURATION_BELOW_GENERATION_BAND",
                f"Draft is {minutes:.1f} min ({words} words); generation "
                f"floor is {band_min} words for the {target_minutes}-min target.",
            )
        )
    elif words > band_max:
        checks.append(
            GenerationCheck(
                "DURATION_ABOVE_GENERATION_BAND",
                f"Draft is {minutes:.1f} min ({words} words); generation "
                f"ceiling is {band_max} words for the {target_minutes}-min target.",
            )
        )
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    min_paragraphs = min(4, max(section_count, 1))
    if len(paragraphs) < min_paragraphs:
        checks.append(
            GenerationCheck(
                "NARRATIVE_STRUCTURE_COLLAPSED",
                f"Draft has {len(paragraphs)} paragraphs for "
                f"{section_count} planned narrative beats; the section "
                "budgets were not realized.",
            )
        )
    if any(unicodedata.category(char) == "Cf" and char != "‌" for char in text):
        checks.append(
            GenerationCheck(
                "PDF_EXTRACTION_ARTIFACT",
                "Unicode format controls remain in generated prose.",
            )
        )
    if language == "fa":
        report = PersianDraftQualityValidator().validate(
            text, list(evidence_texts or [])
        )
        for finding in report.findings:
            if finding.blocking:
                checks.append(
                    GenerationCheck(finding.code, finding.message, blocking=True)
                )
    return GenerationReport(
        passed=not checks,
        word_count=words,
        duration_minutes=minutes,
        band_min_words=band_min,
        band_max_words=band_max,
        checks=tuple(checks),
    )
