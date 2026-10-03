"""Validator for staged Knowledge Units before persistence."""

import hashlib
from dataclasses import dataclass
from uuid import UUID

from app.knowledge.units.domain import (
    ATOMIC_UNIT_TYPES,
    ClaimType,
    EvidenceLevel,
    KnowledgeUnitType,
)
from app.knowledge.units.schemas import UnitValidationReport


@dataclass(frozen=True, slots=True)
class StagedUnit:
    """A Knowledge Unit with its span resolved against real segments."""

    structure_node_id: UUID
    node_version_id: UUID
    source_version_id: UUID
    unit_type: KnowledgeUnitType
    title: str
    summary: str
    full_text: str
    start_segment_id: UUID | None
    end_segment_id: UUID | None
    start_sequence: int
    end_sequence: int
    atomic: bool
    evidence_level: EvidenceLevel
    claim_type: ClaimType
    content_hash: str
    quality_flags: dict[str, object] | None = None


class KnowledgeUnitValidator:
    def validate(self, units: list[StagedUnit]) -> UnitValidationReport:
        errors: list[str] = []
        seen_hashes: set[tuple[KnowledgeUnitType, str]] = set()
        for unit in units:
            label = f"unit {unit.title[:40]} ({unit.unit_type.value})"
            if unit.node_version_id != unit.source_version_id:
                errors.append(f"{label}: structure node and unit version mismatch")
            if (
                unit.start_segment_id is None
                or unit.end_segment_id is None
                or unit.start_sequence > unit.end_sequence
            ):
                errors.append(f"{label}: invalid source span")
            expected_hash = hashlib.sha256(unit.full_text.encode()).hexdigest()
            if unit.content_hash != expected_hash:
                errors.append(f"{label}: full_text hash mismatch")
            if not unit.full_text.strip():
                errors.append(f"{label}: empty full_text")
            if not unit.title.strip() or not unit.summary.strip():
                errors.append(f"{label}: missing title or summary")
            if unit.unit_type in ATOMIC_UNIT_TYPES and not unit.atomic:
                errors.append(f"{label}: atomic type must be atomic")
            key = (unit.unit_type, unit.content_hash)
            if key in seen_hashes:
                errors.append(f"{label}: duplicated unit")
            seen_hashes.add(key)
        return UnitValidationReport(errors=errors, unit_count=len(units))
