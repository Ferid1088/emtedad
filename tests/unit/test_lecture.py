"""Phase 8 Semantic Lecture Master contract tests."""

from uuid import uuid4

from app.lecture.domain import ClaimEpistemicStatus, ClaimOrigin
from app.lecture.validator import (
    AyinFidelityValidator,
    CitationCoverageValidator,
    DialogueStatusValidator,
    RitualBoundaryValidator,
)


def test_ayin_fidelity_rejects_known_conflations() -> None:
    findings = AyinFidelityValidator().validate(
        [{"claim_intent": "Pattern = Identity", "stable_key": "trap"}]
    )
    assert any(item.code == "PATTERN_IDENTITY_CONFLATION" for item in findings)


def test_proposed_dialogue_relation_cannot_leak_as_approved() -> None:
    findings = DialogueStatusValidator().validate(
        [{"relation_id": str(uuid4()), "review_status": "APPROVED"}]
    )
    assert findings[0].code == "DIALOGUE_STATUS_LEAKAGE"


def test_external_claim_requires_evidence_binding() -> None:
    findings = CitationCoverageValidator().validate(
        [
            {
                "id": str(uuid4()),
                "stable_key": "external_1",
                "required": True,
                "claim_origin": ClaimOrigin.EXTERNAL,
            }
        ],
        [],
    )
    assert findings[0].code == "UNSUPPORTED_CLAIM"


def test_ritual_context_is_optional_and_non_evidentiary() -> None:
    findings = RitualBoundaryValidator().validate(
        [{"ritual_version_id": str(uuid4()), "optional": False}],
        [
            {
                "stable_key": "ritual_1",
                "claim_origin": ClaimOrigin.RITUAL_CONTEXT,
                "epistemic_status": ClaimEpistemicStatus.EXTERNAL_EMPIRICAL_CLAIM,
            }
        ],
    )
    assert {item.code for item in findings} == {
        "RITUAL_NOT_OPTIONAL",
        "RITUAL_AS_OTHER_EVIDENCE",
    }
