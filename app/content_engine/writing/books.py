"""Book/author reference policy for final scripts.

Final scripts may naturally reference real non-Persian books and authors
when the attribution is supported by the frozen upstream artifacts
(EvidenceMatrix / ResearchPackage / KnowledgeUnits). The selector proposes
candidates from evidence claim text; ``allowed_book_references`` is the
deterministic gate that rejects Persian-language books (by source
metadata, never by how the title is rendered in the script), unverifiable
quotes, blanks, duplicates, and caps the set — so writer and critics share
one authoritative allow-list per draft.

Quote provenance: a ``verified_quote`` must come from RAW SOURCE wording
(KnowledgeUnit ``full_text`` reconstructed from source segments, imported
book text, or web-source excerpts). Generated evidence claim text is a
summary/paraphrase — wording that only appears there is never enough for
a direct quote and is downgraded to paraphrase instead.

The rule is about the BOOK, not the rendering: a Persian-translated or
Persian-script title of an English book is presentation and is allowed.
``book_reference_findings`` is the deterministic draft-side check for
quoted wording near an attribution.
"""

import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

# Persian-language books must not be used for explicit spoken-book
# references. Normalized lowercase ISO codes and names are rejected.
PERSIAN_LANGUAGE_MARKERS = frozenset(
    {"fa", "fas", "per", "persian", "farsi", "فارسی", "دری", "تاجیکی"}
)

MAX_BOOK_REFERENCES = 4

# A quoted span this close to a book/author mention reads as the author's
# own words; anything quoted there must be verifiable wording.
_QUOTE_ATTRIBUTION_RADIUS = 160
# Tighter radius for generic «در کتاب ...» citation contexts — they name
# no specific author, so only directly adjacent quotes count.
_BOOK_CONTEXT_RADIUS = 120
# Proximity alone is not attribution: a rhetorical inner-voice quote
# («من کافی نیستم») inside a paragraph that happens to name a book is
# NOT the author's wording. A quoted span only counts as attributed when
# it sits in an attribution construction — direct apposition to the
# anchor («براون از «…»») or a reporting verb linking anchor and quote
# inside one sentence zone.
_APPOSITION_RADIUS = 45
_VERB_QUOTE_RADIUS = 90
_VERB_ANCHOR_RADIUS = 60
_BOOK_MENTION = re.compile(r"کتاب")
_QUOTED_SPAN = re.compile(r"[«\"“„]([^»\"”]+?)[»\"“”]")
_WORD = re.compile(r"[\w\u0600-\u06ff]+")
_SENTENCE_BOUNDARY = re.compile(r"[.!?؟\n]")
# Reporting verbs/phrases that bind quoted wording to an author or book.
# Third-person/reporting forms only — «می‌گوییم»/«می‌پرسیم» are narrator
# voice, not attribution.
_ATTRIBUTION_VERB = re.compile(
    r"(می‌گوید|می‌گویند|می‌گفت|می‌گفتند|گفت|گفتند|می‌نویسد|می‌نویسند|نوشت|"
    r"نوشتند|می‌خواند|می‌خوانیم|می‌خوانند|خوانده|توضیح می‌دهد|نشان می‌دهد|"
    r"بیان می‌کند|مطرح می‌کند|ادعا می‌کند|استدلال می‌کند|حرف می‌زند|"
    r"صحبت می‌کند|می‌نامد|می‌نامند|نامید|نامیده|به تعبیر|به قول|به روایت|"
    r"آمده است|می‌آورد|آورده است|می‌گوید که|says|said|writes|wrote|argues|"
    r"calls|claims)"
)


class BookReference(BaseModel):
    """One citable book.

    ``title`` is the ORIGINAL title; ``title_fa``/``author_fa`` are
    optional Persian renderings for natural script/UI presentation.
    ``original_language`` is the book's source-language metadata — a
    missing value cannot be certified non-Persian and is dropped by the
    gate. ``verified_quote`` may only carry wording that literally
    appears in raw source text; the gate blanks anything else.
    """

    model_config = ConfigDict(extra="forbid")

    author: str = Field(min_length=1)
    title: str = Field(min_length=1)
    original_language: str = ""
    supported_idea: str = Field(min_length=1)
    author_fa: str = ""
    title_fa: str = ""
    verified_quote: str = ""


class BookReferenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    references: list[BookReference] = Field(default_factory=list)


@dataclass(frozen=True)
class BookReferenceFinding:
    code: str
    message: str
    location: str
    blocking: bool = False


BOOK_REFERENCE_SELECTION_INSTRUCTIONS = """From the evidence claims, \
select a small set of real published non-Persian books whose authors and \
ideas are genuinely supported by the given claims. Rules: the book must \
really exist; the author/title attribution must be correct; the book's \
source language must NOT be Persian (English, German, French, Arabic, \
etc. are fine) — set original_language to that source language, or leave \
it empty when unknown (the reference will then be dropped); the \
supported idea must trace to a listed claim, not to general knowledge. \
For each reference also provide author_fa (the established or natural \
Persian rendering of the author's name) and title_fa (a natural Persian \
rendering of the title — not a literal calque). Set verified_quote ONLY \
to a short passage copied exactly, word-for-word, from the provided raw \
SOURCE EXCERPTS when they contain the author's or the book's own wording; \
leave it empty otherwise — never compose a quote from memory and never \
copy wording that only appears in the generated evidence claims (claims \
are paraphrases, not source text). Return at most a \
few references — fewer is better; return an empty list when the evidence \
does not clearly support any specific book. Never guess famous books \
that merely fit the topic."""


BOOK_REFERENCE_WRITER_POLICY = """Book references \
(only when allowed_book_references is non-empty; otherwise this section \
does not apply): the listed entries are the ONLY books and authors you \
may name — never invent or mention another book, author, or quotation. \
Each entry carries the author, the ORIGINAL title, the book's source \
language (original_language — a Persian rendering of the title does not \
make the book Persian), the supported idea, optional Persian renderings \
(author_fa, title_fa), and optionally a verified_quote whose wording is \
confirmed verbatim by the evidence.

Usage modes — choose per context: \
(a) paraphrase: attribute the idea naturally, e.g. «ساپولسکی در Behave \
توضیح می‌دهد که ...» — no quotation marks needed; \
(b) direct quote: allowed ONLY as the entry's verified_quote reproduced \
word-for-word; a Persian translation of a verified quote must be \
presented as a translation (e.g. «به تعبیر او»), never inside quotation \
marks as the author's own words; \
(c) critical attribution: when the script discusses rather than endorses \
the claim, use distancing verbs (ادعا می‌کند، استدلال می‌کند، این برداشت \
را مطرح می‌کند) — a book arguing X is not science proving X.

Title rendering: original title only, its Persian rendering only, or \
Persian title plus the original in parentheses on first mention — pick \
what reads most naturally in spoken Persian; you may use the provided \
title_fa or render naturally. Vary the attribution phrasing across the \
script and never repeat the full bilingual citation mechanically. Never \
put a coined Persian phrase in quotation marks as if it were the \
author's own term — render the concept in your own words or name the \
real term. Use references only where they add context, authority, \
contrast, or critique — using none of the listed references is a valid \
choice; a script never needs a book reference."""


BOOK_REFERENCE_CHECKS: tuple[str, ...] = (
    "every book or author named in the script must appear in "
    "allowed_book_references (code BOOK_REFERENCE_UNVERIFIED when a "
    "named book/author is absent from the list)",
    "the language rule is SOURCE METADATA, not presentation: code "
    "BOOK_REFERENCE_PERSIAN only when the cited book's source language "
    "(its original_language metadata or known publication fact) is "
    "Persian — a Persian-translated or Persian-script TITLE of a "
    "non-Persian book is allowed rendering and must never be flagged; "
    "never infer book language from script text",
    "direct quotations attributed to a book/author must reproduce the "
    "entry's verified_quote exactly or be wording that appears verbatim "
    "in the grounded raw source text; code BOOK_REFERENCE_INVENTED_QUOTE for "
    "quotation-marked wording presented as the author's own words that "
    "matches neither — a coined Persian phrase quoted as the author's "
    "term counts; a translation marked as translation does not",
    "a book's claim must not be inflated into proof (code "
    "BOOK_REFERENCE_OVERCLAIM when 'a book argues X' is rendered as "
    "'science/research proves X' or the book is cited as settling a "
    "debated question)",
)


def allowed_book_references(
    selection: BookReferenceSelection,
    source_texts: list[str] | tuple[str, ...] = (),
) -> list[BookReference]:
    """Deterministic gate over the selector output.

    Drops references whose source language is Persian or unknown (a
    missing language cannot be certified non-Persian — omit, do not
    guess), blank fields, and duplicate (author, title) pairs; blanks a
    ``verified_quote`` that does not appear verbatim in the RAW SOURCE
    texts (KnowledgeUnit full_text / imported source excerpts) — wording
    that only exists in generated evidence claims can never certify a
    direct quote; caps the set. Whatever survives is the only material
    the writer and the critics may treat as citable.
    """

    source_blob = _word_blob(" ".join(source_texts))
    allowed: list[BookReference] = []
    seen: set[tuple[str, str]] = set()
    for ref in selection.references:
        language = ref.original_language.strip().lower()
        if not language or language in PERSIAN_LANGUAGE_MARKERS:
            continue
        if not (ref.author.strip() and ref.title.strip()):
            continue
        key = (ref.author.strip().casefold(), ref.title.strip().casefold())
        if key in seen:
            continue
        seen.add(key)
        quote = ref.verified_quote.strip()
        if quote and _word_blob(quote) not in source_blob:
            quote = ""  # not verbatim source wording → paraphrase only
        allowed.append(ref.model_copy(update={"verified_quote": quote}))
        if len(allowed) >= MAX_BOOK_REFERENCES:
            break
    return allowed


def reference_usage(text: str, references: list[BookReference]) -> list[bool]:
    """Per-reference flag: does the script visibly use this reference?

    Matches the author (or surname), its Persian rendering, and the
    original or Persian title — presentation only, never a judgment
    about the book's language.
    """

    lowered = text.casefold()
    return [any(name in lowered for name in _anchor_names(ref)) for ref in references]


def book_reference_findings(
    text: str,
    references: list[BookReference],
    source_texts: list[str] | tuple[str, ...] = (),
) -> list[BookReferenceFinding]:
    """Deterministic draft checks on the frozen allow-list.

    - A Persian-language entry in the list is a blocker (the gate should
      have removed it; provenance may predate the gate).
    - Quotation-marked wording in an ATTRIBUTION CONSTRUCTION near a
      book/author mention must be a verified quote or verbatim RAW SOURCE
      wording — a coined phrase in quotes reads as the author's own
      term. Attribution requires a grammatical link: direct apposition
      («براون از «…» حرف می‌زند» / «کتاب: «…»») or a reporting verb
      bound to the anchor in the same sentence. A rhetorical inner-voice
      quote inside a paragraph that merely mentions the book is not
      flagged — proximity alone is not attribution.
    Title renderings never fire: a quoted span that names the book is
    presentation, not quotation.
    """

    findings: list[BookReferenceFinding] = []
    for ref in references:
        if ref.original_language.strip().lower() in PERSIAN_LANGUAGE_MARKERS:
            findings.append(
                BookReferenceFinding(
                    "BOOK_REFERENCE_PERSIAN",
                    f"Allow-listed book '{ref.title}' is Persian-language by "
                    "source metadata and must not be cited.",
                    location=ref.title,
                    blocking=True,
                )
            )
    if not references:
        return findings
    anchors = _anchor_spans(text, references)
    # «در کتاب ...» mentions are attribution contexts too — the writer may
    # only name listed books, so a quote near a book mention reads as that
    # book's wording even when the transliterated name is unknown.
    book_mentions = [(m.start(), m.end()) for m in _BOOK_MENTION.finditer(text)]
    if not anchors and not book_mentions:
        return findings
    source_blob = _word_blob(" ".join(source_texts))
    title_blobs = {
        _word_blob(title)
        for ref in references
        for title in (ref.title, ref.title_fa)
        if title.strip()
    }
    verified = {
        _word_blob(ref.verified_quote)
        for ref in references
        if ref.verified_quote.strip()
    }
    # Anchor zones: (start, end, radius) for named refs and کتاب mentions.
    zones = [(start, end, _QUOTE_ATTRIBUTION_RADIUS) for start, end in anchors] + [
        (start, end, _BOOK_CONTEXT_RADIUS) for start, end in book_mentions
    ]
    verbs = [(m.start(), m.end()) for m in _ATTRIBUTION_VERB.finditer(text)]
    for match in _QUOTED_SPAN.finditer(text):
        segment = match.group(1).strip()
        blob = _word_blob(segment)
        if len(blob.split()) < 2:
            continue  # single-word quotes are emphasis, not quotations
        if blob in title_blobs or blob in verified:
            continue
        if source_blob and blob in source_blob:
            continue  # verbatim raw-source wording → verified
        # «کتاب «عنوان»» — a quoted span naming the book directly after
        # the word کتاب is a title citation, not a quotation.
        if any(0 < match.start() - kend <= 2 for _kstart, kend in book_mentions):
            continue
        # A quote explicitly labeled as a translation («به ترجمهٔ آزاد»,
        # «به تعبیر فارسی») is honest rendering, not fabricated source
        # wording — the writer must not present it as the original.
        if _marked_translation(text, match.start(), match.end()):
            continue
        if _attributed_quote(text, match.start(), match.end(), zones, verbs):
            findings.append(
                BookReferenceFinding(
                    "BOOK_REFERENCE_INVENTED_QUOTE",
                    "Quoted wording attributed to a book/author is neither "
                    "a verified quote nor verbatim evidence wording; "
                    "paraphrase it or use the verified quote exactly.",
                    location=segment[:120],
                )
            )
    return findings


_TRANSLATION_MARKER = re.compile(r"(ترجمه|تعبیر|ترجمهٔ آزاد)")


def _marked_translation(text: str, quote_start: int, quote_end: int) -> bool:
    """True when the quote's own sentence labels it as a translation."""

    start = text.rfind("\n", 0, quote_start) + 1
    for boundary in _SENTENCE_BOUNDARY.finditer(text[:quote_start]):
        start = boundary.end()
    end = len(text)
    tail = _SENTENCE_BOUNDARY.search(text, quote_end)
    if tail is not None:
        end = tail.start()
    return bool(_TRANSLATION_MARKER.search(text[start:end]))


def _attributed_quote(
    text: str,
    quote_start: int,
    quote_end: int,
    zones: list[tuple[int, int, int]],
    verbs: list[tuple[int, int]],
) -> bool:
    """True when the quoted span is grammatically bound to an attribution.

    Two link shapes count:
    - apposition — the anchor directly introduces the quote in the same
      sentence («براون از «…»») or directly follows it (««…» که براون»);
    - reporting verb — a saying/writing verb sits near the quote AND the
      same verb's clause contains the anchor (براون … می‌گوید), so the
      quote is what the author said — not what an inner voice said.
    """

    for start, end, radius in zones:
        if max(0, start - quote_end, quote_start - end) > radius:
            continue
        before = text[end:quote_start]
        after = text[quote_end:start]
        if (
            0 <= quote_start - end <= _APPOSITION_RADIUS
            and not _SENTENCE_BOUNDARY.search(before)
        ):
            return True
        if (
            0 <= start - quote_end <= _APPOSITION_RADIUS
            and not _SENTENCE_BOUNDARY.search(after)
        ):
            return True
        for verb_start, verb_end in verbs:
            # The verb must share the quote's clause AND belong to the
            # anchor's clause — a sentence boundary between verb and
            # quote means the quote answers to a different subject (e.g.
            # an inner voice), not to the book.
            if (
                max(0, verb_start - quote_end, quote_start - verb_end)
                > _VERB_QUOTE_RADIUS
            ):
                continue
            verb_quote_span = text[
                min(verb_start, quote_start) : max(verb_end, quote_end)
            ]
            if _SENTENCE_BOUNDARY.search(verb_quote_span):
                continue
            if (
                0 <= verb_start - end <= _VERB_ANCHOR_RADIUS
                and not _SENTENCE_BOUNDARY.search(text[end:verb_start])
            ):
                return True
    return False


def _word_blob(value: str) -> str:
    """Word sequence used for verbatim comparison — punctuation-agnostic."""

    return " ".join(_WORD.findall(value.casefold()))


def _anchor_names(ref: BookReference) -> set[str]:
    """Surface forms that anchor an attribution in rendered text."""

    names: set[str] = set()
    for raw in (ref.author, ref.author_fa, ref.title, ref.title_fa):
        name = raw.strip().casefold()
        if len(name) >= 4:
            names.add(name)
    for raw in (ref.author, ref.author_fa):
        tokens = raw.split()
        if len(tokens) > 1 and len(tokens[-1]) >= 3:
            names.add(tokens[-1].casefold())  # surname alone anchors too
    return names


def _anchor_spans(text: str, references: list[BookReference]) -> list[tuple[int, int]]:
    lowered = text.casefold()
    spans: list[tuple[int, int]] = []
    for ref in references:
        for name in _anchor_names(ref):
            start = lowered.find(name)
            while start != -1:
                spans.append((start, start + len(name)))
                start = lowered.find(name, start + 1)
    return spans
