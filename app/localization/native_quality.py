"""Deterministic gates for native target-language scripts (§54, §56).

Language-agnostic corruption checks plus a dominant-script sanity check
so a German script that is mostly Arabic characters (or vice versa) is
blocked before any semantic work runs. No LLM is spent on these checks.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.content_engine.writing.quality import word_count
from app.lecture.domain import PublicationLanguage


@dataclass(frozen=True)
class TargetScriptFinding:
    code: str
    message: str
    blocking: bool = True


# Internal pipeline phrases that must never leak into audience text,
# across all target languages.
_FORBIDDEN_PHRASES = (
    "Semantic Master",
    "ResearchPackage",
    "LocalizationSemanticPackage",
    "source chunk",
    "retrieved passage",
    "The selected Ayin Working source states",
)

_LATIN_RE = re.compile(r"[A-Za-zÀ-ÿ]")
_ARABIC_RE = re.compile(r"[؀-ۿ]")


def _dominant_share(text: str, language: PublicationLanguage) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    if language in (PublicationLanguage.AR, PublicationLanguage.FA):
        hits = sum(1 for c in letters if _ARABIC_RE.match(c))
    else:
        hits = sum(1 for c in letters if _LATIN_RE.match(c))
    return hits / len(letters)


def _normalize(value: str) -> str:
    cleaned = "".join(
        ch for ch in value if unicodedata.category(ch) != "Cf" or ch == "\u200c"
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def validate_target_script(
    text: str,
    language: PublicationLanguage,
    *,
    min_minutes: float,
    max_minutes: float,
    wpm: int,
) -> tuple[list[TargetScriptFinding], int, float]:
    """Return (findings, words, minutes) for a localized script."""

    findings: list[TargetScriptFinding] = []
    if "\ufffd" in text:
        findings.append(
            TargetScriptFinding(
                "ENCODING_CORRUPTION",
                "Replacement characters (U+FFFD) remain in the script.",
            )
        )
    # ZWNJ is legitimate in Persian and tolerated in Arabic script text.
    allowed_cf = (
        {"\u200c"}
        if language in (PublicationLanguage.FA, PublicationLanguage.AR)
        else set()
    )
    if any(unicodedata.category(ch) == "Cf" and ch not in allowed_cf for ch in text):
        findings.append(
            TargetScriptFinding(
                "CONTROL_CHARS", "Disallowed format-control characters present."
            )
        )
    lowered = text.casefold()
    for phrase in _FORBIDDEN_PHRASES:
        if phrase.casefold() in lowered:
            findings.append(
                TargetScriptFinding(
                    "INTERNAL_LEAKAGE",
                    f"Internal pipeline phrase in prose: {phrase}",
                )
            )
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    normalized = [_normalize(p) for p in paragraphs]
    if normalized and (len(normalized) - len(set(normalized))) / len(normalized) > 0.15:
        findings.append(
            TargetScriptFinding(
                "DUPLICATE_PARAGRAPHS", "Repeated paragraphs exceed 15%."
            )
        )
    sentences = [
        _normalize(part)
        for part in re.split(r"[.!?؟\n]+", text)
        if len(_normalize(part)) >= 40
    ]
    if sentences and (len(sentences) - len(set(sentences))) / len(sentences) > 0.12:
        findings.append(
            TargetScriptFinding(
                "REPEATED_SENTENCES", "Sentences are restated across the script."
            )
        )
    if _dominant_share(text, language) < 0.7:
        findings.append(
            TargetScriptFinding(
                "WRONG_SCRIPT",
                f"Less than 70% of letters are the {language.value} script.",
            )
        )
    words = word_count(text)
    minutes = words / wpm if wpm else 0.0
    if minutes < min_minutes:
        findings.append(
            TargetScriptFinding(
                "DURATION_TOO_SHORT",
                f"{minutes:.1f} min at {wpm} wpm — below {min_minutes} min.",
            )
        )
    elif minutes > max_minutes:
        findings.append(
            TargetScriptFinding(
                "DURATION_TOO_LONG",
                f"{minutes:.1f} min at {wpm} wpm — above {max_minutes} min.",
            )
        )
    return findings, words, minutes
