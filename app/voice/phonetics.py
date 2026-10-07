"""Phonetic comparison for the Persian pronunciation check.

Ported from the TrueCrime documentary pipeline: compare the short vowels a
word's reading needs (from the pronunciation key) with the IPA phonemes a
wav2vec2 recognizer heard at the word's place in the audio.
"""

import re
from typing import Any

from app.voice.pronunciation_key import _WORD_CH, HARAKAT, reading_vowels, strip_harakat

_IPA_VOWELS = {
    "a": "a",
    "æ": "a",
    "ɐ": "a",
    "ʌ": "a",
    "aː": "A",
    "æː": "A",
    "ɑ": "A",
    "ɑː": "A",
    "ɒ": "A",
    "ɒː": "A",
    "ɔ": "O",
    "ɔː": "O",  # between ā and o in Persian TTS: matches both
    "e": "e",
    "eː": "e",
    "ɛ": "e",
    "ɛː": "e",
    "ə": "e",
    "ɪ": "i",
    "i": "i",
    "iː": "i",
    "y": "i",
    "o": "o",
    "oː": "o",
    "ɵ": "o",
    "u": "u",
    "uː": "u",
    "ʊ": "u",
    "ɯ": "u",
}


_CLOSE = {
    ("a", "A"): 0.5,
    ("e", "i"): 0.5,
    ("o", "u"): 0.5,
    ("A", "o"): 0.1,
    ("O", "A"): 0.0,
    ("O", "o"): 0.0,
    ("O", "a"): 0.6,
    ("O", "u"): 0.5,
}


def _sub_cost(x: str, y: str) -> float:
    if x == y:
        return 0.0
    return _CLOSE.get((x, y), _CLOSE.get((y, x), 1.0))


def ipa_vowels(tokens: list[str]) -> list[str]:
    return [_IPA_VOWELS[t] for t in tokens if t in _IPA_VOWELS]


_CONS = {
    "kh": {"x", "χ", "h"},
    "gh": {"q", "ɢ", "ʁ", "ɣ", "ɡ", "k"},
    "sh": {"ʃ", "s"},
    "ch": {"tʃ", "ʃ"},
    "zh": {"ʒ", "dʒ"},
    "j": {"dʒ", "ʒ", "j"},
    "y": {"j", "i", "iː"},
    "g": {"ɡ", "k"},
    "k": {"k", "ɡ", "c"},
    "v": {"v", "w", "β", "f"},
    "w": {"v", "w"},
    "h": {"h", "ɦ", "x"},
    "r": {"r", "ɾ", "ɹ"},
    "q": {"q", "ɢ", "ʁ", "ɣ"},
    "t": {"t", "d"},
    "d": {"d", "t"},
    "b": {"b", "p"},
    "p": {"p", "b"},
    "s": {"s", "z"},
    "z": {"z", "s"},
    "f": {"f", "v"},
    "m": {"m", "n"},
    "n": {"n", "m", "ŋ"},
    "l": {"l", "ɫ"},
    "'": set(),
}


def reading_consonants(read: str) -> list[set[str]]:
    r = (read or "").lower()
    out, i = [], 0
    while i < len(r):
        two = r[i : i + 2]
        if two in ("kh", "gh", "sh", "ch", "zh"):
            out.append(_CONS[two])
            i += 2
            continue
        ch = r[i]
        # a doubled consonant is one sound
        if ch not in "aeiou -'" and (not out or i == 0 or r[i - 1] != ch):
            out.append(_CONS.get(ch, {ch}))
        i += 1
    return out


def word_tokens(read: str, window: list[str]) -> list[str]:
    """The recognizer's tokens that belong to THIS word: its consonants
    are matched in order inside a generous window (the best-matching
    start wins), so the neighbours' sounds are left out. Falls back to the
    whole window."""
    cons = reading_consonants(read)
    if not cons or not window:
        return window
    best = None  # (matched, -span, a, b)
    for a, tok in enumerate(window):
        if tok not in cons[0]:
            continue
        k, b, matched = 1, a, 1
        for j in range(a + 1, len(window)):
            if k < len(cons) and window[j] in cons[k]:
                k, b, matched = k + 1, j, matched + 1
            elif window[j] not in _IPA_VOWELS and k >= len(cons):
                break
        key = (matched, -(b - a), a, b)
        if best is None or key > best:
            best = key
    if best is None:
        return window
    _, _, a, b = best
    if reading_vowels(read[:1]) and a > 0 and window[a - 1] in _IPA_VOWELS:
        a -= 1  # the word starts with a vowel (andam)
    # vowels after the last matched consonant up to the next consonant
    # belong to the word when it ends in a vowel or a consonant was missed
    matched = best[0]
    if reading_vowels(read[-1:]) or matched < len(cons) or len(cons) == 1:
        while b + 1 < len(window) and window[b + 1] in _IPA_VOWELS:
            b += 1
            if len(cons) == 1:
                break
    return window[a : b + 1]


def vowel_distance(expected: list[str], heard: list[str]) -> tuple[float, int]:
    """(normalized weighted edit distance, hard substitutions). A missing
    vowel (the recognizer often drops one) costs 0.7, an extra one 0.7 —
    except an extra final e (the ezafe the narrator adds before the next
    word), which is free."""
    if heard and expected and len(heard) == len(expected) + 1 and heard[-1] == "e":
        heard = heard[:-1]
    n, m = len(expected), len(heard)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    hard = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + 0.7
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + 0.7
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sub = _sub_cost(expected[i - 1], heard[j - 1])
            options = [
                (dp[i - 1][j - 1] + sub, hard[i - 1][j - 1] + (1 if sub >= 1.0 else 0)),
                (dp[i - 1][j] + 0.7, hard[i - 1][j]),
                (dp[i][j - 1] + 0.7, hard[i][j - 1]),
            ]
            dp[i][j], hard[i][j] = min(options)
    return dp[n][m] / max(n, 1), hard[n][m]


def find_word(text: str, word: str, start: int = 0) -> tuple[int, int] | None:
    """Character span of `word` as a whole word in `text` (harakat in the
    text are allowed: «مُلک» matches «ملک»)."""
    pattern = "".join(re.escape(ch) + f"[{HARAKAT}]*" for ch in strip_harakat(word))
    m = re.compile(f"(?<![{_WORD_CH}]){pattern}(?![{_WORD_CH}])").search(text, start)
    return (m.start(), m.end()) if m else None


def span_times(
    alignment: dict[str, Any], text: str, span: tuple[int, int], t0: float
) -> tuple[float, float] | None:
    """Audio time (block-local after trimming) of a character span, from
    the provider's character timing of exactly this text."""
    chars, starts, ends = (
        alignment["characters"],
        alignment["starts"],
        alignment["ends"],
    )
    if "".join(chars) != text:
        return None
    idx = [
        i for i in range(span[0], min(span[1], len(chars))) if not chars[i].isspace()
    ]
    if not idx:
        return None
    return max(starts[idx[0]] - t0, 0.0), max(ends[idx[-1]] - t0, 0.0)


def judge(
    read: str, heard_tokens: list[str], max_vowel_distance: float = 0.6
) -> dict[str, Any]:
    """Was the word said with the vowels its meaning needs?"""

    expected = reading_vowels(read)
    got = ipa_vowels(word_tokens(read, heard_tokens))
    if not got:
        return {
            "ok": None,
            "expected": expected,
            "heard": got,
            "distance": None,
            "reason": "nothing_heard",
        }
    dist, hard = vowel_distance(expected, got)
    ok = hard == 0 and dist <= max_vowel_distance
    return {
        "ok": ok,
        "expected": expected,
        "heard": got,
        "distance": round(dist, 2),
        "hard_errors": hard,
    }
