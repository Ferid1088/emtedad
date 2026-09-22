"""Deterministic Research Engine boundary validation."""

from dataclasses import dataclass
from uuid import UUID

from app.research.domain import PackageIssueSeverity, ResearchQuestionKind
from app.research.schemas import PackageIssueRead


@dataclass(frozen=True, slots=True)
class SpineValidationInput:
    human_question: str
    concept_version_ids: list[UUID]
    passage_ids: list[UUID]
    canon_version_id: UUID
    target_canon_version_ids: list[UUID]
    discourse_types: list[str]
    prohibited_conflations: list[str]


@dataclass(frozen=True, slots=True)
class PlanValidationInput:
    question_count: int
    question_kinds: list[ResearchQuestionKind]
    has_counterevidence_question: bool
    manasek_relevant: bool
    manasek_reason: str | None


class ResearchEngineValidator:
    """Validate source grounding, research scope, and frozen package safety."""

    def validate_spine(self, item: SpineValidationInput) -> list[PackageIssueRead]:
        issues: list[PackageIssueRead] = []
        if not item.human_question.strip():
            issues.append(
                self._error("MISSING_HUMAN_QUESTION", "Human question is required")
            )
        if not item.concept_version_ids:
            issues.append(
                self._error(
                    "MISSING_AYIN_CONCEPT", "Ayin Spine needs at least one concept"
                )
            )
        if not item.passage_ids:
            issues.append(
                self._error("MISSING_AYIN_PASSAGE", "Ayin Spine must cite a passage")
            )
        if not item.prohibited_conflations:
            issues.append(
                self._warning(
                    "MISSING_PROHIBITED_CONFLATIONS",
                    "Spine has no explicit prohibited-conflation rules",
                )
            )
        if any(
            version_id != item.canon_version_id
            for version_id in item.target_canon_version_ids
        ):
            issues.append(
                self._error(
                    "MIXED_AYIN_VERSIONS",
                    "Every Ayin Spine target must use its pinned corpus version",
                )
            )
        allowed = {"CONCEPTUAL", "DESCRIPTIVE", "ETHICAL", "OPTIONAL_METAPHYSICAL"}
        if any(value not in allowed for value in item.discourse_types):
            issues.append(
                self._error("UNKNOWN_DISCOURSE_TYPE", "Unknown Ayin discourse type")
            )
        return issues

    def validate_plan(self, item: PlanValidationInput) -> list[PackageIssueRead]:
        issues: list[PackageIssueRead] = []
        if item.question_count == 0:
            issues.append(
                self._error(
                    "MISSING_RESEARCH_QUESTIONS", "ResearchPlan needs questions"
                )
            )
        if not item.has_counterevidence_question:
            issues.append(
                self._warning(
                    "COUNTEREVIDENCE_NOT_PLANNED",
                    "ResearchPlan has no explicit counterevidence question",
                )
            )
        if item.manasek_relevant and not (item.manasek_reason or "").strip():
            issues.append(
                self._error(
                    "MANASEK_RELEVANCE_UNJUSTIFIED",
                    "Manasek relevance requires an explicit reason",
                )
            )
        return issues

    @staticmethod
    def _error(code: str, message: str) -> PackageIssueRead:
        return PackageIssueRead(
            code=code,
            severity=PackageIssueSeverity.ERROR,
            message=message,
            resolved=False,
        )

    @staticmethod
    def _warning(code: str, message: str) -> PackageIssueRead:
        return PackageIssueRead(
            code=code,
            severity=PackageIssueSeverity.WARNING,
            message=message,
            resolved=False,
        )
