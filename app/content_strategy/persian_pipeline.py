"""LEGACY_PROVENANCE_ONLY: lesson-semantic review for historical drafts.

The generic stages (quality validator, native reviewer/optimizer, diversity
checks, published memory, text helpers) moved to
``app.content_engine.writing``. What remains here validates a draft against
its pinned ``LessonContentPackage`` snapshot — only reachable through
``PersianEditorialService.review`` on historical lesson-origin drafts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.content_engine.writing.diversity import ScriptDiversityValidator
from app.content_engine.writing.findings import PipelineFinding
from app.content_engine.writing.memory import PublishedMemoryItem
from app.content_engine.writing.native import PersianNativeReviewer
from app.content_engine.writing.text import (
    deduplicate_findings,
    explicit_ayin_reference_ratio,
)
from app.content_strategy.lesson_canon import LessonContentPackage


@dataclass(frozen=True, slots=True)
class ReviewBundle:
    findings: tuple[PipelineFinding, ...]
    published_items_checked: int
    ledger_entries_checked: int
    explicit_ayin_ratio: float


class LessonConsistencyReviewer:
    """Check the draft against the lesson, protected terms, and external package."""

    _protected_conflicts = (
        (r"بُن\s+(?:همان|یعنی)\s+(?:شخصیت|روح)", "BON_REDEFINED"),
        (r"جان\s+(?:همان|یعنی)\s+(?:هوش|آگاهی)", "JAN_REDEFINED"),
        (r"الگو\s+(?:همان|یعنی)\s+هویت", "PATTERN_IDENTITY_CONFLATION"),
        (r"مجال\s+(?:یعنی|همان).*بیرون از علیت", "MAJAL_CAUSALITY_CONFLATION"),
        (r"علم\s+(?:آیین امتداد را\s+)?(?:ثابت|اثبات)\s+کرد", "SCIENCE_PROVES_AYIN"),
    )

    def validate(
        self,
        text: str,
        lesson: LessonContentPackage,
        *,
        external_evidence_count: int,
        published: list[PublishedMemoryItem],
    ) -> list[PipelineFinding]:
        findings: list[PipelineFinding] = []
        for pattern, code in self._protected_conflicts:
            if re.search(pattern, text):
                findings.append(
                    PipelineFinding(
                        code,
                        "DIRECT_CONTRADICTION",
                        "ERROR",
                        "Der Entwurf verletzt eine geschützte Ayin-Unterscheidung.",
                        blocking=True,
                    )
                )
        if external_evidence_count == 0 and re.search(
            r"(?:پژوهش‌ها|مطالعات|دانشمندان)\s+(?:نشان|ثابت)", text
        ):
            findings.append(
                PipelineFinding(
                    "UNSUPPORTED_EXTERNAL_CLAIM",
                    "POSSIBLE_CONTRADICTION",
                    "ERROR",
                    "Der Entwurf beruft sich auf Forschung ohne ausgewählte Quelle.",
                    blocking=True,
                )
            )
        if lesson.what_should_remain_open and not any(
            marker in text for marker in ("پرسش", "باز می‌ماند", "نمی‌دانیم")
        ):
            findings.append(
                PipelineFinding(
                    "OPEN_QUESTION_CLOSED",
                    "POSSIBLE_CONTRADICTION",
                    "WARNING",
                    "Eine im Kanon offene Frage wirkt im Entwurf abgeschlossen.",
                )
            )
        published_concepts = {
            concept for item in published for concept in item.concept_keys
        }
        overlap = published_concepts & set(lesson.core_concepts)
        if overlap:
            findings.append(
                PipelineFinding(
                    "CONCEPT_PREVIOUSLY_COVERED",
                    "DEEPENS",
                    "INFO",
                    "Der Entwurf vertieft bereits veröffentlichte Begriffe.",
                    metadata={"concepts": sorted(overlap)},
                )
            )
        if not any(item.blocking for item in findings):
            findings.append(
                PipelineFinding(
                    "LESSON_MEANING_CONSISTENT",
                    "CONSISTENT",
                    "INFO",
                    "Keine direkte Abweichung vom kanonischen Lektionskern erkannt.",
                )
            )
        return findings


def review_bundle(
    text: str,
    lesson: LessonContentPackage,
    *,
    external_evidence_count: int,
    published: list[PublishedMemoryItem],
    ledger_entries_checked: int,
) -> ReviewBundle:
    """Run archive, ledger, consistency, diversity, and native review after draft."""

    findings = ScriptDiversityValidator().validate(text, published)
    findings.extend(
        LessonConsistencyReviewer().validate(
            text,
            lesson,
            external_evidence_count=external_evidence_count,
            published=published,
        )
    )
    findings.extend(PersianNativeReviewer().review(text))
    return ReviewBundle(
        findings=tuple(deduplicate_findings(findings)),
        published_items_checked=len(published),
        ledger_entries_checked=ledger_entries_checked,
        explicit_ayin_ratio=explicit_ayin_reference_ratio(text),
    )


def final_semantic_findings(
    text: str,
    lesson: LessonContentPackage,
    *,
    external_evidence_count: int,
) -> list[PipelineFinding]:
    """Re-run semantic boundaries after any language optimization."""

    findings = LessonConsistencyReviewer().validate(
        text,
        lesson,
        external_evidence_count=external_evidence_count,
        published=[],
    )
    ratio = explicit_ayin_reference_ratio(text)
    if ratio > 0.12:
        findings.append(
            PipelineFinding(
                "EXCESSIVE_EXPLICIT_AYIN_EXPOSITION",
                "CLARIFIES",
                "WARNING",
                "Explizite Ayin-Passagen dominieren die menschliche Leitfrage.",
                metadata={"estimated_ratio": ratio},
            )
        )
    return findings
