"""Protected Ayin terminology used by language and voice preparation."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CanonicalAyinTerm:
    canonical_id: str
    persian_form: str
    canonical_transliteration: str | None
    translation_policy: str
    language_rendering: dict[str, str]
    voice_rendering: dict[str, str]


# Transliteration follows the forms already present in the working seed.  A
# missing form is deliberately represented as None rather than guessed.
CANONICAL_AYIN_TERMS: tuple[CanonicalAyinTerm, ...] = (
    CanonicalAyinTerm(
        "EMTEDAD",
        "امتداد",
        "Emtedad",
        "PRESERVE",
        {"fa": "امتداد", "de": "Emtedad", "en": "Emtedad", "ar": "امتداد"},
        {"fa": "اِمتِداد", "de": "Emtedad", "en": "Emtedad", "ar": "اِمْتِداد"},
    ),
    CanonicalAyinTerm(
        "BON",
        "بُن",
        "Bon",
        "PRESERVE",
        {"fa": "بُن", "de": "Bon", "en": "Bon", "ar": "بُن"},
        {"fa": "بُن", "de": "Bon", "en": "Bon", "ar": "بُن"},
    ),
    CanonicalAyinTerm(
        "JAN",
        "جان",
        "Jan",
        "PRESERVE",
        {"fa": "جان", "de": "Jan", "en": "Jan", "ar": "جان"},
        {"fa": "جان", "de": "Jan", "en": "Jan", "ar": "جان"},
    ),
    CanonicalAyinTerm(
        "MAJAL",
        "مجال",
        "Majal",
        "PRESERVE",
        {"fa": "مجال", "de": "Majal", "en": "Majal", "ar": "مجال"},
        {"fa": "مَجال", "de": "Majal", "en": "Majal", "ar": "مَجال"},
    ),
    CanonicalAyinTerm(
        "TOHIGAH",
        "تهیگاه",
        "Tohigah",
        "PRESERVE",
        {"fa": "تهیگاه", "de": "Tohigah", "en": "Tohigah", "ar": "تهیگاه"},
        {"fa": "تَهیگاه", "de": "Tohigah", "en": "Tohigah", "ar": "تَهیگاه"},
    ),
    CanonicalAyinTerm(
        "BETWEEN",
        "میان",
        "Miyan",
        "PRESERVE",
        {"fa": "میان", "de": "Miyan", "en": "Miyan", "ar": "میان"},
        {"fa": "مِیان", "de": "Miyan", "en": "Miyan", "ar": "مِیان"},
    ),
)


def canonical_terms_for_prompt(language: str) -> str:
    """Return a compact, human-readable preservation instruction."""

    forms = [
        term.language_rendering.get(language)
        or term.canonical_transliteration
        or term.persian_form
        for term in CANONICAL_AYIN_TERMS
    ]
    return ", ".join(forms)


def protected_term_pairs(language: str) -> tuple[tuple[str, str], ...]:
    return tuple(
        (term.persian_form, term.language_rendering.get(language) or term.persian_form)
        for term in CANONICAL_AYIN_TERMS
    )
