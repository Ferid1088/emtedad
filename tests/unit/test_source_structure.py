"""Unit coverage for the knowledge.structure domain (Phase 4)."""

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.knowledge.structure.agent import SourceStructureAgent
from app.knowledge.structure.domain import StructureNodeType
from app.knowledge.structure.schemas import (
    SourceStructureOutput,
    StructureNodeProposal,
)
from app.knowledge.structure.service import SourceStructureService
from app.knowledge.structure.validator import (
    SourceStructureValidator,
    StagedNode,
)


def _segment(sequence: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        sequence=sequence,
        start_seconds=Decimal(sequence * 10),
        end_seconds=Decimal(sequence * 10 + 9),
        raw_text=f"transcript segment {sequence} text",
        normalized_text=f"transcript segment {sequence} text",
        content_hash="a" * 64,
    )


def _staged(
    temp_id: str,
    start: int,
    end: int,
    *,
    parent: str | None = None,
    node_type: StructureNodeType = StructureNodeType.TOPIC,
    ordinal: int = 1,
    resolve: bool = True,
) -> StagedNode:
    return StagedNode(
        temp_id=temp_id,
        parent_temp_id=parent,
        node_type=node_type,
        title=f"Node {temp_id}",
        summary=f"Summary {temp_id}",
        start_segment_id=uuid4() if resolve else None,
        end_segment_id=uuid4() if resolve else None,
        start_sequence=start,
        end_sequence=end,
        start_seconds=Decimal(start),
        end_seconds=Decimal(end),
        ordinal=ordinal,
        confidence=0.8,
    )


class _FakeProvider:
    name = "fake-structure"

    def __init__(self, output: BaseModel):
        self.output = output
        self.requests: list = []

    async def extract(self, request):
        self.requests.append(request)
        return self.output


def test_validator_accepts_valid_nested_hierarchy() -> None:
    nodes = [
        _staged("root", 1, 10),
        _staged("story", 3, 8, parent="root", node_type=StructureNodeType.STORY),
    ]
    report = SourceStructureValidator().validate(nodes, list(range(1, 11)))
    assert report.valid
    assert report.node_count == 2
    assert report.maximum_depth == 2


def test_validator_rejects_child_escaping_parent_span() -> None:
    nodes = [
        _staged("root", 1, 5),
        _staged("child", 4, 9, parent="root"),
    ]
    report = SourceStructureValidator().validate(nodes, list(range(1, 11)))
    assert not report.valid
    assert any("escapes parent" in error for error in report.errors)


def test_validator_rejects_missing_parent_and_unknown_span() -> None:
    nodes = [
        _staged("orphan", 1, 3, parent="ghost", resolve=False),
        _staged("inverted", 8, 4),
    ]
    report = SourceStructureValidator().validate(nodes, list(range(1, 11)))
    assert not report.valid
    assert any("missing source span" in error for error in report.errors)
    assert any("start after end" in error for error in report.errors)


def test_validator_rejects_duplicate_sibling_ordinals() -> None:
    nodes = [
        _staged("a", 1, 4, ordinal=1),
        _staged("b", 5, 8, ordinal=1),
    ]
    report = SourceStructureValidator().validate(nodes, list(range(1, 11)))
    assert not report.valid
    assert any("sibling ordinals" in error for error in report.errors)


def test_validator_warns_on_uncovered_and_overlapping_siblings() -> None:
    nodes = [
        _staged("a", 1, 5, ordinal=1),
        _staged("b", 5, 8, ordinal=2),
    ]
    report = SourceStructureValidator().validate(nodes, list(range(1, 20)))
    assert report.valid
    assert any("overlapping siblings" in warning for warning in report.warnings)
    assert any("uncovered" in warning for warning in report.warnings)
    assert report.coverage_percent < 100


def test_agent_single_window_skips_merge_pass() -> None:
    segments = [_segment(index) for index in range(1, 6)]
    provider = _FakeProvider(
        SourceStructureOutput(
            nodes=[
                StructureNodeProposal(
                    temp_id="n1",
                    node_type=StructureNodeType.STORY,
                    title="Whole story",
                    summary="A continuous narrative",
                    start_segment_sequence=1,
                    end_segment_sequence=5,
                )
            ]
        )
    )
    agent = SourceStructureAgent(provider, window_size=120, overlap=16)
    output = asyncio.run(agent.propose(segments))  # type: ignore[arg-type]
    assert len(provider.requests) == 1
    assert output.nodes[0].node_type is StructureNodeType.STORY


def test_agent_rejects_node_escaping_window() -> None:
    segments = [_segment(index) for index in range(1, 200)]
    provider = _FakeProvider(
        SourceStructureOutput(
            nodes=[
                StructureNodeProposal(
                    temp_id="n1",
                    title="Escape",
                    summary="x",
                    start_segment_sequence=1,
                    end_segment_sequence=199,
                )
            ]
        )
    )
    agent = SourceStructureAgent(provider, window_size=40, overlap=8)
    with pytest.raises(ValueError, match="escapes its window"):
        asyncio.run(agent.propose(segments))  # type: ignore[arg-type]


def test_service_stage_maps_sequences_to_segment_ids() -> None:
    segments = [_segment(index) for index in range(1, 4)]
    output = SourceStructureOutput(
        nodes=[
            StructureNodeProposal(
                temp_id="n1",
                title="Span",
                summary="s",
                start_segment_sequence=2,
                end_segment_sequence=3,
            ),
            StructureNodeProposal(
                temp_id="bad",
                title="Bad",
                summary="s",
                start_segment_sequence=40,
                end_segment_sequence=41,
            ),
        ]
    )
    staged, errors = SourceStructureService._stage(output, segments)
    assert staged[0].start_segment_id == segments[1].id
    assert staged[0].end_segment_id == segments[2].id
    assert staged[1].start_segment_id is None
    assert errors and "bad" in errors[0]


def test_configuration_hash_is_deterministic() -> None:
    segments = [_segment(1), _segment(2)]
    version_id = uuid4()
    first = SourceStructureService._configuration_hash(version_id, {"a": 1}, segments)
    second = SourceStructureService._configuration_hash(version_id, {"a": 1}, segments)
    assert first == second
    changed = SourceStructureService._configuration_hash(version_id, {"a": 2}, segments)
    assert changed != first
