"""Focused unit tests for semantic content invariants."""

import pytest

from app.semantic_content.generation import AutomatedContentService
from app.semantic_content.schemas import (
    EvidenceReference,
    GlobalOutline,
    GlobalOutlineNode,
    SynthesisCluster,
    SynthesisSpec,
)
from app.semantic_content.structuring import SemanticStructureService


def test_outline_rejects_child_outside_parent() -> None:
    outline = GlobalOutline(
        title="test",
        sections=[
            GlobalOutlineNode(
                title="parent",
                summary="summary",
                main_idea="idea",
                start_sequence=1,
                end_sequence=5,
                children=[
                    GlobalOutlineNode(
                        title="child",
                        summary="summary",
                        main_idea="idea",
                        start_sequence=4,
                        end_sequence=6,
                    )
                ],
            )
        ],
    )
    with pytest.raises(ValueError, match="escapes parent"):
        SemanticStructureService._validate_outline(outline, 1, 10)


def test_synthesis_cannot_change_candidate_provenance() -> None:
    evidence: list[object] = [
        {
            "candidate_id": "E0001",
            "source_id": "source-1",
            "source_version_id": "version-1",
            "source_title": "Title",
            "source_url": None,
            "timestamp_start": None,
            "timestamp_end": None,
            "chunk_id": "chunk-1",
            "semantic_root_path": None,
            "semantic_hit_path": None,
        }
    ]
    synthesis = SynthesisSpec(
        clusters=[
            SynthesisCluster(
                cluster_id="C1",
                title="Cluster",
                core_idea="Idea",
                supporting_points=["Point"],
                references=[
                    EvidenceReference(
                        candidate_id="E0001",
                        source_id="source-1",
                        source_version_id="version-1",
                        source_title="Changed title",
                        chunk_id="chunk-1",
                    )
                ],
            )
        ]
    )
    with pytest.raises(ValueError, match="changed provenance"):
        AutomatedContentService._validate_references(synthesis, evidence)


def test_global_state_deduplicates_without_reordering() -> None:
    assert AutomatedContentService._merge(
        ["awareness", "experience"],
        ["experience", "language"],
    ) == ["awareness", "experience", "language"]
