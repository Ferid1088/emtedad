"""Phase 6 taxonomy, epistemic, provider, cache, and boundary tests."""

from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import ForeignKeyConstraint, Table, UniqueConstraint

from app.cli import _parser
from app.core.ayin.domain import CorpusZone
from app.core.config import Settings
from app.dialogue.classifier import EvidenceRoleClassifier
from app.dialogue.domain import (
    NEGATIVE_RELATION_TYPES,
    ClaimTestability,
    EvidenceRole,
    ProposalMethod,
    RelationScope,
    RelationType,
    ReviewAction,
    ReviewPriority,
    ReviewStatus,
)
from app.dialogue.models import (
    DialogueAyinTarget,
    DialogueExternalTarget,
    DialogueProposal,
    DialogueRelation,
    DialogueReviewDecision,
)
from app.dialogue.schemas import (
    ClassifiedRelation,
    DialogueClassification,
    ProvenancePins,
    ValidationIssue,
)
from app.dialogue.service import (
    classifier_cache_key,
    merge_counterevidence_results,
    proposal_cache_key,
    review_status_for_action,
)
from app.dialogue.validator import DialogueEpistemicValidator, ValidationInput
from app.knowledge.llm.base import StructuredExtractionRequest
from app.retrieval.domain import RetrievalLane, RetrievalSourceKind
from app.retrieval.schemas import RetrievalProvenance, SearchResult


def _id(value: int) -> UUID:
    return UUID(int=value)


def _pins(*, complete: bool = True) -> ProvenancePins:
    return ProvenancePins(
        ayin_version_id=_id(1) if complete else None,
        ayin_passage_ids=[_id(2)] if complete else [],
        external_version_id=_id(3) if complete else None,
        external_segment_ids=[_id(4)] if complete else [],
        proposal_run_id=_id(5) if complete else None,
    )


def _search_result(chunk_id: int) -> SearchResult:
    return SearchResult(
        chunk_id=_id(chunk_id),
        chunk_content_hash="a" * 64,
        text="Actual corpus text",
        normalized_text="actual corpus text",
        language="en",
        section_title=None,
        matched_entities=[],
        lexical_rank=1,
        lexical_score=1.0,
        dense_rank=None,
        dense_score=None,
        entity_rank=None,
        entity_score=None,
        fusion_score=1.0,
        reranker_score=1.0,
        final_rank=1,
        expanded_context=[],
        provenance=RetrievalProvenance(
            corpus_zone=CorpusZone.EXTERNAL_PRIMARY,
            lane=RetrievalLane.EXTERNAL,
            source_kind=RetrievalSourceKind.EXTERNAL_SEGMENT,
            source_type="youtube",
            source_id=_id(100),
            source_version_id=_id(101),
            source_title="Fixture",
            source_url="https://example.test/source",
            record_ids=[_id(102)],
            source_status="active",
        ),
    )


def _validate(
    relation_type: RelationType,
    scope: RelationScope,
    testability: ClaimTestability,
    explanation: str = "The source has a limited, traceable relation.",
    *,
    pins: ProvenancePins | None = None,
    status: ReviewStatus = ReviewStatus.PROPOSED,
) -> list[ValidationIssue]:
    return DialogueEpistemicValidator().validate(
        ValidationInput(
            relation_type=relation_type,
            scope=scope,
            claim_testability=testability,
            explanation=explanation,
            provenance=pins or _pins(),
            review_status=status,
        )
    )


def test_relation_taxonomy_is_exact_and_has_no_generic_supports_ayin() -> None:
    assert {item.value for item in RelationType} == {
        "EMPIRICALLY_RELEVANT_TO",
        "SUPPORTS_EMPIRICAL_SUBCLAIM",
        "CONCEPTUAL_PARALLEL",
        "HISTORICAL_PARALLEL",
        "ILLUSTRATES",
        "COMPATIBLE_WITH",
        "TENSION_WITH",
        "CHALLENGES",
        "COUNTEREXAMPLE_TO",
        "ALTERNATIVE_EXPLANATION",
        "NOT_EQUIVALENT_TO",
        "UNRESOLVED_RELATION",
    }
    assert "SUPPORTS_AYIN" not in RelationType.__members__


def test_evidence_role_taxonomy_is_independent_and_complete() -> None:
    assert {item.value for item in EvidenceRole} == {
        "EMPIRICAL_EVIDENCE",
        "EMPIRICAL_COUNTEREVIDENCE",
        "PHILOSOPHICAL_ARGUMENT",
        "CONCEPTUAL_ANALOGY",
        "HISTORICAL_CONTEXT",
        "EXAMPLE",
        "ANECDOTE",
        "COMMENTARY",
        "REFERENCE_ONLY",
        "ALTERNATIVE_EXPLANATION",
        "UNKNOWN",
    }


def test_classifier_schema_is_strict_for_codex_structured_output() -> None:
    schema = DialogueClassification.model_json_schema()
    assert schema["additionalProperties"] is False
    relation_schema = schema["$defs"]["ClassifiedRelation"]
    assert relation_schema["additionalProperties"] is False
    assert set(relation_schema["required"]) == set(relation_schema["properties"])


@pytest.mark.parametrize("scope", list(RelationScope))
def test_all_scopes_are_explicitly_supported(scope: RelationScope) -> None:
    assert not _validate(
        RelationType.COMPATIBLE_WITH, scope, ClaimTestability.DESCRIPTIVE_NONTESTABLE
    )


def test_impossible_relation_scope_is_rejected() -> None:
    issues = _validate(
        RelationType.CONCEPTUAL_PARALLEL,
        RelationScope.EMPIRICAL,
        ClaimTestability.CONCEPTUAL,
    )
    assert {item.code for item in issues} == {"IMPOSSIBLE_RELATION_SCOPE"}


def test_only_descriptive_testable_can_receive_empirical_support() -> None:
    assert not _validate(
        RelationType.SUPPORTS_EMPIRICAL_SUBCLAIM,
        RelationScope.EMPIRICAL,
        ClaimTestability.DESCRIPTIVE_TESTABLE,
    )
    for testability in (
        ClaimTestability.CONCEPTUAL,
        ClaimTestability.DESCRIPTIVE_NONTESTABLE,
        ClaimTestability.ETHICAL,
        ClaimTestability.OPTIONAL_METAPHYSICAL,
        ClaimTestability.OPEN_QUESTION,
    ):
        issues = _validate(
            RelationType.SUPPORTS_EMPIRICAL_SUBCLAIM,
            RelationScope.EMPIRICAL,
            testability,
        )
        assert "EMPIRICAL_SUPPORT_REQUIRES_TESTABLE_DESCRIPTION" in {
            item.code for item in issues
        }


def test_known_philosophical_traps_are_machine_detected() -> None:
    proof = _validate(
        RelationType.EMPIRICALLY_RELEVANT_TO,
        RelationScope.EMPIRICAL,
        ClaimTestability.DESCRIPTIVE_TESTABLE,
        "Neuroscience proves Ayin and settles the matter.",
    )
    identity = _validate(
        RelationType.CONCEPTUAL_PARALLEL,
        RelationScope.CONCEPTUAL,
        ClaimTestability.CONCEPTUAL,
        "The psychological theory is identical to Pattern.",
    )
    metaphysical = _validate(
        RelationType.EMPIRICALLY_RELEVANT_TO,
        RelationScope.EMPIRICAL,
        ClaimTestability.OPTIONAL_METAPHYSICAL,
    )
    open_question = _validate(
        RelationType.COMPATIBLE_WITH,
        RelationScope.CONCEPTUAL,
        ClaimTestability.OPEN_QUESTION,
        "The paper provides the final answer and resolves this question.",
    )
    assert {item.code for item in proof} == {"SCIENCE_PROVES_AYIN_FRAMING"}
    assert {item.code for item in identity} == {"CONCEPTUAL_PARALLEL_AS_IDENTITY"}
    assert {item.code for item in metaphysical} == {
        "METAPHYSICAL_EMPIRICAL_RELEVANCE_REVIEW"
    }
    assert metaphysical[0].severity == "WARNING"
    assert {item.code for item in open_question} == {
        "OPEN_QUESTION_TREATED_AS_RESOLVED"
    }


def test_missing_version_passage_segment_and_run_are_all_reported() -> None:
    issues = _validate(
        RelationType.UNRESOLVED_RELATION,
        RelationScope.CONCEPTUAL,
        ClaimTestability.CONCEPTUAL,
        pins=_pins(complete=False),
    )
    assert {item.code for item in issues} == {
        "MISSING_AYIN_VERSION",
        "MISSING_AYIN_PASSAGE",
        "MISSING_EXTERNAL_VERSION",
        "MISSING_EXTERNAL_SEGMENT",
        "MISSING_PROPOSAL_RUN",
    }


def test_manual_relation_does_not_require_a_machine_proposal_run() -> None:
    pins = _pins()
    pins.proposal_run_id = None
    issues = DialogueEpistemicValidator().validate(
        ValidationInput(
            relation_type=RelationType.ILLUSTRATES,
            scope=RelationScope.ILLUSTRATIVE,
            claim_testability=ClaimTestability.CONCEPTUAL,
            explanation="A source-bounded example.",
            provenance=pins,
            proposal_method=ProposalMethod.MANUAL,
        )
    )
    assert "MISSING_PROPOSAL_RUN" not in {item.code for item in issues}


def test_approved_relation_cannot_hide_critical_errors() -> None:
    issues = _validate(
        RelationType.SUPPORTS_EMPIRICAL_SUBCLAIM,
        RelationScope.EMPIRICAL,
        ClaimTestability.CONCEPTUAL,
        status=ReviewStatus.APPROVED,
    )
    assert "APPROVED_WITH_CRITICAL_ERRORS" in {item.code for item in issues}


def test_negative_relations_are_first_class() -> None:
    assert {
        RelationType.TENSION_WITH,
        RelationType.CHALLENGES,
        RelationType.COUNTEREXAMPLE_TO,
        RelationType.ALTERNATIVE_EXPLANATION,
        RelationType.NOT_EQUIVALENT_TO,
        RelationType.UNRESOLVED_RELATION,
    } == NEGATIVE_RELATION_TYPES


def test_typed_registries_have_real_fks_and_no_generic_owner_columns() -> None:
    ayin_table = cast(Table, DialogueAyinTarget.__table__)
    external_table = cast(Table, DialogueExternalTarget.__table__)
    ayin_columns = ayin_table.columns
    external_columns = external_table.columns
    assert "owner_type" not in ayin_columns
    assert "owner_id" not in ayin_columns
    assert "target_type" not in external_columns
    assert "target_id" not in external_columns
    ayin_fks = {
        item
        for item in ayin_table.constraints
        if isinstance(item, ForeignKeyConstraint)
    }
    external_fks = {
        item
        for item in external_table.constraints
        if isinstance(item, ForeignKeyConstraint)
    }
    assert len(ayin_fks) == 5
    assert len(external_fks) == 6


def test_machine_proposal_and_review_are_separate_records() -> None:
    assert "relation_type" in DialogueProposal.__table__.columns
    assert "relation_type" in DialogueRelation.__table__.columns
    relation_table = cast(Table, DialogueRelation.__table__)
    assert any(
        isinstance(item, UniqueConstraint)
        and [column.name for column in item.columns] == ["proposal_id"]
        for item in relation_table.constraints
    )
    default = DialogueRelation.__table__.columns["review_status"].default
    assert default is not None and default.arg is ReviewStatus.PROPOSED
    assert review_status_for_action(ReviewAction.APPROVE) is ReviewStatus.APPROVED
    assert review_status_for_action(ReviewAction.REJECT) is ReviewStatus.REJECTED


def test_human_override_preserves_original_machine_proposal_and_decision() -> None:
    proposal = DialogueProposal(
        id=_id(20),
        ayin_target_id=_id(21),
        external_target_id=_id(22),
        relation_type=RelationType.CONCEPTUAL_PARALLEL,
        scope=RelationScope.CONCEPTUAL,
        explanation="Original machine explanation.",
        relation_confidence=0.7,
        evidence_role=EvidenceRole.CONCEPTUAL_ANALOGY,
        claim_testability=ClaimTestability.CONCEPTUAL,
        proposal_method=ProposalMethod.MODEL_CLASSIFIER,
        review_priority=ReviewPriority.NORMAL,
        created_by="fixture",
        validation_issues=[],
    )
    relation = DialogueRelation(
        id=_id(23),
        proposal_id=proposal.id,
        relation_type=proposal.relation_type,
        scope=proposal.scope,
        explanation=proposal.explanation,
        review_status=ReviewStatus.PROPOSED,
        review_priority=ReviewPriority.NORMAL,
    )
    decision = DialogueReviewDecision(
        relation_id=relation.id,
        action=ReviewAction.REJECT,
        reviewer="human-reviewer",
        previous_relation_type=relation.relation_type,
        new_relation_type=RelationType.NOT_EQUIVALENT_TO,
        previous_scope=relation.scope,
        new_scope=RelationScope.CONCEPTUAL,
        previous_explanation=relation.explanation,
        new_explanation="Reviewed explanation.",
        notes="False equivalence risk.",
    )
    relation.relation_type = decision.new_relation_type
    relation.explanation = decision.new_explanation
    relation.review_status = review_status_for_action(decision.action)

    assert proposal.relation_type is RelationType.CONCEPTUAL_PARALLEL
    assert proposal.explanation == "Original machine explanation."
    assert decision.previous_relation_type is RelationType.CONCEPTUAL_PARALLEL
    assert relation.relation_type is RelationType.NOT_EQUIVALENT_TO
    assert relation.review_status is ReviewStatus.REJECTED


def test_classifier_cache_changes_with_model_or_prompt_but_not_same_config() -> None:
    values = {
        "ayin_input_hash": "a" * 64,
        "candidate_input_hash": "b" * 64,
        "provider": "fixture",
        "model": "model-1",
        "configuration_hash": "c" * 64,
    }
    first = proposal_cache_key(**values)
    assert proposal_cache_key(**values) == first
    assert proposal_cache_key(**(values | {"model": "model-2"})) != first
    assert proposal_cache_key(**values, prompt_version="v-next") != first


def test_pair_cache_is_independent_of_surrounding_retrieval_run() -> None:
    first = classifier_cache_key(
        ayin_version_id=_id(1),
        ayin_input_hash="a" * 64,
        external_version_id=_id(2),
        external_content_hash="b" * 64,
        provider="fixture",
        model="model-1",
    )
    assert (
        classifier_cache_key(
            ayin_version_id=_id(1),
            ayin_input_hash="a" * 64,
            external_version_id=_id(2),
            external_content_hash="b" * 64,
            provider="fixture",
            model="model-1",
        )
        == first
    )
    assert (
        classifier_cache_key(
            ayin_version_id=_id(1),
            ayin_input_hash="a" * 64,
            external_version_id=_id(2),
            external_content_hash="b" * 64,
            provider="fixture",
            model="model-2",
        )
        != first
    )
    assert (
        classifier_cache_key(
            ayin_version_id=_id(1),
            ayin_input_hash="a" * 64,
            external_version_id=_id(2),
            external_content_hash="b" * 64,
            provider="fixture",
            model="model-1",
            prompt_version="v-next",
        )
        != first
    )


def test_counterevidence_deduplicates_real_results_and_allows_empty() -> None:
    first = _search_result(200)
    second = _search_result(201)
    assert merge_counterevidence_results([], limit=5) == []
    assert merge_counterevidence_results([[first], [first, second]], limit=5) == [
        first,
        second,
    ]


class _ClassifierProvider:
    name = "fixture"

    async def extract(
        self, request: StructuredExtractionRequest
    ) -> DialogueClassification:
        assert request.output_model is DialogueClassification
        return DialogueClassification(
            evidence_role=EvidenceRole.EMPIRICAL_EVIDENCE,
            claim_testability=ClaimTestability.DESCRIPTIVE_TESTABLE,
            relations=[
                ClassifiedRelation(
                    relation_type=RelationType.CONCEPTUAL_PARALLEL,
                    scope=RelationScope.CONCEPTUAL,
                    explanation="A bounded structural analogy.",
                    relation_confidence=0.8,
                    review_priority=ReviewPriority.NORMAL,
                    review_reasons=[],
                ),
                ClassifiedRelation(
                    relation_type=RelationType.NOT_EQUIVALENT_TO,
                    scope=RelationScope.CONCEPTUAL,
                    explanation="The source theory does not define the Ayin concept.",
                    relation_confidence=0.9,
                    review_priority=ReviewPriority.NORMAL,
                    review_reasons=[],
                ),
            ],
        )


@pytest.mark.asyncio
async def test_classifier_preserves_deterministic_ayin_testability() -> None:
    output = await EvidenceRoleClassifier(
        _ClassifierProvider(), model="fixture"
    ).classify(
        ayin_context="Pattern is not identity.",
        external_context="A psychological identity theory.",
        fixed_testability=ClaimTestability.CONCEPTUAL,
    )
    assert output.claim_testability is ClaimTestability.CONCEPTUAL
    assert [item.relation_type for item in output.relations] == [
        RelationType.CONCEPTUAL_PARALLEL,
        RelationType.NOT_EQUIVALENT_TO,
    ]


def test_dialogue_cli_supports_targeted_proposal_filter_and_counterevidence() -> None:
    proposal = _parser().parse_args(
        ["dialogue", "propose", "--ayin-concept", "pattern"]
    )
    filtered = _parser().parse_args(
        ["dialogue", "list", "--relation-type", "tension_with"]
    )
    counter = _parser().parse_args(
        ["dialogue", "counterevidence", "--ayin-open-question", str(_id(9))]
    )
    assert proposal.ayin_concept == "pattern"
    assert filtered.relation_type == "TENSION_WITH"
    assert counter.ayin_open_question == str(_id(9))


def test_dialogue_routes_exist_with_phase8_lecture_routes(
    test_settings: Settings,
) -> None:
    from app.main import create_app

    app = create_app(test_settings)
    paths = set(app.openapi()["paths"])
    assert {
        "/dialogue/relations",
        "/dialogue/relations/{relation_id}",
        "/dialogue/ayin/{concept_id}/relations",
        "/dialogue/review-queue",
        "/dialogue/propose",
        "/dialogue/relations/{relation_id}/review",
    } <= paths
    assert "/lectures" in paths
