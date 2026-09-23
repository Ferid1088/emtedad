"""Language-native performance preparation for external voice providers.

This module deliberately stops at text.  It does not call ElevenLabs and it
does not attempt to synthesize audio.  Provider markup is kept in a third,
inspectable representation so publication and pronunciation text stay clean.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.lecture.domain import PublicationLanguage
from app.localization.pronunciation import pronunciation_preserves_text


class PerformanceTag(StrEnum):
    THOUGHTFUL = "thoughtful"
    SOFTLY = "softly"
    PAUSE = "pause"
    CURIOUS = "curious"
    SLOWLY = "slowly"
    DRAWN_OUT = "drawn out"
    RUSHED = "rushed"
    WHISPERS = "whispers"
    LAUGHS = "laughs"
    SIGHS = "sighs"
    CHUCKLES = "chuckles"
    CLEARS_THROAT = "clears throat"


@dataclass(frozen=True, slots=True)
class ElevenLabsCapabilityProfile:
    """Capabilities for one external model, not an audio client."""

    provider: str
    model_id: str
    supported_tags: frozenset[str]
    supports_ssml: bool = False

    @classmethod
    def eleven_v3(cls) -> ElevenLabsCapabilityProfile:
        return cls(
            provider="elevenlabs",
            model_id="eleven_v3",
            supported_tags=frozenset(item.value for item in PerformanceTag),
            supports_ssml=False,
        )


@dataclass(frozen=True, slots=True)
class NativeReviewFinding:
    code: str
    message: str
    blocking: bool = True


@dataclass(frozen=True, slots=True)
class NativeReview:
    language: PublicationLanguage
    findings: tuple[NativeReviewFinding, ...]

    @property
    def passed(self) -> bool:
        return not any(item.blocking for item in self.findings)


class NativeLanguageReviewer:
    """Conservative deterministic review before any performance markup.

    Full editorial judgment remains human/model-assisted.  These checks catch
    obvious pipeline leakage and translationese-shaped scaffolding without
    rewriting the owner's text.
    """

    _LEAKAGE = (
        "ResearchPackage",
        "Semantic Master",
        "source chunk",
        "retrieved passage",
        "The selected Ayin Working source",
    )
    _GERMAN_FORMAL_ADDRESS = re.compile(r"\b(?:Sie|Ihnen|Ihr|Ihre|Ihrem|Ihren|Ihres)\b")

    def review(self, language: PublicationLanguage, text: str) -> NativeReview:
        findings: list[NativeReviewFinding] = []
        if not text.strip():
            findings.append(NativeReviewFinding("EMPTY_TEXT", "Text is empty."))
        if any(marker in text for marker in self._LEAKAGE):
            findings.append(
                NativeReviewFinding(
                    "INTERNAL_SCAFFOLDING",
                    "Internal research scaffolding is visible in the text.",
                )
            )
        if language is PublicationLanguage.DE and self._GERMAN_FORMAL_ADDRESS.search(
            text
        ):
            findings.append(
                NativeReviewFinding(
                    "GERMAN_FORMAL_ADDRESS",
                    "Ayin narration uses formal German address; use du/dich/dir/dein.",
                )
            )
        if re.search(r"(\b\w+\b)(?:\s+\1){3,}", text, re.IGNORECASE):
            findings.append(
                NativeReviewFinding(
                    "REPETITIVE_RHYTHM",
                    "A repeated word pattern needs editorial review.",
                    blocking=False,
                )
            )
        return NativeReview(language, tuple(findings))


class NativeLanguageOptimizer:
    """Safe optimization boundary; never silently edits owner text.

    A future model-backed optimizer can implement this interface.  The
    current default is intentionally identity-preserving and returns a new
    candidate only when a caller explicitly asks for optimization.
    """

    def optimize(self, language: PublicationLanguage, text: str) -> str:
        return text


@dataclass(frozen=True, slots=True)
class PerformancePreparation:
    language: PublicationLanguage
    voice_ready_text: str
    elevenlabs_performance_text: str
    profile: ElevenLabsCapabilityProfile
    findings: tuple[NativeReviewFinding, ...]


_TAG_RE = re.compile(r"\[([^\]\n]+)\]")


class PerformanceDirector:
    """Add sparse, explicit provider cues after native text is approved."""

    def prepare(
        self,
        language: PublicationLanguage,
        voice_ready_text: str,
        *,
        tags_by_paragraph: dict[int, str] | None = None,
        profile: ElevenLabsCapabilityProfile | None = None,
    ) -> PerformancePreparation:
        selected_profile = profile or ElevenLabsCapabilityProfile.eleven_v3()
        paragraphs = voice_ready_text.split("\n\n")
        cues = tags_by_paragraph or {}
        output: list[str] = []
        findings: list[NativeReviewFinding] = []
        for index, paragraph in enumerate(paragraphs):
            tag = cues.get(index)
            if tag is None:
                output.append(paragraph)
                continue
            if tag not in selected_profile.supported_tags:
                findings.append(
                    NativeReviewFinding(
                        "UNSUPPORTED_PERFORMANCE_TAG",
                        f"[{tag}] is not supported by {selected_profile.model_id}.",
                    )
                )
                output.append(paragraph)
            else:
                output.append(f"[{tag}] {paragraph}")
        performance_text = "\n\n".join(output)
        findings.extend(
            PerformanceQualityValidator().validate(
                voice_ready_text, performance_text, selected_profile
            )
        )
        return PerformancePreparation(
            language,
            voice_ready_text,
            performance_text,
            selected_profile,
            tuple(findings),
        )


class PerformanceQualityValidator:
    """Validate provider markup, sparse density, and semantic text identity."""

    def validate(
        self,
        voice_ready_text: str,
        performance_text: str,
        profile: ElevenLabsCapabilityProfile | None = None,
    ) -> list[NativeReviewFinding]:
        selected_profile = profile or ElevenLabsCapabilityProfile.eleven_v3()
        findings: list[NativeReviewFinding] = []
        tags = _TAG_RE.findall(performance_text)
        unsupported = [
            tag for tag in tags if tag not in selected_profile.supported_tags
        ]
        if unsupported:
            findings.append(
                NativeReviewFinding(
                    "UNSUPPORTED_PERFORMANCE_TAG",
                    ", ".join(sorted(set(unsupported))),
                )
            )
        if "<break" in performance_text.lower() or "<speak" in performance_text.lower():
            findings.append(
                NativeReviewFinding(
                    "SSML_NOT_ALLOWED",
                    f"{selected_profile.model_id} uses audio tags, not SSML breaks.",
                )
            )
        word_count = max(1, len(re.findall(r"\b\w+\b", voice_ready_text, re.UNICODE)))
        if len(tags) >= 3 and len(tags) / word_count * 100 > 2:
            findings.append(
                NativeReviewFinding(
                    "EXCESSIVE_TAG_DENSITY",
                    "Performance directions exceed two tags per 100 words.",
                )
            )
        if any(tags[index] == tags[index - 1] for index in range(1, len(tags))):
            findings.append(
                NativeReviewFinding(
                    "REPEATED_PERFORMANCE_TAG",
                    "Adjacent identical performance directions are excessive.",
                    blocking=False,
                )
            )
        without_tags = _TAG_RE.sub("", performance_text)
        if not pronunciation_preserves_text(voice_ready_text, without_tags):
            findings.append(
                NativeReviewFinding(
                    "PERFORMANCE_TEXT_CHANGED",
                    "Performance markup changed the voice-ready text.",
                )
            )
        return findings


def run_native_review(language: PublicationLanguage, text: str) -> NativeReview:
    """Public convenience boundary for the first native-language pass."""

    return NativeLanguageReviewer().review(language, text)
