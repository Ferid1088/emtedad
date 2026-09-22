"""Deterministic epistemic and structural validation for dialogue relations."""

import re
from dataclasses import dataclass

from app.dialogue.domain import (
    ALLOWED_SCOPES,
    ClaimTestability,
    ProposalMethod,
    RelationScope,
    RelationType,
    ReviewReason,
    ReviewStatus,
)
from app.dialogue.schemas import ProvenancePins, ValidationIssue

_PROOF = re.compile(
    r"\b(science|research|neuroscience|psychology)\s+(proves?|verified)\b|"
    r"\b(empirically|scientifically)\s+proven\b|"
    r"علم.{0,12}(ثابت|اثبات)|اثبات علمی",
    re.IGNORECASE,
)
_IDENTITY = re.compile(
    r"\b(identical to|the same as|is equivalent to|equals?)\b|"
    r"همان است|یکسان است|معادل است",
    re.IGNORECASE,
)
_RESOLVED = re.compile(
    r"\b(resolves?|settles?|final answer)\b|پاسخ قطعی|حل شد|حل می‌کند",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ValidationInput:
    relation_type: RelationType
    scope: RelationScope
    claim_testability: ClaimTestability
    explanation: str
    provenance: ProvenancePins
    review_status: ReviewStatus = ReviewStatus.PROPOSED
    proposal_method: ProposalMethod = ProposalMethod.MODEL_CLASSIFIER


class DialogueEpistemicValidator:
    """Reject proof, identity, discourse mismatch, and missing provenance."""

    def validate(self, item: ValidationInput) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if item.scope not in ALLOWED_SCOPES[item.relation_type]:
            issues.append(
                self._error(
                    "IMPOSSIBLE_RELATION_SCOPE",
                    f"{item.relation_type.value} cannot use {item.scope.value} scope",
                    ReviewReason.DISCOURSE_MISMATCH,
                )
            )
        if (
            item.relation_type is RelationType.SUPPORTS_EMPIRICAL_SUBCLAIM
            and item.claim_testability is not ClaimTestability.DESCRIPTIVE_TESTABLE
        ):
            reason = (
                ReviewReason.METAPHYSICAL_OVERREACH
                if item.claim_testability is ClaimTestability.OPTIONAL_METAPHYSICAL
                else ReviewReason.UNSUPPORTED_SCIENTIFIC_FRAMING
            )
            issues.append(
                self._error(
                    "EMPIRICAL_SUPPORT_REQUIRES_TESTABLE_DESCRIPTION",
                    "Direct empirical support requires a DESCRIPTIVE_TESTABLE "
                    "Ayin target",
                    reason,
                )
            )
        if _PROOF.search(item.explanation):
            issues.append(
                self._error(
                    "SCIENCE_PROVES_AYIN_FRAMING",
                    "Explanation uses prohibited scientific-proof framing",
                    ReviewReason.UNSUPPORTED_SCIENTIFIC_FRAMING,
                )
            )
        if (
            item.claim_testability is ClaimTestability.OPTIONAL_METAPHYSICAL
            and item.scope is RelationScope.EMPIRICAL
            and item.relation_type is RelationType.EMPIRICALLY_RELEVANT_TO
        ):
            issues.append(
                self._warning(
                    "METAPHYSICAL_EMPIRICAL_RELEVANCE_REVIEW",
                    "Empirical relevance to an optional metaphysical interpretation "
                    "requires review and never constitutes verification",
                    ReviewReason.METAPHYSICAL_OVERREACH,
                )
            )
        if (
            item.claim_testability is ClaimTestability.ETHICAL
            and item.relation_type is RelationType.SUPPORTS_EMPIRICAL_SUBCLAIM
        ):
            issues.append(
                self._error(
                    "ETHICAL_PRINCIPLE_AS_EMPIRICAL_RESULT",
                    "An ethical orientation cannot be experimentally proven",
                    ReviewReason.DISCOURSE_MISMATCH,
                )
            )
        if (
            item.relation_type is not RelationType.NOT_EQUIVALENT_TO
            and _IDENTITY.search(item.explanation)
        ):
            issues.append(
                self._error(
                    "CONCEPTUAL_PARALLEL_AS_IDENTITY",
                    "Conceptual parallel explanation collapses similarity into "
                    "identity",
                    ReviewReason.POTENTIAL_FALSE_EQUIVALENCE,
                )
            )
        if (
            item.claim_testability is ClaimTestability.OPEN_QUESTION
            and _RESOLVED.search(item.explanation)
        ):
            issues.append(
                self._error(
                    "OPEN_QUESTION_TREATED_AS_RESOLVED",
                    "External material cannot resolve an Ayin open question",
                    ReviewReason.DISCOURSE_MISMATCH,
                )
            )
        pins = item.provenance
        if pins.ayin_version_id is None:
            issues.append(self._error("MISSING_AYIN_VERSION", "Missing Ayin version"))
        if not pins.ayin_passage_ids:
            issues.append(self._error("MISSING_AYIN_PASSAGE", "Missing Ayin passage"))
        if pins.external_version_id is None:
            issues.append(
                self._error("MISSING_EXTERNAL_VERSION", "Missing external version")
            )
        if not pins.external_segment_ids:
            issues.append(
                self._error("MISSING_EXTERNAL_SEGMENT", "Missing external segment")
            )
        if (
            item.proposal_method is ProposalMethod.MODEL_CLASSIFIER
            and pins.proposal_run_id is None
        ):
            issues.append(
                self._error("MISSING_PROPOSAL_RUN", "Machine proposal lacks its run")
            )
        if item.review_status is ReviewStatus.APPROVED and any(
            issue.severity == "ERROR" for issue in issues
        ):
            issues.append(
                self._error(
                    "APPROVED_WITH_CRITICAL_ERRORS",
                    "Approved relation still has critical epistemic errors",
                )
            )
        return issues

    @staticmethod
    def _error(
        code: str,
        message: str,
        reason: ReviewReason | None = None,
    ) -> ValidationIssue:
        return ValidationIssue(
            code=code,
            message=message,
            severity="ERROR",
            review_reason=reason,
        )

    @staticmethod
    def _warning(
        code: str,
        message: str,
        reason: ReviewReason | None = None,
    ) -> ValidationIssue:
        return ValidationIssue(
            code=code,
            message=message,
            severity="WARNING",
            review_reason=reason,
        )
