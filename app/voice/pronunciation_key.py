"""Persian pronunciation key (text side, before any voice is rendered).

Persian script hides short vowels, so a voice engine guesses them — and a
wrong guess says another word: «ملک» melk / molk / malek / malak. A
pronunciation agent marks, per sentence, every word whose reading is not
obvious, decides the reading from the MEANING of the sentence, and gives
harakat that force it. The voice text gets those harakat; subtitles keep
the plain text. Ported from the TrueCrime documentary pipeline
(pronunciation check), adapted to Emtedad: the source is Persian itself,
and the vocabulary is philosophical/mystical.
"""

import asyncio
import json
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest

PROMPT_VERSION = "pronunciation_key_v1"

HARAKAT = "\u064b\u064c\u064d\u064e\u064f\u0650\u0651\u0652\u0670"
_HARAKAT_RE = re.compile(f"[{HARAKAT}]")
_WORD_CH = f"\\w{HARAKAT}\u200c"
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?؟!…])\s+|\n+")


def strip_harakat(text: str) -> str:
    return _HARAKAT_RE.sub("", text or "")


def reading_vowels(read: str) -> list[str]:
    """Latin reading (molk, jannat, aakhare) → vowel classes."""

    r = (read or "").lower().replace("ā", "aa").replace("â", "aa")
    out: list[str] = []
    i = 0
    while i < len(r):
        two = r[i : i + 2]
        if two == "aa":
            out.append("A")
            i += 2
        elif two in ("ii", "ee"):
            out.append("i")
            i += 2
        elif two in ("oo", "uu", "ou"):
            out.append("u")
            i += 2
        elif r[i] in "aeiou":
            out.append(r[i])
            i += 1
        else:
            i += 1
    return out


_HARAKA_VOWEL = {"\u064e": "a", "\u0650": "e", "\u064f": "o"}


def harakat_agree(form: str, read: str) -> bool:
    """The harakat of a vowelled form say the same short vowels, in order,
    as the reading. If they disagree, one of them is wrong — the entry is
    not trusted. A final kasra (ezafe) is allowed."""

    marks = [_HARAKA_VOWEL[c] for c in form if c in _HARAKA_VOWEL]
    short = [v for v in reading_vowels(read) if v in ("a", "e", "o")]
    k = 0
    for i, v in enumerate(marks):
        while k < len(short) and short[k] != v:
            k += 1
        if k == len(short):
            return i == len(marks) - 1 and v == "e" and form.endswith("\u0650")
        k += 1
    return True


def _levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _tokens(sentence: str) -> set[str]:
    return {strip_harakat(t) for t in re.findall(f"[{_WORD_CH}]+", sentence or "")}


def _bare(text: str) -> str:
    return strip_harakat(text).replace("\u200c", "").strip()


def validate_key(sentence: str, words: list[dict[str, object]]) -> list[dict[str, str]]:
    """Keep only usable entries: the word is in the sentence, the reading is
    Latin, vowelled/full forms keep the letters and agree with the reading."""

    toks = _tokens(sentence)
    ok: list[dict[str, str]] = []
    for w in words or []:
        if not isinstance(w, dict):
            continue
        word = strip_harakat(str(w.get("w") or "")).strip()
        read = str(w.get("read") or "").strip().lower()
        if not word or word not in toks:
            continue
        if (
            not read
            or not re.fullmatch(r"[a-z'\- ]+", read)
            or not reading_vowels(read)
        ):
            continue
        entry = {"w": word, "read": read, "meaning": str(w.get("meaning") or "")[:60]}
        disagree = False
        for key in ("vowelled", "full"):
            form = str(w.get(key) or "").strip()
            if form and strip_harakat(form) == word and form != word:
                if not harakat_agree(form, read):
                    disagree = True
                    continue
                entry[key] = form
        if disagree:
            continue
        respell = str(w.get("respell") or "").strip()
        if (
            respell
            and respell != word
            and " " not in respell
            and _levenshtein(_bare(respell), word) <= 2
        ):
            entry["respell"] = respell
        synonym = " ".join(str(w.get("synonym") or "").split())
        if synonym and _bare(synonym) != _bare(word) and len(synonym.split()) <= 3:
            entry["synonym"] = synonym
        if any(k in entry for k in ("vowelled", "full", "respell")):
            ok.append(entry)
    return ok


KEY_INSTRUCTIONS = """
You are a Persian pronunciation editor for a lecture/documentary narrated
by a text-to-speech voice. Persian script does not show short vowels, so
the voice guesses them — and a wrong guess turns the word into another
word: «ملک» melk (estate) / molk (realm) / malek (king) / malak (angel);
«شکر» shekar (sugar) / shokr (thanks); «مهر» mehr (love) / mohr (seal);
«سر» sar (head) / serr (secret); «کرم» karam (generosity) / kerm (worm);
«عالم» aalam (world) / aalem (scholar); «حکمت» hekmat; «معرفت» ma'refat;
«تجلی» tajalli; «فنا» fanaa; «بقا» baghaa.

For every sentence, list the words whose reading is NOT obvious from the
letters: homographs, words often misread, words with tashdid, Arabic loan
words and Quranic/mystical terms, rare or literary words, and foreign
names. Decide each word's reading from the MEANING of the sentence and its
passage. Skip words every reader says correctly (و، در، به، از، که، این،
است، بود ...).

For each listed word give:
- "w": the word exactly as written in the sentence (same letters)
- "read": its pronunciation in simple Latin letters: a (short a), aa (long
  ā), e, o, i (long i), u (long u); kh, gh, sh, ch, zh; ' for ع/ء;
  doubled consonants written twice (tajalli)
- "meaning": a few words
- "vowelled": the same word with the FEWEST harakat that force this reading
  (fatha َ kasra ِ damma ُ, tashdid ّ, sukun ْ) — the letters must stay
  exactly the same: «مُلک», «تَجَلّی»
- "full": the same word with harakat on every letter that needs one
- "respell": only if harakat may not be enough: a spelling that can only be
  read one way, otherwise ""
- "synonym": a word with the SAME meaning here that nobody can misread, or ""

Return one entry per input sentence (an empty "words" list is fine).
""".strip()


class _Word(BaseModel):
    model_config = ConfigDict(extra="ignore")
    w: str = ""
    read: str = ""
    meaning: str = ""
    vowelled: str = ""
    full: str = ""
    respell: str = ""
    synonym: str = ""


class _Sentence(BaseModel):
    model_config = ConfigDict(extra="ignore")
    i: int
    words: list[_Word] = Field(default_factory=list)


class _KeyOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sentences: list[_Sentence] = Field(default_factory=list)


@dataclass
class PronunciationKey:
    sentences: list[str]
    words: dict[int, list[dict[str, str]]] = field(default_factory=dict)

    @property
    def entries(self) -> list[dict[str, str]]:
        return [entry for i in sorted(self.words) for entry in self.words[i]]

    def voice_text(self, level: str = "vowelled") -> str:
        """Text for the voice engine: risky words carry their harakat.
        level: vowelled | full | respell (falls back to the gentler form)."""

        order = {
            "vowelled": ("vowelled",),
            "full": ("full", "vowelled"),
            "respell": ("respell", "full", "vowelled"),
        }[level]
        out: list[str] = []
        for index, sentence in enumerate(self.sentences):
            text = sentence
            for entry in self.words.get(index, []):
                form = next((entry[k] for k in order if entry.get(k)), "")
                if form:
                    text = re.sub(
                        rf"(?<![{_WORD_CH}]){re.escape(entry['w'])}(?![{_WORD_CH}])",
                        form,
                        text,
                        count=1,
                    )
            out.append(text)
        return " ".join(out)


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]


class PronunciationKeyEditor:
    """Runs the key agent over all sentences, in parallel chunks."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str = "configured-default",
        sentences_per_call: int = 25,
        concurrency: int = 4,
    ) -> None:
        self.provider = provider
        self.model = model
        self.size = sentences_per_call
        self.semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _call(self, chunk: list[tuple[int, str]]) -> dict[int, list[_Word]]:
        payload = {"sentences": [{"i": i, "text": t} for i, t in chunk]}
        async with self.semaphore:
            result = await self.provider.extract(
                StructuredExtractionRequest(
                    task="pronunciation_key",
                    prompt_version=PROMPT_VERSION,
                    model=self.model,
                    instructions=KEY_INSTRUCTIONS,
                    input_text=json.dumps(payload, ensure_ascii=False),
                    output_model=_KeyOutput,
                )
            )
        output = _KeyOutput.model_validate(result.model_dump())
        return {s.i: s.words for s in output.sentences}

    async def annotate(self, text: str) -> PronunciationKey:
        sentences = split_sentences(text)
        indexed = list(enumerate(sentences))
        chunks = [indexed[k : k + self.size] for k in range(0, len(indexed), self.size)]
        results = await asyncio.gather(*(self._call(c) for c in chunks))
        key = PronunciationKey(sentences=sentences)
        for result in results:
            for index, words in result.items():
                if 0 <= index < len(sentences):
                    valid = validate_key(
                        sentences[index], [w.model_dump() for w in words]
                    )
                    if valid:
                        key.words[index] = valid
        return key
