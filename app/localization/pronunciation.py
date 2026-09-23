"""Provider-aware pronunciation preparation without changing display text."""

from dataclasses import dataclass

from app.lecture.domain import PublicationLanguage


@dataclass(frozen=True)
class PronunciationPreparation:
    display_text: str
    tts_text: str
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
        tts_text = display_text
        for entry in lexicon:
            written = entry.get("written_form")
            pronunciation = entry.get("preferred_pronunciation")
            if isinstance(written, str) and isinstance(pronunciation, str) and written:
                if add_short_vowels or entry.get("criticality") == "CRITICAL":
                    tts_text = tts_text.replace(written, pronunciation)
                elif provider_profile and isinstance(
                    entry.get("provider_representation"), dict
                ):
                    profile_value = entry["provider_representation"]
                    profile = profile_value if isinstance(profile_value, dict) else {}
                    value = profile.get(provider_profile)
                    if isinstance(value, str):
                        tts_text = tts_text.replace(written, value)
        return PronunciationPreparation(display_text, tts_text, lexicon_version)


class ArabicDiacritizer:
    """Prepare optional Tashkil for speech while retaining Arabic display text."""

    def annotate(
        self,
        display_text: str,
        lexicon: list[dict[str, object]],
        *,
        lexicon_version: int | None = None,
        fully_vocalized: bool = False,
    ) -> PronunciationPreparation:
        tts_text = display_text
        for entry in lexicon:
            written = entry.get("written_form")
            pronunciation = entry.get("preferred_pronunciation")
            if (
                isinstance(written, str)
                and isinstance(pronunciation, str)
                and written
                and (fully_vocalized or entry.get("criticality") == "CRITICAL")
            ):
                tts_text = tts_text.replace(written, pronunciation)
        return PronunciationPreparation(display_text, tts_text, lexicon_version)


def prepare_pronunciation(
    language: PublicationLanguage,
    display_text: str,
    lexicon: list[dict[str, object]],
    *,
    lexicon_version: int | None = None,
) -> PronunciationPreparation:
    """Select the language-specific preparation strategy."""

    if language is PublicationLanguage.FA:
        return PersianPronunciationAnnotator().annotate(
            display_text, lexicon, lexicon_version=lexicon_version
        )
    if language is PublicationLanguage.AR:
        return ArabicDiacritizer().annotate(
            display_text, lexicon, lexicon_version=lexicon_version
        )
    return PronunciationPreparation(display_text, display_text, lexicon_version)
