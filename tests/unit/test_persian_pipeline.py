from uuid import UUID

from app.content_engine.writing.diversity import ScriptDiversityValidator
from app.content_engine.writing.memory import PublishedMemoryItem
from app.content_engine.writing.native import PersianNativeReviewer
from app.content_engine.writing.text import explicit_ayin_reference_ratio
from app.content_strategy.lesson_canon import LessonContentPackage
from app.content_strategy.persian_pipeline import (
    LessonConsistencyReviewer,
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


def _lesson_package() -> LessonContentPackage:
    """Hand-built snapshot standing in for the retired canon repository."""

    return LessonContentPackage(
        lesson_canon_hash="legacy-hash",
        lesson_id="1.1",
        lesson_number=1,
        chapter=1,
        chapter_title_fa="آغاز",
        order_in_chapter=1,
        level=1,
        canonical_lesson_title="بُن",
        is_core_concept=True,
        central_question="بُن چیست؟",
        canonical_lesson_explanation="توضیح کانونیک درس.",
        core_concepts=["بُن"],
        required_distinctions=[],
        conceptual_boundaries=[],
        prerequisites=[],
        lesson_relations=[],
        canonical_relations_section_fa="",
        what_this_lesson_develops=[],
        what_should_remain_open=[],
        ayin_provenance=None,
        provenance_complete=True,
        review_items=[],
        core_concept_registry=[],
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
    findings = LessonConsistencyReviewer().validate(
        "بُن یعنی شخصیت و چیزی بیشتر از آن نیست.",
        _lesson_package(),
        external_evidence_count=1,
        published=[],
    )

    conflict = next(item for item in findings if item.code == "BON_REDEFINED")
    assert conflict.category == "DIRECT_CONTRADICTION"
    assert conflict.blocking is True


def test_unsupported_research_claim_requires_review() -> None:
    findings = final_semantic_findings(
        "پژوهش‌ها نشان داده‌اند که این نتیجه قطعی است.",
        _lesson_package(),
        external_evidence_count=0,
    )

    assert any(
        item.code == "UNSUPPORTED_EXTERNAL_CLAIM" and item.blocking for item in findings
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
