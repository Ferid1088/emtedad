"""Conservative multilingual normalization for external text identity."""

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_ZERO_WIDTH = str.maketrans({"\u200b": "", "\u200c": " ", "\u200d": "", "\ufeff": ""})
_PERSIAN_VARIANTS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک"})


def normalize_external_text(value: str) -> str:
    """Normalize presentation variants without removing semantic content."""

    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(_ZERO_WIDTH).translate(_PERSIAN_VARIANTS)
    return _WHITESPACE.sub(" ", normalized).strip()


def normalize_identifier(value: str) -> str:
    """Normalize a provider identifier for stable uniqueness checks."""

    return normalize_external_text(value).casefold().strip()
