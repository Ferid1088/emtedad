"""Conservative multilingual forms used only for retrieval."""

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")
_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
_ZERO_WIDTH = str.maketrans(
    {"\u200b": "", "\u200c": " ", "\u200d": "", "\ufeff": "", "\u2060": ""}
)
_ARABIC_VARIANTS = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ۀ": "ه",
        "ة": "ه",
        "ؤ": "و",
    }
)
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def normalize_search_text(value: str) -> str:
    """Normalize orthographic variants without changing stored source text."""

    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(_ZERO_WIDTH).translate(_ARABIC_VARIANTS)
    normalized = _DIACRITICS.sub("", normalized).casefold()
    return _WHITESPACE.sub(" ", normalized).strip()


def search_tokens(value: str) -> list[str]:
    return _TOKEN.findall(normalize_search_text(value))


def token_count(value: str) -> int:
    return max(1, len(search_tokens(value)))
