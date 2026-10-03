"""Validator for staged source-structure hierarchies.

Operates on ``StagedNode`` objects (proposals with resolved segment ranges)
before persistence, so invalid structures never reach the database.
"""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.knowledge.structure.domain import ATOMIC_NODE_TYPES, StructureNodeType
from app.knowledge.structure.schemas import StructureValidationReport


@dataclass(frozen=True, slots=True)
class StagedNode:
    temp_id: str
    parent_temp_id: str | None
    node_type: StructureNodeType
    title: str
    summary: str
    start_segment_id: UUID | None
    end_segment_id: UUID | None
    start_sequence: int
    end_sequence: int
    start_seconds: Decimal | None
    end_seconds: Decimal | None
    ordinal: int
    confidence: float
    level: int | None = None


class SourceStructureValidator:
    """Enforces every rule that must hold before nodes are persisted."""

    def validate(
        self, nodes: list[StagedNode], segment_sequences: list[int]
    ) -> StructureValidationReport:
        errors: list[str] = []
        warnings: list[str] = []
        by_temp = {node.temp_id: node for node in nodes}
        if len(by_temp) != len(nodes):
            errors.append("duplicate temp_id values")
            return StructureValidationReport(errors=errors, node_count=len(nodes))

        segment_set = set(segment_sequences)
        parents: dict[str | None, list[StagedNode]] = {}
        for node in nodes:
            parents.setdefault(node.parent_temp_id, []).append(node)

        levels = self._levels(by_temp, errors)
        for node in nodes:
            label = f"node {node.temp_id} ({node.title[:40]})"
            if node.start_segment_id is None or node.end_segment_id is None:
                errors.append(f"{label}: missing source span")
                continue
            if node.start_sequence not in segment_set:
                errors.append(f"{label}: start segment not in source version")
            if node.end_sequence not in segment_set:
                errors.append(f"{label}: end segment not in source version")
            if node.start_sequence > node.end_sequence:
                errors.append(f"{label}: start after end")
            if not node.summary.strip():
                errors.append(f"{label}: summary without content")
            if (
                node.start_seconds is not None
                and node.end_seconds is not None
                and node.start_seconds > node.end_seconds
            ):
                errors.append(f"{label}: inverted timestamps")
            parent = by_temp.get(node.parent_temp_id or "")
            if node.parent_temp_id is not None:
                if parent is None:
                    errors.append(f"{label}: parent not in hierarchy")
                else:
                    expected = (levels.get(parent.temp_id) or 1) + 1
                    if levels.get(node.temp_id) != expected:
                        errors.append(f"{label}: level inconsistent with parent")
                    if node.level is not None and node.level != expected:
                        errors.append(f"{label}: level inconsistent with parent")
                    if not (
                        node.start_sequence >= parent.start_sequence
                        and node.end_sequence <= parent.end_sequence
                    ):
                        errors.append(f"{label}: span escapes parent span")
            if node.node_type in ATOMIC_NODE_TYPES and (
                node.end_sequence - node.start_sequence < 0
            ):
                errors.append(f"{label}: empty atomic span")

        for siblings in parents.values():
            ordinals = [node.ordinal for node in siblings]
            counts = Counter(ordinals)
            duplicated = sorted(key for key, n in counts.items() if n > 1)
            if duplicated:
                errors.append(f"duplicate sibling ordinals: {duplicated}")
            ordered = sorted(siblings, key=lambda item: item.ordinal)
            for left, right in zip(ordered, ordered[1:], strict=False):
                if right.start_sequence <= left.end_sequence:
                    warnings.append(
                        f"overlapping siblings: {left.temp_id} and {right.temp_id}"
                    )

        covered: set[int] = set()
        for node in nodes:
            covered.update(range(node.start_sequence, node.end_sequence + 1))
        uncovered = [seq for seq in segment_sequences if seq not in covered]
        if segment_sequences:
            coverage = len(segment_set - set(uncovered)) / len(segment_set)
        else:
            coverage = 0.0
        if uncovered:
            warnings.append(
                f"{len(uncovered)} transcript segments uncovered by structure"
            )
        span_total = max(segment_set, default=0) - min(segment_set, default=0) + 1
        for node in nodes:
            span = node.end_sequence - node.start_sequence + 1
            if span_total and span > max(span_total // 2, 50):
                warnings.append(f"oversized node {node.temp_id}: {span} segments")
            if span <= 1 and node.node_type in {
                StructureNodeType.TOPIC,
                StructureNodeType.SUBTOPIC,
            }:
                warnings.append(f"tiny structural node {node.temp_id}")

        return StructureValidationReport(
            errors=errors,
            warnings=warnings,
            node_count=len(nodes),
            maximum_depth=max(levels.values(), default=0),
            coverage_percent=round(coverage * 100, 2),
        )

    @staticmethod
    def _levels(by_temp: dict[str, StagedNode], errors: list[str]) -> dict[str, int]:
        levels: dict[str, int] = {}
        visiting: set[str] = set()

        def resolve(temp_id: str) -> int:
            if temp_id in levels:
                return levels[temp_id]
            if temp_id in visiting:
                errors.append(f"cycle at node {temp_id}")
                return 1
            visiting.add(temp_id)
            node = by_temp[temp_id]
            if node.parent_temp_id is None or node.parent_temp_id not in by_temp:
                level = 1
            else:
                level = resolve(node.parent_temp_id) + 1
            visiting.discard(temp_id)
            levels[temp_id] = level
            return level

        for temp_id in by_temp:
            resolve(temp_id)
        return levels
