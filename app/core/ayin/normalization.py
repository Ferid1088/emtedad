"""Deterministic Persian search normalization that never replaces raw text."""

import re
import unicodedata

_BIDI_CONTROLS = dict.fromkeys(
    map(
        ord,
        "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069",
    )
)
_ARABIC_TO_PERSIAN = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ـ": ""})
_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
_WHITESPACE = re.compile(r"\s+")


def normalize_persian_text(value: str) -> str:
    """Normalize Unicode/spacing for search while retaining source separately."""

    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(_BIDI_CONTROLS)
    normalized = normalized.translate(_ARABIC_TO_PERSIAN)
    normalized = _ZERO_WIDTH.sub(" ", normalized)
    return _WHITESPACE.sub(" ", normalized).strip()


def digits_to_ascii(value: str) -> str:
    """Convert Unicode decimal digits without altering non-digit text."""

    converted: list[str] = []
    for character in value:
        try:
            converted.append(str(unicodedata.digit(character)))
        except (TypeError, ValueError):
            converted.append(character)
    return "".join(converted)
