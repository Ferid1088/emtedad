"""Deterministic Semantic Master integrity validators."""

import re
from dataclasses import dataclass
from typing import Any

from app.lecture.domain import ClaimEpistemicStatus, ClaimOrigin


@dataclass(frozen=True, slots=True)
class LectureFinding:
    dimension: str
    code: str
    severity: str
    message: str
    blocking: bool = True


class AyinFidelityValidator:
    """Reject common Ayin conflations before a master can become READY."""

    def validate(self, claims: list[dict[str, Any]]) -> list[LectureFinding]:
        findings: list[LectureFinding] = []
        traps = {
            "pattern = identity": "PATTERN_IDENTITY_CONFLATION",
            "bon = personality": "BON_PERSONALITY_CONFLATION",
            "bon = soul": "BON_SOUL_CONFLATION",
            "jan = intelligence": "JAN_INTELLIGENCE_CONFLATION",
            "jan = consciousness": "JAN_CONSCIOUSNESS_CONFLATION",
            "acceptance = surrender": "ACCEPTANCE_SURRENDER_CONFLATION",
            "majal = freedom outside causality": "MAJAL_CAUSALITY_CONFLATION",
            "emtedad = repetition": "EMTEDAD_REPETITION_CONFLATION",
            "scientific proof": "SCIENTIFIC_PROOF_FRAMING",
        }
        for claim in claims:
            text = str(claim.get("claim_intent", "")).lower()
            for phrase, code in traps.items():
                if phrase in text:
                    findings.append(
                        LectureFinding(
                            "AYIN_FIDELITY", code, "ERROR", claim["claim_intent"]
                        )
                    )
        return findings


class LectureEpistemicValidator:
    """Prevent relation, attribution, and evidence-category collapse."""

    def validate(
        self,
        claims: list[dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> list[LectureFinding]:
        findings: list[LectureFinding] = []
        for relation in relations:
            status = relation.get("review_status")
            intent = str(relation.get("claim_intent", "")).lower()
            if status == "PROPOSED" and any(
                word in intent for word in ("approved", "confirmed", "established")
            ):
                findings.append(
                    LectureFinding(
                        "DIALOGUE_STATUS",
                        "PROPOSED_RELATION_OVERSTATED",
                        "ERROR",
                        str(relation.get("relation_id")),
                    )
                )
        for claim in claims:
            status = claim.get("epistemic_status")
            origin = claim.get("claim_origin")
            if (
                origin == ClaimOrigin.EXTERNAL
                and status == ClaimEpistemicStatus.AYIN_DEFINITION
            ):
                findings.append(
                    LectureFinding(
                        "EPISTEMIC_INTEGRITY",
                        "EXTERNAL_AS_AYIN",
                        "ERROR",
                        str(claim.get("stable_key")),
                    )
                )
            if status == ClaimEpistemicStatus.OPTIONAL_METAPHYSICAL_INTERPRETATION:
                constraints = claim.get("formulation_constraints", [])
                if not any("optional" in str(item).lower() for item in constraints):
                    findings.append(
                        LectureFinding(
                            "EPISTEMIC_INTEGRITY",
                            "METAPHYSICAL_OPTIONALITY_MISSING",
                            "ERROR",
                            str(claim.get("stable_key")),
                        )
                    )
        return findings


class CitationCoverageValidator:
    """Require package evidence for every substantive intended claim."""

    def validate(
        self,
        claims: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
    ) -> list[LectureFinding]:
        bound = {item.get("claim_id") for item in evidence}
        findings: list[LectureFinding] = []
        for claim in claims:
            if (
                claim.get("required", True)
                and claim.get("claim_origin") != ClaimOrigin.EXAMPLE
                and claim.get("id") not in bound
            ):
                findings.append(
                    LectureFinding(
                        "CITATION_COVERAGE",
                        "UNSUPPORTED_CLAIM",
                        "ERROR",
                        str(claim.get("stable_key")),
                    )
                )
        return findings


class DialogueStatusValidator:
    def validate(self, relations: list[dict[str, Any]]) -> list[LectureFinding]:
        return [
            LectureFinding(
                "DIALOGUE_STATUS",
                "DIALOGUE_STATUS_LEAKAGE",
                "ERROR",
                str(item.get("relation_id")),
            )
            for item in relations
            if item.get("review_status") not in {"PROPOSED", "IN_REVIEW"}
        ]


class RitualBoundaryValidator:
    def validate(
        self, ritual_links: list[dict[str, Any]], claims: list[dict[str, Any]]
    ) -> list[LectureFinding]:
        findings: list[LectureFinding] = []
        for link in ritual_links:
            if not link.get("optional", False):
                findings.append(
                    LectureFinding(
                        "RITUAL_BOUNDARY",
                        "RITUAL_NOT_OPTIONAL",
                        "ERROR",
                        str(link.get("ritual_version_id")),
                    )
                )
        for claim in claims:
            if (
                claim.get("claim_origin") == ClaimOrigin.RITUAL_CONTEXT
                and claim.get("epistemic_status") != ClaimEpistemicStatus.RITUAL_CONTEXT
            ):
                findings.append(
                    LectureFinding(
                        "RITUAL_BOUNDARY",
                        "RITUAL_AS_OTHER_EVIDENCE",
                        "ERROR",
                        str(claim.get("stable_key")),
                    )
                )
        return findings


class LectureValidator:
    """Compose all blocking semantic master validators."""

    def validate(self, payload: dict[str, Any]) -> list[LectureFinding]:
        claims = payload.get("claims", [])
        relations = payload.get("dialogue_relations", [])
        findings = AyinFidelityValidator().validate(claims)
        findings.extend(LectureEpistemicValidator().validate(claims, relations))
        findings.extend(
            CitationCoverageValidator().validate(claims, payload.get("evidence", []))
        )
        findings.extend(DialogueStatusValidator().validate(relations))
        findings.extend(
            RitualBoundaryValidator().validate(payload.get("ritual_links", []), claims)
        )
        findings.extend(SemanticMasterStandaloneValidator().validate(payload))
        findings.extend(LocalizationReadinessValidator().validate(payload))
        return findings


_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.IGNORECASE)


class SemanticMasterStandaloneValidator:
    """Ensure an export can be understood without database lookups."""

    def validate(self, payload: dict[str, Any]) -> list[LectureFinding]:
        findings: list[LectureFinding] = []
        claims = payload.get("claims", [])
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            proposition = str(claim.get("semantic_proposition") or "").strip()
            intent = str(claim.get("claim_intent") or "").strip()
            if not proposition:
                findings.append(
                    LectureFinding(
                        "PACKAGE_TRACEABILITY",
                        "MISSING_SEMANTIC_PROPOSITION",
                        "ERROR",
                        str(claim.get("stable_key")),
                    )
                )
            if (
                _UUID.search(proposition)
                and len(_UUID.sub("", proposition).strip()) < 20
            ):
                findings.append(
                    LectureFinding(
                        "PACKAGE_TRACEABILITY",
                        "UUID_ONLY_CLAIM",
                        "ERROR",
                        str(claim.get("stable_key")),
                    )
                )
            if _UUID.search(intent) and len(_UUID.sub("", intent).strip()) < 20:
                findings.append(
                    LectureFinding(
                        "PACKAGE_TRACEABILITY",
                        "UUID_ONLY_CLAIM",
                        "ERROR",
                        str(claim.get("stable_key")),
                    )
                )
            if (
                claim.get("required", True)
                and claim.get("claim_origin")
                in {ClaimOrigin.EXTERNAL, ClaimOrigin.AYIN}
                and not claim.get("source_evidence")
            ):
                findings.append(
                    LectureFinding(
                        "PACKAGE_TRACEABILITY",
                        "MISSING_EVIDENCE_TEXT",
                        "ERROR",
                        str(claim.get("stable_key")),
                    )
                )
            if (
                claim.get("epistemic_status")
                in {"OPEN_QUESTION", ClaimEpistemicStatus.OPEN_QUESTION}
                and "?" not in proposition
                and not proposition.lower().startswith(("what", "how", "why", "can "))
            ):
                findings.append(
                    LectureFinding(
                        "OPEN_QUESTION_PRESERVATION",
                        "MISSING_OPEN_QUESTION_TEXT",
                        "ERROR",
                        str(claim.get("stable_key")),
                    )
                )
            if claim.get(
                "epistemic_status"
            ) == ClaimEpistemicStatus.SYNTHESIS_INFERENCE and not claim.get(
                "plain_meaning"
            ):
                findings.append(
                    LectureFinding(
                        "PACKAGE_TRACEABILITY",
                        "MISSING_SYNTHESIS_PREMISE_MEANING",
                        "ERROR",
                        str(claim.get("stable_key")),
                    )
                )
        for section in payload.get("sections", []):
            if not isinstance(section, dict):
                continue
            for field in ("purpose", "transition_intent"):
                value = str(section.get(field) or "").strip()
                if field == "purpose" and not value:
                    findings.append(
                        LectureFinding(
                            "PACKAGE_TRACEABILITY",
                            "MISSING_SECTION_SEMANTICS",
                            "ERROR",
                            str(section.get("id")),
                        )
                    )
                if _UUID.search(value) and len(_UUID.sub("", value).strip()) < 20:
                    findings.append(
                        LectureFinding(
                            "PACKAGE_TRACEABILITY",
                            "UUID_ONLY_SECTION",
                            "ERROR",
                            str(section.get("id")),
                        )
                    )
        for relation in payload.get("dialogue_relations", []):
            if not str(relation.get("explanation") or "").strip():
                findings.append(
                    LectureFinding(
                        "DIALOGUE_STATUS",
                        "MISSING_RELATION_EXPLANATION",
                        "ERROR",
                        str(relation.get("relation_id")),
                    )
                )
        for term in payload.get("terminology_references", []):
            if not str(term.get("definition") or "").strip():
                findings.append(
                    LectureFinding(
                        "PACKAGE_TRACEABILITY",
                        "MISSING_TERM_DEFINITION",
                        "ERROR",
                        str(term.get("term_id")),
                    )
                )
        return findings


class LocalizationReadinessValidator:
    """Final deterministic gate for the language-neutral handoff."""

    def validate(self, payload: dict[str, Any]) -> list[LectureFinding]:
        findings = SemanticMasterStandaloneValidator().validate(payload)
        if not payload.get("claims"):
            findings.append(
                LectureFinding(
                    "PACKAGE_TRACEABILITY", "NO_SEMANTIC_CLAIMS", "ERROR", "master"
                )
            )
        return findings
