"""Regression tests for real localization persistence boundaries."""

from app.core.terminology.models import Term
from app.db.base import Base
from app.lecture.domain import PublicationLanguage
from app.localization.service import LocalizationService


def test_pronunciation_foreign_key_target_is_registered() -> None:
    assert Term.__table__ in Base.metadata.tables.values()


def test_lexicon_marks_core_ayin_terms_critical() -> None:
    entries = LocalizationService._lexicon(
        [
            {"source_form": "bon"},
            {"source_form": "emtedad"},
            {"source_form": "pattern"},
        ],
        PublicationLanguage.DE,
    )
    critical = {
        item["written_form"] for item in entries if item["criticality"] == "CRITICAL"
    }
    assert critical == {"bon", "emtedad"}


def test_duration_adjustment_instruction_preserves_claim_set() -> None:
    from app.localization.prompts import duration_adjustment_instruction

    for direction in ("condense", "expand"):
        text = duration_adjustment_instruction(PublicationLanguage.DE, direction, 1500)
        assert "1500" in text
        assert "claim ID" in text
        assert "never drop" in text or "never drop," in text
        assert "evidence" in text
    condense = duration_adjustment_instruction(PublicationLanguage.FA, "condense", 800)
    assert "condense" in condense
    expand = duration_adjustment_instruction(PublicationLanguage.EN, "expand", 2500)
    assert "elaborate" in expand
