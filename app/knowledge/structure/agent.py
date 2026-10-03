"""Structured-extraction agent for hierarchical source structure.

Pass A proposes local nodes over overlapping transcript windows; Pass B merges
the proposals into one global hierarchy. The agent only sees segment
``sequence`` numbers — the service resolves them to real segment UUIDs.
"""

import json
import logging
from collections.abc import Callable

from pydantic import ValidationError

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
    SourceStructureOutputRaw,
    StructureNodeProposal,
)
from app.knowledge.windowing import WindowSegment, build_windows

logger = logging.getLogger(__name__)


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
                output_model=SourceStructureOutputRaw,
            )
            result = await self.provider.extract(request)
            raw = SourceStructureOutputRaw.model_validate(result.model_dump())
            proposal = SourceStructureOutput(
                nodes=self._valid_nodes(raw, within=window.segments)
            )
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
            output_model=SourceStructureOutputRaw,
        )
        merged = await self.provider.extract(merge_request)
        raw = SourceStructureOutputRaw.model_validate(merged.model_dump())
        return SourceStructureOutput(nodes=self._valid_nodes(raw))

    @staticmethod
    def _valid_nodes(
        raw: SourceStructureOutputRaw,
        *,
        within: tuple[WindowSegment, ...] | None = None,
    ) -> list[StructureNodeProposal]:
        """Strict-validate each proposed node; drop malformed items.

        Unknown keys are trimmed first — provider commentary fields must
        not discard an otherwise valid node. Spans that escape the local
        window or invert are dropped as well; the structure validator
        reports resulting coverage gaps instead of crashing the run.
        """

        fields = set(StructureNodeProposal.model_fields)
        valid_sequences = (
            {segment.sequence for segment in within} if within is not None else None
        )
        nodes: list[StructureNodeProposal] = []
        for item in raw.nodes:
            trimmed = {key: item[key] for key in fields if key in item}
            try:
                node = StructureNodeProposal.model_validate(trimmed)
            except ValidationError:
                logger.warning(
                    "source_structure.invalid_node",
                    extra={"raw": str(item)[:500]},
                )
                continue
            if valid_sequences is not None and (
                node.start_segment_sequence not in valid_sequences
                or node.end_segment_sequence not in valid_sequences
            ):
                logger.warning(
                    "source_structure.node_escapes_window",
                    extra={
                        "temp_id": node.temp_id,
                        "span": (
                            node.start_segment_sequence,
                            node.end_segment_sequence,
                        ),
                    },
                )
                continue
            if node.end_segment_sequence < node.start_segment_sequence:
                logger.warning(
                    "source_structure.inverted_span",
                    extra={
                        "temp_id": node.temp_id,
                        "span": (
                            node.start_segment_sequence,
                            node.end_segment_sequence,
                        ),
                    },
                )
                continue
            nodes.append(node)
        return nodes


__all__ = [
    "SourceStructureAgent",
    "StructureNodeType",
    "StructureNodeProposal",
    "SourceStructureOutput",
]
