"""Deterministic semantic and pronunciation quality gates."""

import unicodedata
from dataclasses import dataclass

from app.core.terminology.canonical import CANONICAL_AYIN_TERMS
from app.lecture.domain import PublicationLanguage
from app.localization.domain import PronunciationCriticality
from app.localization.pronunciation import pronunciation_preserves_text


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
                display_text = statement.get("display_text")
                if (
                    isinstance(display_text, str)
                    and isinstance(voice_text, str)
                    and not pronunciation_preserves_text(display_text, voice_text)
                ):
                    findings.append(
                        LocalizationFinding(
                            "VOICE_TEXT_SEMANTIC_DRIFT",
                            "voice_text changes lexical content instead of "
                            "pronunciation marks",
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

    def validate_voice_preparation(
        self,
        language: PublicationLanguage,
        display_text: str,
        voice_text: str,
    ) -> list[LocalizationFinding]:
        """Require useful marks when a high-risk term is actually present."""

        if language not in {PublicationLanguage.FA, PublicationLanguage.AR}:
            return []
        risky_terms = {
            "امتداد",
            "بُن",
            "بن",
            "جان",
            "مجال",
            "میان",
            "تهیگاه",
            "مناسک",
            "مناسك",
        }
        present = [term for term in risky_terms if term in display_text]
        if not present:
            return []
        if display_text == voice_text and not any(
            mark in voice_text for mark in "ًٌٍَُِّْ"
        ):
            return [
                LocalizationFinding(
                    "PRONUNCIATION_PREPARATION_MISSING",
                    (
                        "Risk terms need selective pronunciation marks: "
                        f"{', '.join(sorted(present))}"
                    ),
                )
            ]
        if language is PublicationLanguage.FA:
            for phrase, marked_prefix in (
                ("آیین امتداد", "آیینِ"),
                ("راه زندگی", "راهِ"),
                ("کتاب من", "کتابِ"),
            ):
                if phrase in display_text and marked_prefix not in voice_text:
                    return [
                        LocalizationFinding(
                            "EZAFE_MISSING",
                            (
                                f"The Persian compound '{phrase}' requires "
                                "an explicit Ezafe mark."
                            ),
                        )
                    ]
            if not any(mark in voice_text for mark in "َُِّ"):
                return [
                    LocalizationFinding(
                        "PERSIAN_DIACRITICS_MISSING",
                        (
                            "Persian risk terms require selective short-vowel "
                            "or Shadda support."
                        ),
                    )
                ]
        if language is PublicationLanguage.AR and not any(
            mark in voice_text for mark in "ًٌٍَُِّْ"
        ):
            return [
                LocalizationFinding(
                    "ARABIC_TASHKIL_MISSING",
                    "Arabic risk terms require selective Tashkil support.",
                )
            ]
        return []


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


class ProtectedTerminologyValidator:
    """Ensure protected Ayin terms are retained in native realizations."""

    def validate(
        self,
        language: PublicationLanguage,
        source_persian: str,
        localized_text: str,
    ) -> list[LocalizationFinding]:
        findings: list[LocalizationFinding] = []
        for term in CANONICAL_AYIN_TERMS:
            source_without_marks = "".join(
                char for char in source_persian if char not in "ًٌٍَُِّْ"
            )
            term_without_marks = "".join(
                char for char in term.persian_form if char not in "ًٌٍَُِّْ"
            )
            if (
                term.persian_form not in source_persian
                and term_without_marks not in source_without_marks
            ):
                continue
            expected = term.language_rendering.get(language.value)
            if expected is None:
                findings.append(
                    LocalizationFinding(
                        "CANONICAL_TRANSLITERATION_REVIEW",
                        (
                            f"No reviewed {language.value} rendering exists for "
                            f"{term.canonical_id}."
                        ),
                    )
                )
            elif expected not in localized_text:
                findings.append(
                    LocalizationFinding(
                        "PROTECTED_AYIN_TERM_MISSING",
                        f"{term.canonical_id} must remain as {expected}.",
                    )
                )
        return findings
