"""Phase 8 Semantic Lecture Master contract tests."""

from uuid import uuid4

from app.lecture.domain import ClaimEpistemicStatus, ClaimOrigin, PublicationLanguage
from app.lecture.schemas import SemanticLectureMasterExport
from app.lecture.validator import (
    AyinFidelityValidator,
    CitationCoverageValidator,
    DialogueStatusValidator,
    RitualBoundaryValidator,
)
from app.localization.domain import PronunciationCriticality
from app.localization.pronunciation import (
    ArabicDiacritizer,
    PersianPronunciationAnnotator,
)
from app.localization.validators import (
    PronunciationValidator,
    SemanticFidelityValidator,
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


def test_semantic_master_handoff_declares_four_languages_without_scripts() -> None:
    assert [item.value for item in PublicationLanguage] == ["fa", "de", "en", "ar"]
    assert "supported_languages" in SemanticLectureMasterExport.model_fields
    assert "evidence" in SemanticLectureMasterExport.model_fields
    assert "terminology_references" in SemanticLectureMasterExport.model_fields
    assert "persian_script" not in SemanticLectureMasterExport.model_fields
    assert "german_script" not in SemanticLectureMasterExport.model_fields


def test_semantic_localization_requires_claim_alignment() -> None:
    findings = SemanticFidelityValidator().validate(
        [{"id": "claim-1", "epistemic_status": "AYIN_DEFINITION", "certainty": "HIGH"}],
        [],
    )
    assert findings[0].code == "CLAIM_OMISSION"


def test_critical_pronunciation_requires_approved_lexicon_entry() -> None:
    findings = PronunciationValidator().validate(
        PublicationLanguage.DE,
        [{"tts_text": "Bon"}],
        [
            {
                "written_form": "Bon",
                "criticality": PronunciationCriticality.CRITICAL.value,
                "status": "PROPOSED",
            }
        ],
    )
    assert findings[0].code == "CRITICAL_PRONUNCIATION_MISSING"


def test_pronunciation_preparation_preserves_display_text() -> None:
    fa = PersianPronunciationAnnotator().annotate(
        "بُن",
        [{"written_form": "بُن", "preferred_pronunciation": "بُنِ"}],
    )
    ar = ArabicDiacritizer().annotate(
        "امتداد",
        [{"written_form": "امتداد", "preferred_pronunciation": "اِمْتِداد"}],
        fully_vocalized=True,
    )
    assert fa.display_text == "بُن"
    assert fa.tts_text == "بُنِ"
    assert ar.display_text == "امتداد"
    assert ar.tts_text == "اِمْتِداد"
