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
