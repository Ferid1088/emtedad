import json
from typing import cast

from app.content_strategy.lesson_canon import LessonCanonRepository
from app.content_strategy.persian_service import PersianEditorialService
from app.lecture.domain import PublicationLanguage
from app.lecture.schemas import LectureValidationRead, SemanticLectureMasterExport
from app.research.domain import ResearchQuestionKind
from app.research.models import AyinSpine
from app.research.service import ResearchEngineService


def test_approved_lesson_canon_builds_direct_content_packages() -> None:
    repository = LessonCanonRepository()

    summaries = repository.summaries()
    package = repository.package("1.1")

    assert len(summaries) == 100
    assert package.lesson_id == "1.1"
    assert package.canonical_lesson_title == "آیین امتداد چیست و چه نیست"
    assert package.canonical_lesson_explanation
    assert package.lesson_relations
    assert package.canonical_relations_section_fa
    assert len(package.lesson_canon_hash) == 64
    assert package.ayin_provenance is None
    assert package.provenance_complete is False
    assert package.review_items == ["MISSING_LESSON_AYIN_PROVENANCE"]


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

    _, context, evidence = service._generation_context(export, package, 15)
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


def test_default_lesson_research_questions_use_only_external_space() -> None:
    questions = ResearchEngineService._default_questions(
        "What bears on this lesson?", cast(AyinSpine, object())
    )

    assert {question.kind for question in questions} == {
        ResearchQuestionKind.EMPIRICAL,
        ResearchQuestionKind.COUNTEREVIDENCE,
    }


def test_lesson_diversity_profiles_do_not_collapse_to_one_template() -> None:
    lesson_ids = [item.lesson_id for item in LessonCanonRepository().summaries()]
    profiles = {
        tuple(PersianEditorialService._diversity_plan(lesson_id).values())
        for lesson_id in lesson_ids
    }

    assert len(profiles) >= 90
