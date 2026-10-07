"""Deterministic source-quality categories (no LLM).

The category always stays visible next to the score, so the owner sees
*why* a source ranks high or low. Tuned for Persian and English sources
on philosophy, religion, mysticism, history and culture.
"""

import re

# (pattern on the host, category, weight) — first match wins.
_RULES: tuple[tuple[re.Pattern[str], str, float], ...] = (
    (
        re.compile(
            r"(^|\.)(edu|ac\.[a-z]{2}|ac\.ir)$|plato\.stanford\.edu|jstor\.org|"
            r"springer|sciencedirect|tandfonline|cambridge\.org|"
            r"oup\.com|brill\.com|degruyter|philpapers|doi\.org|"
            r"semanticscholar|researchgate|academia\.edu",
            re.I,
        ),
        "akademisch",
        0.95,
    ),
    (
        re.compile(
            r"sid\.ir|magiran\.com|noormags\.ir|ensani\.ir|civilica\.com|"
            r"irandoc\.ac\.ir|journals\.|jdq\.|\.ut\.ac\.ir",
            re.I,
        ),
        "akademisch",
        0.9,
    ),
    (
        re.compile(
            r"iranicaonline\.org|cgie\.org\.ir|rch\.ac\.ir|britannica\.com|"
            r"encyclopedia|dabe\.ir|wikifeqh\.ir|wikinoor\.ir|iep\.utm\.edu",
            re.I,
        ),
        "Enzyklopädie",
        0.85,
    ),
    (
        re.compile(
            r"ganjoor\.net|noorlib\.ir|lib\.ir|archive\.org|gutenberg\.org|"
            r"wikisource\.org|tebyan\.net|hawzah\.net|hadith|quran",
            re.I,
        ),
        "Primärtext/Archiv",
        0.85,
    ),
    (
        re.compile(
            r"bbc\.(com|co\.uk)|dw\.com|radiofarda|rferl|voanews|iranintl|"
            r"theguardian|nytimes|reuters|apnews|economist|irna\.ir|isna\.ir|"
            r"hamshahrionline|ettelaat",
            re.I,
        ),
        "Journalismus",
        0.7,
    ),
    (re.compile(r"wikipedia\.org", re.I), "Wikipedia", 0.6),
    (re.compile(r"youtube\.com|youtu\.be|aparat\.com|vimeo", re.I), "Video", 0.55),
    (
        re.compile(r"blog|virgool\.io|medium\.com|substack|wordpress|blogfa", re.I),
        "Blog",
        0.35,
    ),
    (
        re.compile(r"reddit\.com|quora\.com|forum|ninisite|telegram|t\.me", re.I),
        "Forum/Social",
        0.2,
    ),
)


def classify_domain(domain: str) -> tuple[str, float]:
    for pattern, category, weight in _RULES:
        if pattern.search(domain):
            return category, weight
    return "Unbekannt", 0.45
