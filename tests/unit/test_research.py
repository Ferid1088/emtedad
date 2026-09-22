"""Phase 7 Research Engine contract tests."""

from uuid import uuid4

from app.research.domain import (
    EvidenceSelectionRole,
    PackageStatus,
    ResearchQuestionKind,
    SpineStatus,
)
from app.research.schemas import ResearchQuestionInput
from app.research.validator import (
    PlanValidationInput,
    ResearchEngineValidator,
    SpineValidationInput,
)


def test_research_taxonomy_is_explicit_and_phase_eight_is_absent() -> None:
    assert {item.value for item in EvidenceSelectionRole} >= {
        "AYIN_GROUNDING",
        "EXTERNAL_EVIDENCE",
        "COUNTEREVIDENCE",
        "ALTERNATIVE_EXPLANATION",
        "TENSION",
        "UNRESOLVED",
    }
    assert PackageStatus.FROZEN.value == "FROZEN"
    assert SpineStatus.VALIDATED.value == "VALIDATED"
    assert not hasattr(__import__("app", fromlist=["lecture"]), "lecture")


def test_spine_validator_requires_pinned_ayin_context() -> None:
    report = ResearchEngineValidator().validate_spine(
        SpineValidationInput(
            human_question="How should this be understood?",
            concept_version_ids=[],
            passage_ids=[],
            canon_version_id=uuid4(),
            target_canon_version_ids=[],
            discourse_types=[],
            prohibited_conflations=[],
        )
    )
    assert {issue.code for issue in report} >= {
        "MISSING_AYIN_CONCEPT",
        "MISSING_AYIN_PASSAGE",
    }


def test_plan_validator_requires_reason_for_manasek_lane() -> None:
    report = ResearchEngineValidator().validate_plan(
        PlanValidationInput(
            question_count=1,
            question_kinds=[ResearchQuestionKind.MANASEK],
            has_counterevidence_question=False,
            manasek_relevant=True,
            manasek_reason=None,
        )
    )
    assert any(issue.code == "MANASEK_RELEVANCE_UNJUSTIFIED" for issue in report)


def test_question_contract_defaults_to_explicit_retrieval_text() -> None:
    question = ResearchQuestionInput(
        kind=ResearchQuestionKind.COUNTEREVIDENCE,
        question="What could challenge this description?",
    )
    assert question.retrieval_text is None
    assert question.requires_counterevidence is False
