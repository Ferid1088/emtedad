"""Post-draft Persian review and optimization for canonical lesson scripts."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from hashlib import sha256
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content_strategy.lesson_canon import LessonContentPackage
from app.content_strategy.models import (
    ChannelLedgerEntry,
    EditorialProject,
    PersianDraft,
)
from app.content_strategy.persian_quality import clean_source_text
from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest


@dataclass(frozen=True, slots=True)
class PipelineFinding:
    """One owner-readable finding from a distinct post-draft review stage."""

    code: str
    category: str
    severity: str
    message: str
    blocking: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


class ScriptOutline(BaseModel):
    """Internal, stable prose plan; never rendered as final copy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "lesson-script-outline-v1"
    canonical_title: str
    opening_human_situation: str
    central_intellectual_movement: str
    ayin_contribution: str
    external_perspective: str
    tension_or_counterposition: str
    example_strategy: str
    transition_logic: list[str]
    ending_open_question: str
    diversity_profile: dict[str, str]
    selected_example_id: str | None = None
    selected_example_title: str | None = None

    @property
    def content_hash(self) -> str:
        return sha256(
            json.dumps(
                self.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class PublishedMemoryItem:
    project_id: UUID
    title: str
    text: str
    lesson_id: str | None
    concept_keys: tuple[str, ...]
    examples: tuple[str, ...]
    open_promises: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewBundle:
    findings: tuple[PipelineFinding, ...]
    published_items_checked: int
    ledger_entries_checked: int
    explicit_ayin_ratio: float


class _OptimizedPersianOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)


class PublishedMemoryReader:
    """Read only published projects; drafts never become memory implicitly."""

    @staticmethod
    async def load(session: AsyncSession) -> tuple[list[PublishedMemoryItem], int]:
        ledger_rows = list(await session.scalars(select(ChannelLedgerEntry)))
        ledgers = {item.editorial_project_id: item for item in ledger_rows}
        projects = list(
            await session.scalars(
                select(EditorialProject).where(EditorialProject.status == "PUBLISHED")
            )
        )
        memory: list[PublishedMemoryItem] = []
        for project in projects:
            draft = await session.scalar(
                select(PersianDraft)
                .where(
                    PersianDraft.editorial_project_id == project.id,
                    PersianDraft.status == "PERSIAN_APPROVED",
                )
                .order_by(PersianDraft.version_number.desc())
            )
            if draft is None:
                continue
            ledger = ledgers.get(project.id)
            snapshot = project.strategy_topic_snapshot or {}
            package = snapshot.get("lesson_content_package_snapshot", {})
            package = package if isinstance(package, dict) else {}
            concept_keys = (
                tuple(str(item) for item in ledger.concept_keys)
                if ledger
                else tuple(str(item) for item in package.get("core_concepts", []))
            )
            memory.append(
                PublishedMemoryItem(
                    project_id=project.id,
                    title=ledger.published_title if ledger else project.title,
                    text=draft.text,
                    lesson_id=(
                        ledger.lesson_id
                        if ledger
                        else str(snapshot.get("lesson_id") or "") or None
                    ),
                    concept_keys=concept_keys,
                    examples=(
                        tuple(str(item) for item in ledger.examples) if ledger else ()
                    ),
                    open_promises=(
                        tuple(
                            str(item.get("text", ""))
                            for item in ledger.open_promises
                            if isinstance(item, dict) and item.get("text")
                        )
                        if ledger
                        else ()
                    ),
                )
            )
        return memory, len(ledger_rows)


class ScriptDiversityValidator:
    """Detect repeat patterns without exposing archive prose to the writer."""

    def validate(
        self, text: str, published: list[PublishedMemoryItem]
    ) -> list[PipelineFinding]:
        findings: list[PipelineFinding] = []
        words = _words(text)
        opening = set(words[:55])
        ending = set(words[-55:])
        phrases = _ngrams(words, 5)
        paragraph_shape = _paragraph_shape(text)
        for item in published:
            other_words = _words(item.text)
            opening_overlap = _jaccard(opening, set(other_words[:55]))
            ending_overlap = _jaccard(ending, set(other_words[-55:]))
            phrase_overlap = _jaccard(phrases, _ngrams(other_words, 5))
            if opening_overlap >= 0.62:
                findings.append(
                    PipelineFinding(
                        "REPEATED_OPENING_PATTERN",
                        "EXCESSIVE_REPETITION",
                        "WARNING",
                        (
                            "Der Einstieg ähnelt dem veröffentlichten Text "
                            f"„{item.title}“."
                        ),
                        metadata={"overlap": round(opening_overlap, 3)},
                    )
                )
            if ending_overlap >= 0.62:
                findings.append(
                    PipelineFinding(
                        "REPEATED_ENDING_PATTERN",
                        "EXCESSIVE_REPETITION",
                        "WARNING",
                        f"Der Schluss ähnelt dem veröffentlichten Text „{item.title}“.",
                        metadata={"overlap": round(ending_overlap, 3)},
                    )
                )
            if phrase_overlap >= 0.34:
                findings.append(
                    PipelineFinding(
                        "EXCESSIVE_PHRASE_OVERLAP",
                        "EXCESSIVE_REPETITION",
                        "WARNING",
                        (
                            "Zu viele Formulierungen überschneiden sich mit "
                            f"„{item.title}“."
                        ),
                        metadata={"overlap": round(phrase_overlap, 3)},
                    )
                )
            if paragraph_shape and paragraph_shape == _paragraph_shape(item.text):
                findings.append(
                    PipelineFinding(
                        "REPEATED_PARAGRAPH_STRUCTURE",
                        "EXCESSIVE_REPETITION",
                        "INFO",
                        f"Die Absatzbewegung entspricht „{item.title}“.",
                    )
                )
            used_examples = set(_extract_examples(text)) & set(item.examples)
            if used_examples:
                findings.append(
                    PipelineFinding(
                        "REUSED_EXAMPLE",
                        "EXCESSIVE_REPETITION",
                        "WARNING",
                        f"Ein Beispiel wurde bereits in „{item.title}“ verwendet.",
                        metadata={"examples": sorted(used_examples)},
                    )
                )
        return _deduplicate_findings(findings)


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


class PersianNativeReviewer:
    """Ask whether educated readers would recognize the prose as native Persian."""

    _translated_connectors = (
        "از سوی دیگر",
        "در نتیجه",
        "به طور کلی",
        "در این راستا",
        "لازم به ذکر است",
    )

    def review(self, text: str) -> list[PipelineFinding]:
        findings: list[PipelineFinding] = []
        words = _words(text)
        persian_words = [word for word in words if re.search(r"[\u0600-\u06ff]", word)]
        if words and len(persian_words) / len(words) < 0.8:
            findings.append(
                PipelineFinding(
                    "NON_NATIVE_LANGUAGE_MIX",
                    "NATIVE_PERSIAN",
                    "ERROR",
                    "Der Text wirkt nicht wie ursprünglich auf Persisch geschrieben.",
                    blocking=True,
                )
            )
        connector_count = sum(
            text.count(value) for value in self._translated_connectors
        )
        if connector_count >= 4:
            findings.append(
                PipelineFinding(
                    "TRANSLATED_CONNECTOR_PATTERN",
                    "NATIVE_PERSIAN",
                    "WARNING",
                    "Zu viele formelhafte Übergänge erzeugen übersetzten Satzrhythmus.",
                )
            )
        sentences = [item.strip() for item in re.split(r"[.!؟]+", text) if item.strip()]
        long_sentences = [item for item in sentences if len(_words(item)) > 48]
        if long_sentences:
            findings.append(
                PipelineFinding(
                    "UNNATURAL_SENTENCE_LENGTH",
                    "NATIVE_PERSIAN",
                    "WARNING",
                    "Einige Sätze sind für gesprochene persische Prosa zu lang.",
                    metadata={"count": len(long_sentences)},
                )
            )
        starts = [" ".join(_words(item)[:3]) for item in sentences if _words(item)]
        repeated_starts = [
            value for value, count in Counter(starts).items() if count >= 3
        ]
        if repeated_starts:
            findings.append(
                PipelineFinding(
                    "ROBOTIC_SENTENCE_SYMMETRY",
                    "NATIVE_PERSIAN",
                    "WARNING",
                    "Mehrere Sätze beginnen mit derselben mechanischen Struktur.",
                )
            )
        if not findings:
            findings.append(
                PipelineFinding(
                    "NATIVE_PERSIAN_PASS",
                    "NATIVE_PERSIAN",
                    "INFO",
                    (
                        "Der Text besteht die heuristische Prüfung auf natürliche "
                        "persische Prosa."
                    ),
                )
            )
        return findings


class PersianNativeOptimizer:
    """Apply only requested language fixes without receiving archive prose."""

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def optimize(
        self,
        text: str,
        findings: list[PipelineFinding],
        lesson: LessonContentPackage,
        semantic_constraints: list[str],
        owner_style_rules: str | None,
    ) -> str:
        actionable = [
            item
            for item in findings
            if item.category == "NATIVE_PERSIAN" and item.severity != "INFO"
        ]
        if not actionable:
            return text
        payload = {
            "draft": text,
            "language_findings": [
                {"code": item.code, "message": item.message} for item in actionable
            ],
            "canonical_lesson": lesson.model_dump(mode="json"),
            "semantic_constraints": semantic_constraints,
            "owner_style_rules": owner_style_rules,
        }
        result = cast(
            _OptimizedPersianOutput,
            await self.provider.extract(
                StructuredExtractionRequest(
                    task="Minimal native Persian editorial optimization",
                    prompt_version="lesson-native-optimizer-v1",
                    model="configured-default",
                    instructions=(
                        "Rewrite only what the listed language findings require. "
                        "Preserve every claim, uncertainty, protected Ayin term, "
                        "canonical distinction, attribution, and the single central "
                        "movement. Do not add facts, examples, titles, or doctrine. "
                        "Return only the complete optimized Persian script."
                    ),
                    input_text=json.dumps(payload, ensure_ascii=False),
                    output_model=_OptimizedPersianOutput,
                    timeout_seconds=300,
                )
            ),
        )
        return clean_source_text(result.text)


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
        findings=tuple(_deduplicate_findings(findings)),
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


def explicit_ayin_reference_ratio(text: str) -> float:
    sentences = [item.strip() for item in re.split(r"[.!؟]+", text) if item.strip()]
    total = sum(len(_words(item)) for item in sentences)
    explicit = sum(
        len(_words(item))
        for item in sentences
        if "آیین امتداد" in item or "از نگاه آیین" in item
    )
    return round(explicit / max(total, 1), 4)


def extract_ledger_examples(text: str) -> list[str]:
    return _extract_examples(text)


def extract_open_promises(text: str) -> list[dict[str, object]]:
    sentences = [item.strip() for item in re.split(r"[.!؟]+", text) if item.strip()]
    return [
        {"text": item, "status": "OPEN"}
        for item in sentences
        if any(marker in item for marker in ("بعداً", "در آینده", "بعدتر خواهیم"))
    ][:10]


def _words(text: str) -> list[str]:
    return [
        item.casefold()
        for item in re.findall(r"[\w\u0600-\u06ff]+", clean_source_text(text))
    ]


def _ngrams(words: list[str], size: int) -> set[str]:
    return {
        " ".join(words[index : index + size]) for index in range(len(words) - size + 1)
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / max(len(left | right), 1)


def _paragraph_shape(text: str) -> tuple[int, ...]:
    paragraphs = [item for item in re.split(r"\n\s*\n", text) if item.strip()]
    return tuple(min(len(_words(item)) // 20, 8) for item in paragraphs)


def _extract_examples(text: str) -> list[str]:
    sentences = [item.strip() for item in re.split(r"[.!؟]+", text) if item.strip()]
    return [
        item
        for item in sentences
        if any(marker in item for marker in ("مثلاً", "برای مثال", "فرض کنید"))
    ][:12]


def _deduplicate_findings(
    findings: list[PipelineFinding],
) -> list[PipelineFinding]:
    result: list[PipelineFinding] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        key = (finding.code, finding.message)
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result
