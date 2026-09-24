import json
from types import SimpleNamespace
from typing import cast

from app.content_strategy.lesson_canon import LessonCanonRepository
from app.content_strategy.lesson_research import (
    LessonResearchService,
    _focus_tokens,
    _matches_human_question,
)
from app.content_strategy.models import EditorialProject, PersianDraft
from app.content_strategy.persian_service import PersianEditorialService
from app.lecture.domain import PublicationLanguage
from app.lecture.schemas import LectureValidationRead, SemanticLectureMasterExport
from app.research.domain import EvidenceSelectionRole, ResearchQuestionKind
from app.research.models import AyinSpine
from app.research.service import ResearchEngineService
from app.retrieval.schemas import SearchResult


def test_approved_lesson_canon_builds_direct_content_packages() -> None:
    repository = LessonCanonRepository()

    summaries = repository.summaries()
    package = repository.package("1.1")

    assert len(summaries) == 100
    assert package.lesson_id == "1.1"
    assert package.lesson_number == 1
    assert package.lesson_count == 100
    assert package.catalog_version == "100-lessons-v1"
    assert package.canonical_lesson_title == "آیین امتداد چیست و چه نیست"
    assert package.canonical_lesson_explanation
    assert package.lesson_relations
    assert package.canonical_relations_section_fa
    assert len(package.lesson_canon_hash) == 64
    assert package.ayin_provenance is None
    assert package.provenance_complete is False
    assert package.review_items == ["MISSING_LESSON_AYIN_PROVENANCE"]
    assert package == repository.package("1.1")


def test_persian_generation_context_excludes_ayin_and_review_only_material() -> None:
    package = LessonCanonRepository().package("1.1")
    export = SemanticLectureMasterExport(
        export_version="1",
        supported_languages=[PublicationLanguage.FA],
        master={"central_human_question": "پرسش انسانی", "status": "READY"},
        sections=[],
        claims=[
            {
                "claim_origin": "AYIN",
                "source_support_summary": "RAW_AYIN_BOOK_PASSAGE_MUST_NOT_APPEAR",
            },
            {
                "claim_origin": "EXTERNAL",
                "source_support_summary": "EXTERNAL_RESEARCH_MARKER",
                "epistemic_status": "EXTERNAL_EMPIRICAL_CLAIM",
            },
        ],
        evidence=[
            {
                "evidence_kind": "AYIN_PASSAGE",
                "text": "RAW_AYIN_EVIDENCE_MUST_NOT_APPEAR",
            },
            {
                "evidence_kind": "EXTERNAL_CHUNK",
                "text": "EXTERNAL_EVIDENCE_MARKER",
                "source_class": "EXTERNAL_PRIMARY",
            },
        ],
        citations=[],
        ritual_links=[],
        dialogue_relations=[],
        terminology_references=[],
        validation=LectureValidationRead(valid=True, findings=[]),
    )
    service = object.__new__(PersianEditorialService)

    outline, context, evidence = service._generation_context(export, package, 15)
    payload = json.loads(context)

    assert "RAW_AYIN_BOOK_PASSAGE_MUST_NOT_APPEAR" not in context
    assert "RAW_AYIN_EVIDENCE_MUST_NOT_APPEAR" not in context
    assert "EXTERNAL_RESEARCH_MARKER" in context
    assert "EXTERNAL_EVIDENCE_MARKER" in context
    assert (
        payload["canonical_lesson_content"]["canonical_lesson_explanation"]
        == package.canonical_lesson_explanation
    )
    assert "lesson_relations" not in payload["canonical_lesson_content"]
    assert "canonical_relations_section_fa" not in (payload["canonical_lesson_content"])
    assert evidence == ["EXTERNAL_EVIDENCE_MARKER"]
    assert outline.canonical_title == package.canonical_lesson_title
    assert outline.central_intellectual_movement


def test_historical_project_review_uses_the_draft_frozen_lesson_package() -> None:
    package = LessonCanonRepository().package("1.1")
    project = cast(
        EditorialProject,
        SimpleNamespace(strategy_topic_snapshot=None),
    )
    draft = cast(
        PersianDraft,
        SimpleNamespace(
            provenance={
                "lesson_content_package": package.model_dump(mode="json")
            }
        ),
    )

    restored = PersianEditorialService._lesson_package_for_review(project, draft)

    assert restored == package


def test_default_lesson_research_questions_use_only_external_space() -> None:
    questions = ResearchEngineService._default_questions(
        "What bears on this lesson?", cast(AyinSpine, object())
    )

    assert {question.kind for question in questions} == {
        ResearchQuestionKind.EMPIRICAL,
        ResearchQuestionKind.COUNTEREVIDENCE,
    }


def test_lesson_research_plan_is_external_only_and_includes_counterevidence() -> None:
    package = LessonCanonRepository().package("1.1")

    queries = LessonResearchService.build_queries(
        package, owner_focus="تاریخچه و نمونه‌های بین‌فرهنگی"
    )

    assert {query.kind for query in queries} == {
        ResearchQuestionKind.EMPIRICAL.value,
        ResearchQuestionKind.PHILOSOPHICAL.value,
        ResearchQuestionKind.EXTERNAL_CONCEPT.value,
        ResearchQuestionKind.COUNTEREVIDENCE.value,
        "OWNER_FOCUS",
    }
    assert all(query.text.strip() for query in queries)
    assert all(query.kind != "AYIN" for query in queries)
    assert any(
        query.selection_role is EvidenceSelectionRole.COUNTERARGUMENT
        for query in queries
    )
    assert all("AYIN" not in query.kind for query in queries)
    assert all("PUBLISHED_SCRIPT_ARCHIVE" not in query.text for query in queries)


def test_lesson_diversity_profiles_do_not_collapse_to_one_template() -> None:
    lesson_ids = [item.lesson_id for item in LessonCanonRepository().summaries()]
    profiles = {
        tuple(PersianEditorialService._diversity_plan(lesson_id).values())
        for lesson_id in lesson_ids
    }

    assert len(profiles) >= 90


def test_source_quality_rejects_material_unrelated_to_human_question() -> None:
    package = LessonCanonRepository().package("11.3")
    unrelated = cast(
        SearchResult,
        SimpleNamespace(
            normalized_text="گفت‌وگویی درباره وابستگی به مواد و درمان اعتیاد",
            matched_entities=[],
            provenance=SimpleNamespace(source_title="درسگفتار اعتیاد"),
        ),
    )
    relevant = cast(
        SearchResult,
        SimpleNamespace(
            normalized_text="پرسش از هوش مصنوعی و مرز تجربه سامانه‌ها",
            matched_entities=[],
            provenance=SimpleNamespace(source_title="هوش مصنوعی"),
        ),
    )

    focus = _focus_tokens(package)

    assert _matches_human_question(unrelated, package, focus) is False
    assert _matches_human_question(relevant, package, focus) is True
