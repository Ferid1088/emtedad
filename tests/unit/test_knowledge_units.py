"""Unit coverage for Knowledge Unit extraction (Phase 5)."""

import hashlib
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.knowledge.structure.domain import StructureNodeType
from app.knowledge.units.domain import (
    ClaimType,
    EvidenceLevel,
    KnowledgeUnitType,
    default_unit_type,
    node_is_unit_eligible,
)
from app.knowledge.units.service import KnowledgeUnitService
from app.knowledge.units.validator import (
    KnowledgeUnitValidator,
    StagedUnit,
)


def _node(node_type: StructureNodeType, start: int, end: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        source_version_id=uuid4(),
        parent_id=None,
        node_type=node_type,
        title="node",
        summary="summary",
        start_segment_id=uuid4(),
        end_segment_id=uuid4(),
    )


def _segments(n: int = 10) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=uuid4(),
            sequence=index,
            normalized_text=f"normalized segment {index}",
            start_seconds=Decimal(index),
            end_seconds=Decimal(index + 1),
        )
        for index in range(1, n + 1)
    ]


def test_story_and_case_study_nodes_are_always_eligible() -> None:
    for node_type in (StructureNodeType.STORY, StructureNodeType.CASE_STUDY):
        assert node_is_unit_eligible(node_type, has_children=True)
        assert default_unit_type(node_type) in {
            KnowledgeUnitType.STORY,
            KnowledgeUnitType.CASE_STUDY,
        }


def test_container_nodes_with_children_are_not_eligible() -> None:
    assert not node_is_unit_eligible(StructureNodeType.TOPIC, has_children=True)
    assert node_is_unit_eligible(StructureNodeType.TOPIC, has_children=False)


def test_full_text_reconstructed_from_segments_not_summary() -> None:
    segments = _segments()
    node = _node(StructureNodeType.STORY, 3, 8)
    node.start_segment_id = segments[2].id
    node.end_segment_id = segments[7].id
    staged = KnowledgeUnitService._stage_unit(node, segments, None)  # type: ignore[arg-type]
    expected = "\n".join(f"normalized segment {index}" for index in range(3, 9))
    assert staged.full_text == expected
    assert staged.atomic
    assert staged.unit_type is KnowledgeUnitType.STORY
    assert staged.content_hash == hashlib.sha256(expected.encode()).hexdigest()
    assert "summary" not in staged.full_text


def test_validator_rejects_non_atomic_story() -> None:
    unit = StagedUnit(
        structure_node_id=uuid4(),
        node_version_id=uuid4(),
        source_version_id=uuid4(),
        unit_type=KnowledgeUnitType.STORY,
        title="t",
        summary="s",
        full_text="x",
        start_segment_id=uuid4(),
        end_segment_id=uuid4(),
        start_sequence=1,
        end_sequence=3,
        atomic=False,
        evidence_level=EvidenceLevel.NONE,
        claim_type=ClaimType.UNKNOWN,
        content_hash=hashlib.sha256(b"x").hexdigest(),
    )
    # node_version_id != source_version_id also yields an error
    report = KnowledgeUnitValidator().validate([unit])
    assert not report.valid
    assert any("atomic" in error for error in report.errors)


def test_validator_detects_duplicate_units() -> None:
    version = uuid4()
    text = "same text"
    digest = hashlib.sha256(text.encode()).hexdigest()
    base = dict(
        node_version_id=version,
        source_version_id=version,
        unit_type=KnowledgeUnitType.CLAIM,
        title="t",
        summary="s",
        full_text=text,
        start_segment_id=uuid4(),
        end_segment_id=uuid4(),
        start_sequence=1,
        end_sequence=2,
        atomic=False,
        evidence_level=EvidenceLevel.NONE,
        claim_type=ClaimType.UNKNOWN,
        content_hash=digest,
    )
    units = [
        StagedUnit(structure_node_id=uuid4(), **base),  # type: ignore[arg-type]
        StagedUnit(structure_node_id=uuid4(), **base),  # type: ignore[arg-type]
    ]
    report = KnowledgeUnitValidator().validate(units)
    assert not report.valid
    assert any("duplicated" in error for error in report.errors)


def test_eligible_nodes_skip_interior_containers() -> None:
    parent = _node(StructureNodeType.TOPIC, 1, 10)
    child = _node(StructureNodeType.STORY, 2, 6)
    child.parent_id = parent.id
    leaf_topic = _node(StructureNodeType.TOPIC, 8, 10)
    leaf_topic.parent_id = parent.id
    nodes = [parent, child, leaf_topic]
    eligible = KnowledgeUnitService._eligible(nodes)  # type: ignore[arg-type]
    assert child in eligible
    assert leaf_topic in eligible
    assert parent not in eligible
