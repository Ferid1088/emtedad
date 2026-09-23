"""Deterministic semantic and pronunciation quality gates."""

import unicodedata
from dataclasses import dataclass

from app.lecture.domain import PublicationLanguage
from app.localization.domain import PronunciationCriticality


@dataclass(frozen=True)
class LocalizationFinding:
    code: str
    message: str
    blocking: bool = True


class SemanticFidelityValidator:
    """Validate claim-level alignment without comparing whole documents."""

    def validate(
        self,
        master_claims: list[dict[str, object]],
        localized_statements: list[dict[str, object]],
    ) -> list[LocalizationFinding]:
        findings: list[LocalizationFinding] = []
        master_ids = {str(item["id"]) for item in master_claims}
        localized_ids = {str(item["master_claim_id"]) for item in localized_statements}
        for claim_id in sorted(master_ids - localized_ids):
            findings.append(LocalizationFinding("CLAIM_OMISSION", claim_id))
        for claim_id in sorted(localized_ids - master_ids):
            findings.append(LocalizationFinding("CLAIM_ADDITION", claim_id))
        by_id = {str(item["id"]): item for item in master_claims}
        for statement in localized_statements:
            claim = by_id.get(str(statement.get("master_claim_id")))
            if claim is None:
                continue
            for field in ("epistemic_status", "certainty"):
                if field in statement and statement[field] != claim.get(field):
                    findings.append(
                        LocalizationFinding(
                            f"{field.upper()}_DRIFT",
                            f"claim {claim['id']} changes {field}",
                        )
                    )
        return findings


class PronunciationValidator:
    """Check pronunciation metadata; never claim acoustic perfection."""

    def validate(
        self,
        language: PublicationLanguage,
        statements: list[dict[str, object]],
        critical_terms: list[dict[str, object]],
    ) -> list[LocalizationFinding]:
        findings: list[LocalizationFinding] = []
        if language in {PublicationLanguage.FA, PublicationLanguage.AR}:
            for statement in statements:
                voice_text = statement.get("voice_text")
                if not isinstance(voice_text, str) or not voice_text.strip():
                    findings.append(
                        LocalizationFinding(
                            "MISSING_VOICE_TEXT",
                            "Arabic/Persian voice text is required",
                        )
                    )
                elif not all(unicodedata.category(char) != "Cs" for char in voice_text):
                    findings.append(
                        LocalizationFinding(
                            "INVALID_UNICODE", "surrogate in voice_text"
                        )
                    )
        for term in critical_terms:
            if term.get("criticality") == PronunciationCriticality.CRITICAL.value and (
                term.get("status") != "APPROVED"
                or not term.get("preferred_pronunciation")
            ):
                findings.append(
                    LocalizationFinding(
                        "CRITICAL_PRONUNCIATION_MISSING",
                        str(term.get("written_form", "")),
                    )
                )
        return findings


class LocalizationQualityGate:
    """Compose semantic, terminology, and pronunciation gates."""

    def validate(
        self,
        language: PublicationLanguage,
        master_claims: list[dict[str, object]],
        statements: list[dict[str, object]],
        critical_terms: list[dict[str, object]],
    ) -> list[LocalizationFinding]:
        return SemanticFidelityValidator().validate(
            master_claims, statements
        ) + PronunciationValidator().validate(language, statements, critical_terms)
