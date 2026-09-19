"""Structural and provenance validation for the Manasek domain."""

import asyncio
import hashlib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ayin.domain import CorpusZone
from app.core.ayin.provenance import passage_set_hash
from app.ops.assets.models import ObjectAsset
from app.ritual.domain import GATE_ORDER, RitualMode, RitualPieceType
from app.ritual.models import (
    ArchitectureVersion,
    Gate,
    GateVersion,
    RitualExtractionRun,
    RitualPassage,
    RitualSequenceItem,
    RitualSourceVersion,
    RitualStage,
    RitualVersion,
    RitualVersionSourceAsset,
)
from app.ritual.safety import RitualSafetyValidator
from app.ritual.schemas import ValidationIssue, ValidationReport
from app.storage.base import ObjectStore


class RitualStructuralValidator:
    def __init__(self, session: AsyncSession, store: ObjectStore) -> None:
        self._session = session
        self._store = store

    async def validate(self) -> ValidationReport:
        issues: list[ValidationIssue] = []
        await self._validate_gates(issues)
        for run in await self._session.scalars(select(RitualExtractionRun)):
            await self._validate_run(run, issues)
        for architecture in await self._session.scalars(select(ArchitectureVersion)):
            await self._validate_architecture(architecture, issues)
        for ritual in await self._session.scalars(select(RitualVersion)):
            report = await RitualSafetyValidator(self._session).validate_version(
                ritual.id
            )
            issues.extend(report.issues)
        await self._validate_assets(issues)
        canon_count = await self._session.scalar(
            select(func.count(RitualSourceVersion.id)).where(
                RitualSourceVersion.corpus_zone == CorpusZone.MANASEK_CANON
            )
        )
        if canon_count:
            issues.append(
                ValidationIssue(
                    code="unauthorized_manasek_canon",
                    message="Phase 3 import must not create MANASEK_CANON.",
                )
            )
        return ValidationReport(
            valid=not issues,
            publishable=False,
            issue_count=len(issues),
            issues=issues,
        )

    async def _validate_gates(self, issues: list[ValidationIssue]) -> None:
        gates = list(
            await self._session.scalars(select(Gate).order_by(Gate.sequence_position))
        )
        if [gate.stable_key for gate in gates] != list(GATE_ORDER):
            issues.append(
                ValidationIssue(
                    code="five_gates", message="Gate identities/order are invalid."
                )
            )
        bad_gate = await self._session.scalar(
            select(GateVersion.id).where(
                (GateVersion.is_bon_component.is_(True))
                | (GateVersion.is_metaphysical_element.is_(True))
                | (GateVersion.is_personality_category.is_(True))
            )
        )
        if bad_gate is not None:
            issues.append(
                ValidationIssue(
                    code="gate_misclassification",
                    message="A gate was classified as Bon/metaphysics/personality.",
                    record_id=bad_gate,
                )
            )

    async def _validate_run(
        self, run: RitualExtractionRun, issues: list[ValidationIssue]
    ) -> None:
        passages = list(
            await self._session.scalars(
                select(RitualPassage)
                .where(RitualPassage.extraction_run_id == run.id)
                .order_by(RitualPassage.sequence)
            )
        )
        if [item.sequence for item in passages] != list(range(1, len(passages) + 1)):
            issues.append(
                ValidationIssue(
                    code="passage_order",
                    message="Ritual passage sequence is not contiguous.",
                    record_id=run.id,
                )
            )
        if len(passages) != run.passage_count or (
            passages and max(item.page_number for item in passages) != run.page_count
        ):
            issues.append(
                ValidationIssue(
                    code="extraction_counts",
                    message="Extraction run counts disagree with passages.",
                    record_id=run.id,
                )
            )
        if passage_set_hash(passages) != run.output_hash:
            issues.append(
                ValidationIssue(
                    code="extraction_output_hash",
                    message="Extraction output hash does not match stored passages.",
                    record_id=run.id,
                )
            )
        for passage in passages:
            if (
                hashlib.sha256(passage.raw_text.encode()).hexdigest()
                != passage.content_hash
            ):
                issues.append(
                    ValidationIssue(
                        code="passage_hash",
                        message="Stored ritual passage raw hash is invalid.",
                        record_id=passage.id,
                    )
                )

    async def _validate_architecture(
        self, architecture: ArchitectureVersion, issues: list[ValidationIssue]
    ) -> None:
        stages = list(
            await self._session.scalars(
                select(RitualStage)
                .where(RitualStage.architecture_version_id == architecture.id)
                .order_by(RitualStage.sequence_position)
            )
        )
        items = list(
            await self._session.scalars(
                select(RitualSequenceItem)
                .where(RitualSequenceItem.architecture_version_id == architecture.id)
                .order_by(RitualSequenceItem.sequence_position)
            )
        )
        if architecture.mode is RitualMode.INDIVIDUAL:
            if [stage.sequence_position for stage in stages] != list(range(1, 8)):
                issues.append(
                    ValidationIssue(
                        code="seven_stages",
                        message="Individual architecture must contain seven stages.",
                        record_id=architecture.id,
                    )
                )
            if len(items) != 42:
                issues.append(
                    ValidationIssue(
                        code="individual_piece_count",
                        message="Individual architecture must contain 42 pieces.",
                        record_id=architecture.id,
                    )
                )
            for stage in stages:
                stage_items = [item for item in items if item.stage_id == stage.id]
                kinds = [item.slot_kind for item in stage_items]
                if kinds != [RitualPieceType.GATE] * 5 + [RitualPieceType.RETURN]:
                    issues.append(
                        ValidationIssue(
                            code="stage_cycle",
                            message="Stage must contain five gates followed by Return.",
                            record_id=stage.id,
                        )
                    )
            bad_gate_slot = await self._session.scalar(
                select(RitualSequenceItem.id)
                .join(
                    RitualVersion,
                    RitualVersion.id == RitualSequenceItem.ritual_version_id,
                )
                .join(Gate, Gate.id == RitualVersion.gate_id)
                .where(
                    RitualSequenceItem.architecture_version_id == architecture.id,
                    RitualSequenceItem.slot_kind == RitualPieceType.GATE,
                    RitualSequenceItem.gate_position != Gate.sequence_position,
                )
                .limit(1)
            )
            if bad_gate_slot is not None:
                issues.append(
                    ValidationIssue(
                        code="gate_slot_identity",
                        message=(
                            "Gate slot does not match the referenced gate identity."
                        ),
                        record_id=bad_gate_slot,
                    )
                )
        elif (
            stages
            or len(items) != 1
            or items[0].slot_kind is not RitualPieceType.COLLECTIVE
        ):
            issues.append(
                ValidationIssue(
                    code="collective_separation",
                    message=(
                        "Collective architecture must remain separate from 42 pieces."
                    ),
                    record_id=architecture.id,
                )
            )

    async def _validate_assets(self, issues: list[ValidationIssue]) -> None:
        rows = await self._session.execute(
            select(RitualSourceVersion, ObjectAsset)
            .join(
                RitualVersionSourceAsset,
                RitualVersionSourceAsset.source_version_id == RitualSourceVersion.id,
            )
            .join(
                ObjectAsset, ObjectAsset.id == RitualVersionSourceAsset.source_asset_id
            )
        )
        for version, asset in rows:
            if version.source_file_hash != asset.sha256:
                issues.append(
                    ValidationIssue(
                        code="source_hash_mismatch",
                        message="Ritual version and source asset hashes disagree.",
                        record_id=version.id,
                    )
                )
                continue
            try:
                await asyncio.to_thread(
                    self._store.read_bytes,
                    asset.storage_key,
                    expected_sha256=asset.sha256,
                )
            except Exception as exc:
                issues.append(
                    ValidationIssue(
                        code="source_asset_corrupt",
                        message=(
                            f"Source asset verification failed: {type(exc).__name__}"
                        ),
                        record_id=asset.id,
                    )
                )
