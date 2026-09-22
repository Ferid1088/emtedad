"""Deterministic Semantic Master integrity validators."""

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
        return findings
