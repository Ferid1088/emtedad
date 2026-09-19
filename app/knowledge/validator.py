"""Structural validator for external provenance and authority boundaries."""

import hashlib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ayin.domain import CorpusZone
from app.knowledge.domain import VerificationStatus
from app.knowledge.models import ExternalClaim, SourceSegment, SourceVersion
from app.knowledge.schemas import ValidationIssue, ValidationReport


class KnowledgeStructuralValidator:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def validate(self) -> ValidationReport:
        issues: list[ValidationIssue] = []
        bad_zone = await self._session.scalar(
            select(SourceVersion.id).where(
                SourceVersion.corpus_zone != CorpusZone.EXTERNAL_PRIMARY
            )
        )
        if bad_zone is not None:
            issues.append(
                ValidationIssue(code="zone", message="Invalid external zone.")
            )
        for segment in await self._session.scalars(select(SourceSegment)):
            if (
                hashlib.sha256(segment.raw_text.encode()).hexdigest()
                != segment.content_hash
            ):
                issues.append(
                    ValidationIssue(
                        code="segment_hash",
                        message="Raw transcript hash does not match.",
                        record_id=segment.id,
                    )
                )
        promoted = await self._session.scalar(
            select(func.count(ExternalClaim.id)).where(
                ExternalClaim.verification_status != VerificationStatus.ATTRIBUTED_ONLY
            )
        )
        if promoted:
            issues.append(
                ValidationIssue(
                    code="claim_authority",
                    message="Machine-extracted claim was promoted beyond attribution.",
                )
            )
        return ValidationReport(
            valid=not issues, issue_count=len(issues), issues=issues
        )
