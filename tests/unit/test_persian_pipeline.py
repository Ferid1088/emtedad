from uuid import UUID

from app.content_strategy.lesson_canon import LessonCanonRepository
from app.content_strategy.persian_pipeline import (
    LessonConsistencyReviewer,
    PersianNativeReviewer,
    PublishedMemoryItem,
    ScriptDiversityValidator,
    explicit_ayin_reference_ratio,
    final_semantic_findings,
)


def _published(text: str, *, title: str = "متن پیشین") -> PublishedMemoryItem:
    return PublishedMemoryItem(
        project_id=UUID("00000000-0000-0000-0000-000000000001"),
        title=title,
        text=text,
        lesson_id="1.1",
        concept_keys=(),
        examples=(),
        open_promises=(),
    )


def test_published_archive_is_available_only_to_post_draft_diversity_review() -> None:
    text = " ".join(f"واژه{index}" for index in range(90))

    findings = ScriptDiversityValidator().validate(text, [_published(text)])

    assert {item.code for item in findings} >= {
        "REPEATED_OPENING_PATTERN",
        "REPEATED_ENDING_PATTERN",
        "EXCESSIVE_PHRASE_OVERLAP",
    }
    assert all(item.category == "EXCESSIVE_REPETITION" for item in findings)


def test_protected_concept_redefinition_is_a_direct_blocking_contradiction() -> None:
    lesson = LessonCanonRepository().package("1.1")

    findings = LessonConsistencyReviewer().validate(
        "بُن یعنی شخصیت و چیزی بیشتر از آن نیست.",
        lesson,
        external_evidence_count=1,
        published=[],
    )

    conflict = next(item for item in findings if item.code == "BON_REDEFINED")
    assert conflict.category == "DIRECT_CONTRADICTION"
    assert conflict.blocking is True


def test_unsupported_research_claim_requires_review() -> None:
    lesson = LessonCanonRepository().package("1.1")

    findings = final_semantic_findings(
        "پژوهش‌ها نشان داده‌اند که این نتیجه قطعی است.",
        lesson,
        external_evidence_count=0,
    )

    assert any(
        item.code == "UNSUPPORTED_EXTERNAL_CLAIM" and item.blocking
        for item in findings
    )


def test_native_persian_gate_flags_translated_connector_rhythm() -> None:
    text = (
        "از سوی دیگر، این پرسش باقی است. در نتیجه، باید مکث کرد. "
        "به طور کلی، پاسخ آسان نیست. در این راستا، مسئله ادامه دارد."
    )

    findings = PersianNativeReviewer().review(text)

    assert any(item.code == "TRANSLATED_CONNECTOR_PATTERN" for item in findings)


def test_explicit_ayin_reference_is_measured_as_editorial_guidance() -> None:
    text = (
        "آدمی در یک موقعیت دشوار مکث می‌کند. "
        "از نگاه آیین امتداد این مکث می‌تواند مجال دیدن باشد. "
        "پرسش هنوز باز می‌ماند و پاسخ از پیش آماده‌ای ندارد."
    )

    ratio = explicit_ayin_reference_ratio(text)

    assert 0 < ratio < 1
