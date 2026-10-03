"""Structured-extraction agent for hierarchical source structure.

Pass A proposes local nodes over overlapping transcript windows; Pass B merges
the proposals into one global hierarchy. The agent only sees segment
``sequence`` numbers — the service resolves them to real segment UUIDs.
"""

import json
from collections.abc import Callable

from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.knowledge.models import SourceSegment
from app.knowledge.structure.domain import (
    LOCAL_PASS_PROMPT_VERSION,
    MERGE_PASS_PROMPT_VERSION,
    StructureNodeType,
)
from app.knowledge.structure.prompts import (
    LOCAL_INSTRUCTIONS,
    MERGE_INSTRUCTIONS,
)
from app.knowledge.structure.schemas import (
    SourceStructureOutput,
    StructureNodeProposal,
)
from app.knowledge.windowing import WindowSegment, build_windows


class SourceStructureAgent:
    """Two-pass structure extraction over one source version's segments."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str = "configured-default",
        window_size: int = 120,
        overlap: int = 16,
    ) -> None:
        self.provider = provider
        self.model = model
        self.window_size = window_size
        self.overlap = overlap

    async def propose(
        self,
        segments: list[SourceSegment],
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> SourceStructureOutput:
        window_segments = [
            WindowSegment(
                id=segment.id,
                sequence=segment.sequence,
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                normalized_text=segment.raw_text,
            )
            for segment in segments
        ]
        windows = build_windows(
            window_segments, window_size=self.window_size, overlap=self.overlap
        )
        if not windows:
            return SourceStructureOutput()

        local: list[SourceStructureOutput] = []
        for index, window in enumerate(windows, start=1):
            request = StructuredExtractionRequest(
                task="source_structure_local",
                prompt_version=LOCAL_PASS_PROMPT_VERSION,
                model=self.model,
                instructions=LOCAL_INSTRUCTIONS,
                input_text=window.text,
                output_model=SourceStructureOutput,
            )
            result = await self.provider.extract(request)
            proposal = SourceStructureOutput.model_validate(result.model_dump())
            self._assert_within_window(proposal, window.segments)
            local.append(proposal)
            if on_progress is not None:
                on_progress(f"local:{index}/{len(windows)}")

        if len(local) == 1:
            return local[0]

        if on_progress is not None:
            on_progress("merge")
        merge_request = StructuredExtractionRequest(
            task="source_structure_merge",
            prompt_version=MERGE_PASS_PROMPT_VERSION,
            model=self.model,
            instructions=MERGE_INSTRUCTIONS,
            input_text=json.dumps(
                [
                    {
                        "region": index + 1,
                        "nodes": [node.model_dump(mode="json") for node in part.nodes],
                    }
                    for index, part in enumerate(local)
                ],
                ensure_ascii=False,
            ),
            output_model=SourceStructureOutput,
        )
        merged = await self.provider.extract(merge_request)
        return SourceStructureOutput.model_validate(merged.model_dump())

    @staticmethod
    def _assert_within_window(
        proposal: SourceStructureOutput, segments: tuple[WindowSegment, ...]
    ) -> None:
        valid = {segment.sequence for segment in segments}
        for node in proposal.nodes:
            if (
                node.start_segment_sequence not in valid
                or node.end_segment_sequence not in valid
            ):
                raise ValueError(
                    f"local node {node.temp_id} escapes its window "
                    f"({node.start_segment_sequence}-{node.end_segment_sequence})"
                )
            if node.end_segment_sequence < node.start_segment_sequence:
                raise ValueError(f"local node {node.temp_id} has an inverted span")


__all__ = [
    "SourceStructureAgent",
    "StructureNodeType",
    "StructureNodeProposal",
    "SourceStructureOutput",
]
