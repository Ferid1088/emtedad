"""Pure Ayin policy, normalization, and seed tests."""

from app.core.ayin.domain import (
    CorpusZone,
    DiscourseType,
    DistinctionRelation,
    EditorialStatus,
    LanguageCode,
    OpenQuestionStatus,
    ReviewReason,
    TermFormType,
    status_allowed_in_zone,
)
from app.core.ayin.normalization import normalize_persian_text
from app.core.ayin.seed import load_seed_manifest


def test_working_and_canon_statuses_are_separate() -> None:
    assert status_allowed_in_zone(CorpusZone.AYIN_WORKING, EditorialStatus.DRAFT)
    assert not status_allowed_in_zone(CorpusZone.AYIN_WORKING, EditorialStatus.APPROVED)
    assert status_allowed_in_zone(CorpusZone.AYIN_CANON, EditorialStatus.APPROVED)
    assert not status_allowed_in_zone(CorpusZone.AYIN_CANON, EditorialStatus.DRAFT)


def test_four_discourse_types_are_explicit() -> None:
    assert {item.value for item in DiscourseType} == {
        "CONCEPTUAL",
        "DESCRIPTIVE",
        "ETHICAL",
        "OPTIONAL_METAPHYSICAL",
    }


def test_distinction_relations_are_bounded() -> None:
    assert DistinctionRelation("IS_NOT") is DistinctionRelation.IS_NOT
    assert "EQUIVALENT_TO" not in {item.value for item in DistinctionRelation}


def test_open_question_lifecycle_is_explicit() -> None:
    assert {item.value for item in OpenQuestionStatus} == {
        "open",
        "under_review",
        "partially_addressed",
        "retired",
    }


def test_terminology_supports_languages_and_forbidden_equivalents() -> None:
    assert {item.value for item in LanguageCode} == {"fa", "en", "ar"}
    assert TermFormType.FORBIDDEN_EQUIVALENT.value == "forbidden_equivalent"


def test_persian_normalization_does_not_modify_input() -> None:
    raw = "\u202bكِتاب\u200cها\t  يک\u202c"
    assert normalize_persian_text(raw) == "کِتاب ها یک"
    assert raw == "\u202bكِتاب\u200cها\t  يک\u202c"


def test_seed_is_working_only_and_omits_unsupported_horizontal_emtedad() -> None:
    seed = load_seed_manifest()
    keys = {item.stable_key for item in seed.concepts}
    assert len(keys) == 20
    assert "horizontal_emtedad" not in keys
    assert len(seed.distinctions) == 11
    assert len(seed.principles) == 12
    assert len(seed.open_questions) == 5
    assert all(
        form.status in {EditorialStatus.DRAFT, EditorialStatus.REVIEW}
        for term in seed.terms
        for form in term.forms
    )


def test_bon_forbidden_equivalents_are_reviewable_data() -> None:
    seed = load_seed_manifest()
    bon = next(item for item in seed.terms if item.stable_key == "bon")
    forbidden = {
        form.form
        for form in bon.forms
        if form.form_type is TermFormType.FORBIDDEN_EQUIVALENT
    }
    assert forbidden == {"soul", "personality", "self"}


def test_extraction_review_reasons_are_specific() -> None:
    assert {item.value for item in ReviewReason} == {
        "suspicious_extraction",
        "heading_uncertainty",
        "broken_paragraph",
        "character_corruption",
        "page_layout_ambiguity",
        "possible_missing_content",
        "seed_provenance",
    }
