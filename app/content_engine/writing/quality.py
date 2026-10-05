"""Deterministic quality checks for Persian editorial drafts.

Moved verbatim from the retired lesson-production module. These checks reject
research dumps, extraction artifacts, duplicated paragraphs, and non-Persian
prose regardless of which production path produced the draft.
"""

import re
import unicodedata
from dataclasses import dataclass

from app.content_engine.writing.findings import PipelineFinding


@dataclass(frozen=True)
class PersianDraftFinding:
    code: str
    message: str
    blocking: bool = True


@dataclass(frozen=True)
class PersianDraftQualityReport:
    findings: list[PersianDraftFinding]
    repetition_ratio: float

    @property
    def valid(self) -> bool:
        return not any(item.blocking for item in self.findings)


class PersianDraftQualityValidator:
    """Reject research dumps and extraction artifacts before persistence."""

    _forbidden = (
        "The selected Ayin Working source states",
        "The external source provides evidence",
        "ResearchPackage",
        "Semantic Master",
        "source chunk",
        "retrieved passage",
        "منبع انتخاب‌شده",
        "قطعه بازیابی‌شده",
        "منبع خارجی می‌گوید",
    )

    def validate(
        self, text: str, evidence_texts: list[str]
    ) -> PersianDraftQualityReport:
        findings: list[PersianDraftFinding] = []
        lowered = text.casefold()
        for phrase in self._forbidden:
            if phrase.casefold() in lowered:
                findings.append(
                    PersianDraftFinding(
                        "INTERNAL_SCAFFOLDING_LEAKAGE",
                        f"Internal pipeline phrase leaked into prose: {phrase}",
                    )
                )
        if any(
            unicodedata.category(char) == "Cf" and char != "\u200c" for char in text
        ):
            findings.append(
                PersianDraftFinding(
                    "PDF_EXTRACTION_ARTIFACT",
                    "Unicode format controls remain in prose.",
                )
            )
        if "\ufffd" in text:
            findings.append(
                PersianDraftFinding(
                    "ENCODING_CORRUPTION",
                    "Replacement characters (U+FFFD) remain in prose.",
                )
            )
        paragraphs = [
            item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()
        ]
        normalized = [_normalize(item) for item in paragraphs]
        duplicate_count = len(normalized) - len(set(normalized))
        repetition_ratio = duplicate_count / max(len(normalized), 1)
        if repetition_ratio > 0.15:
            findings.append(
                PersianDraftFinding(
                    "DUPLICATE_PARAGRAPHS",
                    "Repeated paragraphs exceed the permitted ratio.",
                )
            )
        # Filler can hide below paragraph level: the same sentence restated
        # across paragraphs pads duration without adding content.
        sentences = [
            _normalize(part)
            for part in re.split(r"[.!?؟\n]+", text)
            if len(_normalize(part)) >= 40
        ]
        repeated = len(sentences) - len(set(sentences))
        if sentences and (
            repeated / len(sentences) > 0.12
            or any(sentences.count(s) >= 3 for s in set(sentences))
        ):
            findings.append(
                PersianDraftFinding(
                    "REPEATED_SENTENCES",
                    "The same sentences are restated across the draft — "
                    "duration filled by repetition, not content.",
                )
            )
        if evidence_texts:
            leaked = sum(
                1
                for evidence in evidence_texts
                if len(evidence.strip()) >= 120
                and _normalize(evidence) in _normalize(text)
            )
            if leaked:
                findings.append(
                    PersianDraftFinding(
                        "RAW_EVIDENCE_DUMP",
                        "Verbatim evidence blocks were copied into prose.",
                    )
                )
        words = re.findall(r"[\w\u0600-\u06ff]+", text)
        if words:
            non_persian = sum(
                1 for word in words if not re.search(r"[\u0600-\u06ff]", word)
            )
            if non_persian / len(words) > 0.35:
                findings.append(
                    PersianDraftFinding(
                        "EXCESSIVE_NON_PERSIAN_PROSE",
                        "Draft contains too much non-Persian prose.",
                    )
                )
        return PersianDraftQualityReport(findings, repetition_ratio)


def word_count(text: str) -> int:
    """Count spoken words — whitespace-separated tokens.

    A character-class regex would split Persian ZWNJ compounds
    («می‌شود») into two tokens and inflate the count ~15 % over the
    spoken truth, which silently under-reads the duration band. One
    counter drives generation validation, persisted
    ``actual_word_count``, and review-level duration findings.
    """

    return len(re.findall(r"\S+", text))


def duration_findings(
    text: str, target_minutes: float, wpm: int = 110
) -> tuple[list[PipelineFinding], int]:
    """Check the word count against the spoken-duration band (±10%).

    ``wpm`` is the language-specific speech rate; the Persian default of 110
    reproduces the historical 99–121-words-per-minute band exactly.
    """

    count = word_count(text)
    target_min = round(target_minutes * wpm * 0.9)
    target_max = round(target_minutes * wpm * 1.1)
    if target_min <= count <= target_max:
        return [], count
    too_short = count < target_min
    return (
        [
            PipelineFinding(
                "DURATION_TOO_SHORT" if too_short else "DURATION_TOO_LONG",
                "EDITORIAL_DURATION",
                "WARNING",
                (
                    "Der Entwurf ist zu kurz für die gewünschte Sprechdauer."
                    if too_short
                    else "Der Entwurf ist zu lang für die gewünschte Sprechdauer."
                ),
                metadata={
                    "word_count": count,
                    "target_min": target_min,
                    "target_max": target_max,
                    "wpm": wpm,
                },
            )
        ],
        count,
    )


def clean_source_text(value: str) -> str:
    """Remove extraction-only controls while preserving source wording."""

    value = "".join(
        char for char in value if unicodedata.category(char) != "Cf" or char == "\u200c"
    )
    value = value.replace("\u00ad", "")
    value = re.sub(r"(?<=[\u0600-\u06ff])n(?=[\u0600-\u06ff])", "", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n\s*\n\s*\n+", "\n\n", value)
    return value.strip()


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", clean_source_text(value)).strip()
