"""Structural Ayin validation without future lecture-fidelity behavior."""

import asyncio
import hashlib
from collections import Counter
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ayin.domain import CorpusZone, EditorialStatus
from app.core.ayin.models import (
    AyinConceptVersion,
    CanonPassage,
    CanonVersion,
    CanonVersionSourceAsset,
    ExtractionRun,
)
from app.core.ayin.provenance import passage_set_hash
from app.core.ayin.schemas import ValidationIssue, ValidationReport
from app.ops.assets.models import ObjectAsset
from app.storage.base import ObjectStore


class AyinStructuralValidator:
    """Detect provenance, authority, ordering, and checksum violations."""

    def __init__(self, session: AsyncSession, object_store: ObjectStore) -> None:
        self._session = session
        self._object_store = object_store

    async def validate(self) -> ValidationReport:
        issues: list[ValidationIssue] = []
        versions = list(await self._session.scalars(select(CanonVersion)))
        for version in versions:
            if (
                version.corpus_zone is CorpusZone.AYIN_WORKING
                and version.status is EditorialStatus.APPROVED
            ):
                issues.append(
                    ValidationIssue(
                        code="approved_working_version",
                        message="A Working version cannot be approved.",
                        record_id=version.id,
                    )
                )
            runs = list(
                await self._session.scalars(
                    select(ExtractionRun).where(
                        ExtractionRun.canon_version_id == version.id
                    )
                )
            )
            if not runs:
                issues.append(
                    ValidationIssue(
                        code="missing_extraction_run",
                        message="Source version has no reproducible extraction run.",
                        record_id=version.id,
                    )
                )
            for run in runs:
                await self._validate_passages(run, issues)

        approved_duplicates = await self._session.execute(
            select(
                AyinConceptVersion.concept_id,
                func.count(AyinConceptVersion.id),
            )
            .where(AyinConceptVersion.approval_status == EditorialStatus.APPROVED)
            .group_by(AyinConceptVersion.concept_id)
            .having(func.count(AyinConceptVersion.id) > 1)
        )
        for concept_id, _ in approved_duplicates:
            issues.append(
                ValidationIssue(
                    code="multiple_approved_concept_versions",
                    message="Concept has multiple approved definitions.",
                    record_id=concept_id,
                )
            )

        await self._validate_assets(issues)
        return ValidationReport(
            valid=not issues, issue_count=len(issues), issues=issues
        )

    async def _validate_passages(
        self, run: ExtractionRun, issues: list[ValidationIssue]
    ) -> None:
        passages = list(
            await self._session.scalars(
                select(CanonPassage)
                .where(CanonPassage.extraction_run_id == run.id)
                .order_by(CanonPassage.sequence)
            )
        )
        sequences = [item.sequence for item in passages]
        if sequences != list(range(1, len(sequences) + 1)):
            issues.append(
                ValidationIssue(
                    code="passage_order",
                    message="Passage sequence is not contiguous.",
                    record_id=run.id,
                )
            )
        page_order = [item.page_number for item in passages]
        if page_order != sorted(page_order):
            issues.append(
                ValidationIssue(
                    code="page_order",
                    message="Passage page order is not monotonic.",
                    record_id=run.id,
                )
            )
        if len(passages) != run.passage_count:
            issues.append(
                ValidationIssue(
                    code="passage_count",
                    message="Extraction run passage count does not match its output.",
                    record_id=run.id,
                )
            )
        if passages and max(item.page_number for item in passages) != run.page_count:
            issues.append(
                ValidationIssue(
                    code="page_count",
                    message=(
                        "Extraction run page count does not match passage locations."
                    ),
                    record_id=run.id,
                )
            )
        if passage_set_hash(passages) != run.output_hash:
            issues.append(
                ValidationIssue(
                    code="extraction_output_hash",
                    message="Extraction run output hash does not match its passages.",
                    record_id=run.id,
                )
            )
        for passage in passages:
            digest = hashlib.sha256(passage.raw_text.encode()).hexdigest()
            if digest != passage.content_hash:
                issues.append(
                    ValidationIssue(
                        code="passage_hash",
                        message="Passage raw text does not match its content hash.",
                        record_id=passage.id,
                    )
                )

    async def _validate_assets(self, issues: list[ValidationIssue]) -> None:
        rows = await self._session.execute(
            select(CanonVersion, ObjectAsset)
            .join(
                CanonVersionSourceAsset,
                CanonVersionSourceAsset.canon_version_id == CanonVersion.id,
            )
            .join(
                ObjectAsset, ObjectAsset.id == CanonVersionSourceAsset.source_asset_id
            )
        )
        seen: Counter[UUID] = Counter()
        for version, asset in rows:
            seen[version.id] += 1
            if version.source_file_hash != asset.sha256:
                issues.append(
                    ValidationIssue(
                        code="source_hash_mismatch",
                        message="Version and source asset hashes disagree.",
                        record_id=version.id,
                    )
                )
                continue
            try:
                await asyncio.to_thread(
                    self._object_store.read_bytes,
                    asset.storage_key,
                    expected_sha256=asset.sha256,
                )
            except Exception as exc:  # exact storage error is reported, not hidden
                issues.append(
                    ValidationIssue(
                        code="source_asset_corrupt",
                        message=(
                            f"Source asset verification failed: {type(exc).__name__}"
                        ),
                        record_id=asset.id,
                    )
                )
        for version in await self._session.scalars(select(CanonVersion)):
            if seen[version.id] != 1:
                issues.append(
                    ValidationIssue(
                        code="source_asset_cardinality",
                        message="Version must have exactly one typed source asset.",
                        record_id=version.id,
                    )
                )
