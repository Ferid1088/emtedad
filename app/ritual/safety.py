"""Deterministic ritual and localization safety validation."""

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ayin.domain import EditorialStatus
from app.ritual.models import (
    LocalizationSafetyRule,
    MusicSpecification,
    RitualCue,
    RitualLocalization,
    RitualVersion,
    RitualVersionSafetyRule,
    SafetyRule,
    SafetyRuleVersion,
)
from app.ritual.schemas import ValidationIssue, ValidationReport
from app.ritual.seed import REQUIRED_SAFETY_KEYS

VALIDATOR_VERSION = "ritual-safety-v1"


@dataclass(frozen=True)
class ForbiddenPattern:
    code: str
    expression: re.Pattern[str]
    message: str


FORBIDDEN_PATTERNS: tuple[ForbiddenPattern, ...] = (
    ForbiddenPattern(
        "forced_eye_closure",
        re.compile(
            r"(everyone|you)\s+must\s+close\s+(their|your)\s+eyes|همه\s+باید.*چشم", re.I
        ),
        "Eye closure cannot be mandatory.",
    ),
    ForbiddenPattern(
        "forced_screaming",
        re.compile(r"(need|must|have)\s+to\s+scream|باید.*فریاد", re.I),
        "Screaming or catharsis cannot be required.",
    ),
    ForbiddenPattern(
        "forced_outcome",
        re.compile(r"repeat\s+until\s+something\s+happens|تکرار.*تا.*اتفاق", re.I),
        "No specific ritual outcome may be required.",
    ),
    ForbiddenPattern(
        "metaphysical_inference",
        re.compile(r"(this|it)\s+proves\s+(your\s+)?bon|اثبات.*ب[ُ]?ن", re.I),
        "Ritual experience cannot prove Bon or metaphysical truth.",
    ),
    ForbiddenPattern(
        "interpret_resistance",
        re.compile(r"your\s+resistance\s+means|مقاومت\s+تو\s+یعنی", re.I),
        "A guide cannot interpret resistance as diagnosis or truth.",
    ),
    ForbiddenPattern(
        "breath_pressure",
        re.compile(r"hold\s+your\s+breath\s+until|نفس.*حبس.*تا", re.I),
        "Breath retention or escalation pressure is prohibited.",
    ),
    ForbiddenPattern(
        "exit_denied",
        re.compile(r"do\s+not\s+leave\s+the\s+circle|نباید.*خارج", re.I),
        "The right to leave cannot be removed.",
    ),
    ForbiddenPattern(
        "psychological_diagnosis",
        re.compile(
            r"(this|your response)\s+(shows|means)\s+you\s+(have|are)|تشخیص\s+روانی",
            re.I,
        ),
        "Ritual response cannot be used for diagnosis.",
    ),
    ForbiddenPattern(
        "frequency_claim",
        re.compile(
            r"(sacred|healing|hidden)\s+frequenc|فرکانس\s+(مقدس|شفابخش|پنهان)", re.I
        ),
        "Sacred, healing, or hidden-frequency claims are prohibited.",
    ),
)

_NEGATIONS = (
    "no ",
    "not ",
    "never ",
    "avoid ",
    "optional",
    "اختیاری",
    "ممنوع",
    "نیست",
    "ندارد",
)


class RitualSafetyValidator:
    """Validate policy bindings and deterministic unsafe language patterns."""

    def __init__(self, session: AsyncSession | None = None) -> None:
        self._session = session

    def validate_text(self, text: str) -> ValidationReport:
        issues: list[ValidationIssue] = []
        for rule in FORBIDDEN_PATTERNS:
            for match in rule.expression.finditer(text):
                prefix = text[max(0, match.start() - 35) : match.start()].casefold()
                if any(prefix.rstrip().endswith(term.rstrip()) for term in _NEGATIONS):
                    continue
                issues.append(ValidationIssue(code=rule.code, message=rule.message))
        return ValidationReport(
            valid=not issues,
            publishable=False,
            issue_count=len(issues),
            issues=issues,
        )

    async def validate_version(self, ritual_version_id: UUID) -> ValidationReport:
        if self._session is None:
            raise RuntimeError("database session is required for version validation")
        ritual = await self._session.get(RitualVersion, ritual_version_id)
        if ritual is None:
            raise LookupError("ritual version not found")
        cues = list(
            await self._session.scalars(
                select(RitualCue).where(RitualCue.ritual_version_id == ritual.id)
            )
        )
        localizations = list(
            await self._session.scalars(
                select(RitualLocalization).where(
                    RitualLocalization.ritual_version_id == ritual.id
                )
            )
        )
        music = await self._session.get(MusicSpecification, ritual.id)
        text_parts = [ritual.experiential_instructions]
        text_parts.extend(cue.text for cue in cues)
        for localization in localizations:
            text_parts.extend(
                [
                    localization.narration_text,
                    localization.instructions,
                    localization.safety_language,
                ]
            )
        if music is not None:
            text_parts.append(music.original_prompt)
        language_report = self.validate_text("\n".join(text_parts))
        issues = list(language_report.issues)

        rows = await self._session.execute(
            select(
                SafetyRule.stable_key,
                SafetyRuleVersion.status,
            )
            .join(SafetyRuleVersion, SafetyRuleVersion.rule_id == SafetyRule.id)
            .join(
                RitualVersionSafetyRule,
                RitualVersionSafetyRule.safety_rule_version_id == SafetyRuleVersion.id,
            )
            .where(RitualVersionSafetyRule.ritual_version_id == ritual.id)
        )
        bindings: dict[str, EditorialStatus] = {
            stable_key: status for stable_key, status in rows
        }
        for missing in sorted(REQUIRED_SAFETY_KEYS - bindings.keys()):
            issues.append(
                ValidationIssue(
                    code="missing_safety_capability",
                    message=f"Required safety capability is not bound: {missing}",
                    record_id=ritual.id,
                )
            )

        for localization in localizations:
            localization_ids = set(
                await self._session.scalars(
                    select(LocalizationSafetyRule.safety_rule_version_id).where(
                        LocalizationSafetyRule.localization_id == localization.id
                    )
                )
            )
            base_ids = set(
                await self._session.scalars(
                    select(RitualVersionSafetyRule.safety_rule_version_id).where(
                        RitualVersionSafetyRule.ritual_version_id == ritual.id
                    )
                )
            )
            if localization_ids != base_ids:
                issues.append(
                    ValidationIssue(
                        code="localization_weakened_safety",
                        message=(
                            "Localization safety bindings must exactly preserve the "
                            "ritual safety policy."
                        ),
                        record_id=localization.id,
                    )
                )
        approved_rules = all(
            status is EditorialStatus.APPROVED for status in bindings.values()
        )
        valid = not issues
        return ValidationReport(
            valid=valid,
            publishable=(
                valid
                and ritual.status is EditorialStatus.APPROVED
                and approved_rules
                and bool(bindings)
            ),
            issue_count=len(issues),
            issues=issues,
        )
