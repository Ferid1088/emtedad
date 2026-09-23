"""Provider-aware pronunciation preparation without changing display text.

The preparation layer is deliberately selective.  It adds pronunciation
marks only for approved lexicon entries and a small set of high-risk Ayin
terms/compounds; it never rewrites the publication text.
"""

import re
from dataclasses import dataclass

from app.lecture.domain import PublicationLanguage

# Arabic-script vowel marks used by both Persian and Arabic.  Removing these
# marks is useful for the deterministic ``display == voice`` identity check:
# the two strings must contain the same lexical text, even when one carries
# pronunciation guidance.
PRONUNCIATION_MARKS = frozenset(
    "\u0610\u0611\u0612\u0613\u0614\u0615\u0616\u0617\u0618\u0619"
    "\u061a\u064b\u064c\u064d\u064e\u064f\u0650\u0651\u0652\u0653\u0654"
    "\u0655\u0656\u0657\u0658\u0659\u065a\u065b\u065c\u065d\u065e\u065f\u0670"
)


def strip_pronunciation_marks(text: str) -> str:
    """Return *text* without Arabic-script pronunciation marks."""

    return "".join(
        character for character in text if character not in PRONUNCIATION_MARKS
    )


def pronunciation_preserves_text(display_text: str, voice_text: str) -> bool:
    """Check that voice preparation changed marks only, not lexical content."""

    # Provider cues can add a separating space.  Whitespace normalization is
    # therefore part of identity comparison, while every lexical character is
    # still compared exactly.
    def normalize(value: str) -> str:
        return re.sub(r"\s+", " ", strip_pronunciation_marks(value)).strip()

    return normalize(display_text) == normalize(voice_text)


# These are intentionally small and high-risk rather than a full vocalizer.
# They cover recurring Ayin terminology and common Ezafe examples while
# leaving ordinary Persian prose untouched.
_PERSIAN_CORE_PRONUNCIATIONS = {
    "امتداد": "اِمتِداد",
    "بُن": "بُن",
    "بن": "بُن",
    "جان": "جَان",
    "مجال": "مَجال",
    "میان": "مِیان",
    "تهیگاه": "تَهیگاه",
    "مناسک": "مَناسِک",
}
_PERSIAN_EZAFE_PHRASES = {
    "آیین امتداد": "آیینِ امتداد",
    "راه زندگی": "راهِ زندگی",
    "کتاب من": "کتابِ من",
}
_ARABIC_CORE_PRONUNCIATIONS = {
    "امتداد": "اِمْتِداد",
    "بُن": "بُن",
    "بن": "بُن",
    "جان": "جَان",
    "مجال": "مَجال",
    "میان": "مِیان",
    "تهیگاه": "تَهیگاه",
    "مناسک": "مَناسِک",
    "مناسك": "مَناسِك",
}


@dataclass(frozen=True)
class PronunciationPreparation:
    display_text: str
    voice_text: str
    lexicon_version: int | None


class PersianPronunciationAnnotator:
    """Apply approved term pronunciations while keeping publication text intact."""

    def annotate(
        self,
        display_text: str,
        lexicon: list[dict[str, object]],
        *,
        lexicon_version: int | None = None,
        add_short_vowels: bool = True,
        provider_profile: str | None = None,
    ) -> PronunciationPreparation:
        voice_text = display_text
        # Ezafe is added only for known compounds.  It is never applied to
        # every noun in a sentence, which would make normal Persian unreadable.
        for phrase, marked in _PERSIAN_EZAFE_PHRASES.items():
            voice_text = voice_text.replace(phrase, marked)

        for written, pronunciation in _PERSIAN_CORE_PRONUNCIATIONS.items():
            if written == "امتداد" and "آیینِ امتداد" in voice_text:
                continue
            voice_text = voice_text.replace(written, pronunciation)

        for entry in lexicon:
            written_value = entry.get("written_form")
            if not isinstance(written_value, str) or not written_value:
                continue
            pronunciation_value = _entry_pronunciation(entry, provider_profile)
            if not isinstance(pronunciation_value, str):
                continue
            requires_ezafe = bool(
                entry.get("ezafe")
                or entry.get("requires_ezafe")
                or entry.get("add_ezafe")
            )
            if requires_ezafe and " " in written_value:
                pronunciation_value = written_value.replace(" ", "ِ ", 1)
            if add_short_vowels or entry.get("criticality") == "CRITICAL":
                voice_text = voice_text.replace(written_value, pronunciation_value)
        return PronunciationPreparation(display_text, voice_text, lexicon_version)


class ArabicDiacritizer:
    """Prepare optional Tashkil for speech while retaining Arabic display text."""

    def annotate(
        self,
        display_text: str,
        lexicon: list[dict[str, object]],
        *,
        lexicon_version: int | None = None,
        fully_vocalized: bool = False,
        provider_profile: str | None = None,
    ) -> PronunciationPreparation:
        voice_text = display_text
        for written, pronunciation in _ARABIC_CORE_PRONUNCIATIONS.items():
            voice_text = voice_text.replace(written, pronunciation)
        for entry in lexicon:
            written_value = entry.get("written_form")
            pronunciation_value = _entry_pronunciation(entry, provider_profile)
            if (
                isinstance(written_value, str)
                and isinstance(pronunciation_value, str)
                and written_value
                and (fully_vocalized or entry.get("criticality") == "CRITICAL")
            ):
                voice_text = voice_text.replace(written_value, pronunciation_value)
        return PronunciationPreparation(display_text, voice_text, lexicon_version)


def prepare_pronunciation(
    language: PublicationLanguage,
    display_text: str,
    lexicon: list[dict[str, object]],
    *,
    lexicon_version: int | None = None,
    provider_profile: str | None = None,
) -> PronunciationPreparation:
    """Select the language-specific preparation strategy."""

    if language is PublicationLanguage.FA:
        return PersianPronunciationAnnotator().annotate(
            display_text,
            lexicon,
            lexicon_version=lexicon_version,
            provider_profile=provider_profile,
        )
    if language is PublicationLanguage.AR:
        return ArabicDiacritizer().annotate(
            display_text,
            lexicon,
            lexicon_version=lexicon_version,
            provider_profile=provider_profile,
        )
    return PronunciationPreparation(display_text, display_text, lexicon_version)


def _entry_pronunciation(
    entry: dict[str, object], provider_profile: str | None
) -> object:
    """Select a provider form when one is approved, otherwise the base form."""

    provider_values = entry.get("provider_representation")
    if provider_profile and isinstance(provider_values, dict):
        provider_value = provider_values.get(provider_profile)
        if isinstance(provider_value, str) and provider_value:
            return provider_value
    return entry.get("preferred_pronunciation")
