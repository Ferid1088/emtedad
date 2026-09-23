from app.content_strategy.persian_quality import (
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


def test_verbatim_evidence_and_duplicate_paragraphs_are_rejected() -> None:
    evidence = "این یک گزارهٔ نسبتاً بلند برای آزمون نشت متن منبع است. " * 8
    text = f"{evidence}\n\n{evidence}"

    report = PersianDraftQualityValidator().validate(text, [evidence])

    codes = {item.code for item in report.findings}
    assert "RAW_EVIDENCE_DUMP" in codes
    assert "DUPLICATE_PARAGRAPHS" in codes
