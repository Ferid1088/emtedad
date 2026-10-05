from app.content_engine.writing.quality import (
    PersianDraftQualityValidator,
    clean_source_text,
)


def test_research_scaffolding_is_rejected() -> None:
    report = PersianDraftQualityValidator().validate(
        "The selected Ayin Working source states the following material: متن.",
        [],
    )

    assert not report.valid
    assert any(item.code == "INTERNAL_SCAFFOLDING_LEAKAGE" for item in report.findings)


def test_source_cleanup_removes_pdf_controls_without_rewriting_words() -> None:
    assert clean_source_text("ی\u202an\u202cک\u00ad") == "یک"
    assert clean_source_text("می\u200cروم") == "می\u200cروم"


def test_replacement_characters_are_rejected() -> None:
    """Provider-corrupted Persian (U+FFFD) is a deterministic blocker — the
    semantic critics demonstrably miss it (Phase 4 live run)."""

    report = PersianDraftQualityValidator().validate("حر\ufffd‌ها برچسب", [])

    assert not report.valid
    assert any(item.code == "ENCODING_CORRUPTION" for item in report.findings)


def test_verbatim_evidence_and_duplicate_paragraphs_are_rejected() -> None:
    evidence = "این یک گزارهٔ نسبتاً بلند برای آزمون نشت متن منبع است. " * 8
    text = f"{evidence}\n\n{evidence}"

    report = PersianDraftQualityValidator().validate(text, [evidence])

    codes = {item.code for item in report.findings}
    assert "RAW_EVIDENCE_DUMP" in codes
    assert "DUPLICATE_PARAGRAPHS" in codes


def test_repeated_sentences_across_paragraphs_are_rejected() -> None:
    """§10: filler spread across paragraphs — the same conclusion restated
    in different sections — fails even when no paragraph is identical."""
    sentence = (
        "در نهایت این داستان به ما می‌آموزد که آسیب‌پذیری نقطه‌ی شروع "
        "ارتباط است و هر بار همین را تکرار می‌کنیم تا بلند شود."
    )
    filler = "و این مسیر را با توجه به جزئیات تازه ادامه می‌دهیم."
    text = "\n\n".join(
        f"{sentence} {filler} شماره {i} با مثال متفاوت." for i in range(6)
    )

    report = PersianDraftQualityValidator().validate(text, [])

    assert any(item.code == "REPEATED_SENTENCES" for item in report.findings)


def test_varied_prose_passes_sentence_repetition() -> None:
    sentences = [
        f"این جملهٔ شماره {i} محتوای متفاوتی را با ساختار کاملاً جدا "
        f"بیان می‌کند و هیچ تکراری در آن نیست."
        for i in range(10)
    ]
    report = PersianDraftQualityValidator().validate("\n\n".join(sentences), [])

    assert not any(item.code == "REPEATED_SENTENCES" for item in report.findings)


class TestDurationFindings:
    """§17: the 25–30-minute band produces correct directional findings."""

    def _text(self, words: int) -> str:
        return " ".join(["واژه"] * words)

    def test_in_target_produces_no_finding(self) -> None:
        from app.content_engine.writing.quality import duration_findings

        # 27.5 min at 110 wpm → 3025 words, band 2722–3327.
        findings, count = duration_findings(self._text(3025), 27.5, wpm=110)
        assert findings == []
        assert count == 3025

    def test_too_short(self) -> None:
        from app.content_engine.writing.quality import duration_findings

        findings, _count = duration_findings(self._text(1980), 27.5, wpm=110)
        assert findings[0].code == "DURATION_TOO_SHORT"
        assert findings[0].severity == "WARNING"

    def test_too_long(self) -> None:
        from app.content_engine.writing.quality import duration_findings

        findings, _count = duration_findings(self._text(4400), 27.5, wpm=110)
        assert findings[0].code == "DURATION_TOO_LONG"

    def test_wpm_is_language_specific(self) -> None:
        from app.content_engine.writing.quality import duration_findings

        # Same word count is in-target for German (120 wpm) but long for
        # Persian (110 wpm): duration status is per-language.
        text = self._text(3400)
        assert duration_findings(text, 27.5, wpm=120)[0] == []
        assert duration_findings(text, 27.5, wpm=110)[0][0].code == (
            "DURATION_TOO_LONG"
        )
