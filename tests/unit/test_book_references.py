"""Book-reference policy gate (EMTEDAD_FINAL_PHASE4 §18–26)."""

import pytest

from app.content_engine.writing.books import (
    BOOK_REFERENCE_CHECKS,
    MAX_BOOK_REFERENCES,
    BookReference,
    BookReferenceSelection,
    allowed_book_references,
    book_reference_findings,
    reference_usage,
)


def _ref(
    author: str,
    title: str,
    language: str,
    *,
    author_fa: str = "",
    title_fa: str = "",
    verified_quote: str = "",
) -> BookReference:
    return BookReference(
        author=author,
        title=title,
        original_language=language,
        supported_idea="supported idea",
        author_fa=author_fa,
        title_fa=title_fa,
        verified_quote=verified_quote,
    )


def test_persian_language_books_are_rejected_by_source_metadata() -> None:
    """The rule judges the BOOK's source language, not the rendered title.

    A Persian book rejected under an English-rendered title is still
    rejected; only source metadata governs.
    """

    selection = BookReferenceSelection(
        references=[
            _ref("A", "T1", "fa"),
            _ref("B", "The Example Book", "Persian"),  # EN title, FA book
            _ref("C", "T3", "فارسی"),
            _ref("D", "T4", "Farsi"),
        ]
    )

    assert allowed_book_references(selection) == []


def test_non_persian_books_survive_with_persian_rendered_titles() -> None:
    """An English or German book keeps its place even when the script
    will render title_fa — the rendering is presentation, not language."""

    selection = BookReferenceSelection(
        references=[
            _ref(
                "Brené Brown",
                "The Gifts of Imperfection",
                "English",
                title_fa="هدایای ناکامی",
            ),
            _ref("Jonathan Haidt", "The Righteous Mind", "en"),
            _ref("Byung-Chul Han", "Müdigkeitsgesellschaft", "German"),
        ]
    )

    assert len(allowed_book_references(selection)) == 3


def test_missing_source_language_is_omitted_not_assumed_persian() -> None:
    selection = BookReferenceSelection(
        references=[
            _ref("Known", "Real Book", "en"),
            _ref("Unknown", "Mystery Book", ""),
            _ref("Blank", "Another Book", "   "),
        ]
    )

    allowed = allowed_book_references(selection)
    assert [ref.title for ref in allowed] == ["Real Book"]


def test_verified_quote_must_appear_verbatim_in_source_text() -> None:
    source = [
        "Brown writes: what makes you vulnerable makes you beautiful.",
        "Another passage entirely.",
    ]
    selection = BookReferenceSelection(
        references=[
            _ref(
                "Brené Brown",
                "Daring Greatly",
                "en",
                verified_quote="what makes you vulnerable makes you beautiful",
            ),
            _ref(
                "Someone",
                "Fabricated",
                "en",
                verified_quote="words that never appear in the evidence",
            ),
        ]
    )

    allowed = allowed_book_references(selection, source)
    assert allowed[0].verified_quote == (
        "what makes you vulnerable makes you beautiful"
    )
    assert allowed[1].verified_quote == ""  # unverifiable → paraphrase only


def test_quote_wording_only_in_generated_claims_is_downgraded() -> None:
    """Evidence claim text is a paraphrase, never quote authority.

    A verified_quote whose wording exists only in generated claim text
    (not in raw source excerpts) is blanked — the reference survives as
    paraphrase-only instead of certifying a fabricated direct quote.
    """

    claim_text = ["Brown argues that vulnerability is the birthplace of courage."]
    selection = BookReferenceSelection(
        references=[
            _ref(
                "Brené Brown",
                "Daring Greatly",
                "en",
                verified_quote="vulnerability is the birthplace of courage",
            )
        ]
    )
    # The claim text is NOT passed as quote authority — callers now pass
    # raw source excerpts; a quote missing from source downgrades.
    allowed = allowed_book_references(selection, source_texts=[])
    assert allowed[0].verified_quote == ""
    # The gate's keyword is explicitly ``source_texts`` — claim text
    # cannot reach the verbatim check through the old ``evidence_texts``
    # parameter name anymore.
    with pytest.raises(TypeError):
        allowed_book_references(selection, evidence_texts=claim_text)  # type: ignore[call-arg]


def test_generated_claim_resembling_famous_quote_is_not_proof() -> None:
    """A generated claim that happens to echo famous wording cannot
    certify a direct quote when the raw source lacks the wording."""

    famous = "facts do not cease to exist because they are ignored"
    selection = BookReferenceSelection(
        references=[
            _ref(
                "Aldous Huxley",
                "Brave New World Revisited",
                "en",
                verified_quote=famous,
            )
        ]
    )

    allowed = allowed_book_references(selection, source_texts=["Unrelated excerpt."])
    assert allowed[0].verified_quote == ""


def test_verified_quote_matching_tolerates_punctuation_and_case() -> None:
    source = ['She wrote "Vulnerability is not weakness." loudly.']
    selection = BookReferenceSelection(
        references=[
            _ref(
                "A",
                "T",
                "en",
                verified_quote="vulnerability is not weakness",
            )
        ]
    )

    allowed = allowed_book_references(selection, source)
    assert allowed[0].verified_quote == "vulnerability is not weakness"


def test_blank_and_duplicate_references_are_dropped() -> None:
    selection = BookReferenceSelection(
        references=[
            _ref("Sapolsky", "Behave", "en"),
            _ref("sapolsky", "behave", "en"),  # case-insensitive duplicate
            _ref(" ", "T", "en"),
            _ref("Haidt", "The Righteous Mind", "en"),
        ]
    )

    allowed = allowed_book_references(selection)
    assert [ref.title for ref in allowed] == [
        "Behave",
        "The Righteous Mind",
    ]


def test_selection_is_capped() -> None:
    selection = BookReferenceSelection(
        references=[
            _ref(f"Author {i}", f"Title {i}", "en")
            for i in range(MAX_BOOK_REFERENCES + 3)
        ]
    )

    assert len(allowed_book_references(selection)) == MAX_BOOK_REFERENCES


def test_empty_selection_returns_empty() -> None:
    assert allowed_book_references(BookReferenceSelection()) == []


def test_persian_book_surviving_in_allow_list_is_a_blocker() -> None:
    """Defense in depth: provenance predating the gate is still caught."""

    ref = _ref("نویسنده", "کتاب", "fa", author_fa="نویسنده")
    findings = book_reference_findings("این متن درباره کتاب نویسنده است.", [ref])

    assert any(
        item.code == "BOOK_REFERENCE_PERSIAN" and item.blocking for item in findings
    )


def test_invented_quote_near_attribution_is_flagged() -> None:
    """The «آدم‌های خالص» case: a coined phrase in quotes near the author
    reads as the author's term — it must be caught deterministically."""

    ref = _ref(
        "Brené Brown",
        "The Gifts of Imperfection",
        "en",
        author_fa="برنه براون",
        title_fa="هدیه‌های ناکامل‌بودن",
    )
    text = (
        "در کتاب هدیه‌های ناکامل‌بودن براون می‌خوانیم که این آدم‌ها را "
        "او «آدم‌های خالص» می‌نامد و درباره‌شان صحبت می‌کند."
    )

    findings = book_reference_findings(text, [ref], ["wholehearted people"])

    assert any(item.code == "BOOK_REFERENCE_INVENTED_QUOTE" for item in findings)


def test_verified_quote_near_attribution_passes() -> None:
    quote = "what makes you vulnerable makes you beautiful"
    ref = _ref(
        "Brené Brown",
        "Daring Greatly",
        "en",
        author_fa="برنه براون",
        verified_quote=quote,
    )
    text = (
        f"براون در Daring Greatly می‌نویسد: «{quote}» و این جمله را بعدها توضیح می‌دهد."
    )

    findings = book_reference_findings(text, [ref], [quote])

    assert not findings


def test_verbatim_evidence_wording_near_attribution_passes() -> None:
    """A quote that is verbatim evidence wording is verified even without
    a populated verified_quote field."""

    ref = _ref(
        "Robert Sapolsky",
        "Behave",
        "en",
        author_fa="ساپولسکی",
    )
    evidence_quote = "a behavior has just occurred in some context"
    text = (
        f"ساپولسکی در Behave می‌گوید «{evidence_quote}» و سپس لایه‌های "
        "زمانی را باز می‌کند."
    )

    findings = book_reference_findings(text, [ref], [evidence_quote])

    assert not findings


def test_quoted_title_rendering_is_not_a_quote() -> None:
    """کتاب «هدایای ناکامی» — quoting the rendered title is presentation."""

    ref = _ref(
        "Brené Brown",
        "The Gifts of Imperfection",
        "en",
        author_fa="برنه براون",
        title_fa="هدایای ناکامی",
    )
    text = "در کتاب «هدایای ناکامی» براون می‌خوانیم که آدم‌ها گاهی از خودشان فرار می‌کنند."

    findings = book_reference_findings(text, [ref])

    assert not findings


def test_faithful_paraphrase_without_quotes_is_clean() -> None:
    ref = _ref(
        "Brené Brown",
        "The Gifts of Imperfection",
        "en",
        author_fa="برنه براون",
        title_fa="هدایای ناکامی",
    )
    text = (
        "برنه براون در کتاب هدایای ناکامی (The Gifts of Imperfection) "
        "توضیح می‌دهد که آدم‌های تمام‌قلب خودشان را لایق محبت می‌دانند."
    )

    findings = book_reference_findings(text, [ref])

    assert not findings


def test_quoted_title_after_kitab_is_a_citation_not_a_quote() -> None:
    """«کتاب «عنوان»» cites a title — even a title we don't know."""

    ref = _ref(
        "Robert Sapolsky",
        "Behave",
        "en",
        author_fa="ساپولسکی",
    )
    text = (
        "پیش‌تر در کتاب «رفتار» همین بحث آمده بود و حالا ساپولسکی در "
        "Behave آن را عمیق‌تر می‌کند."
    )

    findings = book_reference_findings(text, [ref])

    assert not findings


def test_rhetorical_inner_voice_quote_is_not_book_attribution() -> None:
    """§28 CASE A: narrator's inner-voice quote in a paragraph that
    mentions the book must not read as the author's wording."""

    ref = _ref(
        "Brené Brown",
        "The Gifts of Imperfection",
        "en",
        author_fa="برنه براون",
        title_fa="هدایای ناکامی",
    )
    text = (
        "براون در کتاب هدایای ناکامی آسیب‌پذیری را توضیح می‌دهد. "
        "صدای درون اما همین‌جا می‌گوید: «من کافی نیستم». "
        "این صدا از کتاب نیامده؛ صدای تجربه‌ی روزمره است."
    )

    findings = book_reference_findings(text, [ref])

    assert not any(item.code == "BOOK_REFERENCE_INVENTED_QUOTE" for item in findings)


def test_grammatically_attributed_quote_is_flagged() -> None:
    """§28 CASE B: the author attributing a coined phrase — still caught."""

    ref = _ref(
        "Brené Brown",
        "Daring Greatly",
        "en",
        author_fa="برنه براون",
    )
    text = "براون این وضعیت را «من کافی نیستم» می‌نامد."

    findings = book_reference_findings(text, [ref])

    assert any(item.code == "BOOK_REFERENCE_INVENTED_QUOTE" for item in findings)


def test_unrelated_rhetorical_quote_ignored() -> None:
    """§28 CASE D: a rhetorical quote with no attribution link is ignored."""

    ref = _ref("Robert Sapolsky", "Behave", "en", author_fa="ساپولسکی")
    text = (
        "گاهی از خودمان می‌پرسیم: «چرا دوباره همین اتفاق افتاد؟» "
        "و جوابی نمی‌شنویم. " + "متن کاملاً unrelated. " * 12 + "پایان."
    )

    findings = book_reference_findings(text, [ref])

    assert not findings


def test_book_verb_quote_still_detected() -> None:
    """«در کتاب … می‌خوانیم که «…»» — the کتاب clause's own verb links
    the quote to the book even without a named author nearby."""

    ref = _ref(
        "Brené Brown",
        "Daring Greatly",
        "en",
        author_fa="برنه براون",
    )
    text = (
        "پاراگراف اول. "
        + "متن معمولی برای فاصله. " * 12
        + "در کتاب می‌خوانیم که «آدم‌های شجاع هرگز نمی‌هراسند» و "
        "این تصویر غلط است."
    )

    findings = book_reference_findings(text, [ref])

    assert any(item.code == "BOOK_REFERENCE_INVENTED_QUOTE" for item in findings)


def test_marked_translation_is_not_invented_quote() -> None:
    """A translated quote explicitly labeled as translation is honest."""

    ref = _ref(
        "Jonathan Haidt",
        "The Righteous Mind",
        "en",
        author_fa="جوناتان هایت",
    )
    text = (
        "هایت در The Righteous Mind، به ترجمهٔ آزاد، می‌گوید: "
        "«شهود اول می‌آید، استدلال بعد». این ادعای اصلی اوست."
    )

    findings = book_reference_findings(text, [ref])

    assert not any(item.code == "BOOK_REFERENCE_INVENTED_QUOTE" for item in findings)


def test_unmarked_translation_as_own_words_is_flagged() -> None:
    """The same rendering WITHOUT the translation marker reads as the
    author's own wording — still an invented quote."""

    ref = _ref(
        "Jonathan Haidt",
        "The Righteous Mind",
        "en",
        author_fa="هایت",
    )
    text = "هایت می‌گوید «شهود اول می‌آید، استدلال بعد» و تمام."

    findings = book_reference_findings(text, [ref])

    assert any(item.code == "BOOK_REFERENCE_INVENTED_QUOTE" for item in findings)


def test_reference_usage_detects_rendered_forms() -> None:
    ref = _ref(
        "Brené Brown",
        "The Gifts of Imperfection",
        "en",
        author_fa="برنه براون",
        title_fa="هدایای ناکامی",
    )
    other = _ref("Jonathan Haidt", "The Righteous Mind", "en")

    used = reference_usage("براون در همان کتاب می‌گوید ...", [ref, other])

    assert used == [True, False]


def test_critic_checks_cover_all_policy_failures() -> None:
    joined = " ".join(BOOK_REFERENCE_CHECKS)
    for code in (
        "BOOK_REFERENCE_UNVERIFIED",
        "BOOK_REFERENCE_PERSIAN",
        "BOOK_REFERENCE_INVENTED_QUOTE",
        "BOOK_REFERENCE_OVERCLAIM",
    ):
        assert code in joined
    # The check must point at source metadata, not rendered titles.
    assert "original_language" in joined
    assert "verified_quote" in joined
