"""Deterministic orchestration around a small number of structured LLM calls."""

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID

from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.knowledge.models import Source, SourceSegment
from app.speech_structure.domain import (
    GLOBAL_PROMPT_VERSION,
    LOCAL_PROMPT_VERSION,
    SectionRole,
)
from app.speech_structure.prompts import GLOBAL_INSTRUCTIONS, LOCAL_INSTRUCTIONS
from app.speech_structure.schemas import GlobalOutline, LocalTopicAnalysis


@dataclass(frozen=True, slots=True)
class TranscriptWindow:
    index: int
    segments: tuple[SourceSegment, ...]


@dataclass(frozen=True, slots=True)
class ProposedSection:
    key: str
    parent_key: str | None
    title: str
    summary: str | None
    role: str
    confidence: float
    sort_order: int
    segment_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class PipelineResult:
    sections: tuple[ProposedSection, ...]
    windows: int
    input_hash: str


class SpeechStructurePipeline:
    """Load transcript windows, ask for structure, then map exact segments."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str = "configured-default",
        window_seconds: int = 480,
        overlap_seconds: int = 60,
    ) -> None:
        self.provider = provider
        self.model = model
        self.window_seconds = window_seconds
        self.overlap_seconds = overlap_seconds

    def build_windows(self, segments: list[SourceSegment]) -> list[TranscriptWindow]:
        if not segments:
            return []
        windows: list[TranscriptWindow] = []
        start = 0
        while start < len(segments):
            first = segments[start]
            cutoff = float(first.start_seconds) + self.window_seconds
            end = start
            while (
                end + 1 < len(segments)
                and float(segments[end + 1].end_seconds) <= cutoff
            ):
                end += 1
            windows.append(
                TranscriptWindow(len(windows), tuple(segments[start : end + 1]))
            )
            if end >= len(segments) - 1:
                break
            next_start = end + 1
            overlap_start = float(segments[end].end_seconds) - self.overlap_seconds
            for candidate in range(start, end + 1):
                if float(segments[candidate].start_seconds) >= overlap_start:
                    next_start = candidate
                    break
            start = max(start + 1, next_start)
        return windows

    async def analyze(
        self, source: Source, segments: list[SourceSegment], input_hash: str
    ) -> PipelineResult:
        windows = self.build_windows(segments)
        all_topics: list[dict[str, Any]] = []
        known_ids = {segment.id for segment in segments}
        for window in windows:
            payload = "\n".join(
                f"[{segment.id}] {segment.start_seconds}-{segment.end_seconds}: "
                f"{segment.raw_text}"
                for segment in window.segments
            )
            request = StructuredExtractionRequest(
                task="speech_structure_local_topics",
                prompt_version=LOCAL_PROMPT_VERSION,
                model=self.model,
                instructions=LOCAL_INSTRUCTIONS,
                input_text=payload,
                output_model=LocalTopicAnalysis,
            )
            result = await self.provider.extract(request)
            analysis = LocalTopicAnalysis.model_validate(result.model_dump())
            for topic in analysis.topics:
                unknown = [item for item in topic.segment_ids if item not in known_ids]
                if unknown:
                    raise ValueError(f"unknown source segment IDs: {unknown}")
                all_topics.append(
                    {
                        "id": f"w{window.index}:{topic.temporary_id}",
                        "title": topic.title,
                        "role": topic.role,
                        "description": topic.description,
                        "confidence": topic.confidence,
                        "segment_ids": topic.segment_ids,
                    }
                )
        topics_text = json.dumps(all_topics, ensure_ascii=False, default=str)
        outline_request = StructuredExtractionRequest(
            task="speech_structure_global_outline",
            prompt_version=GLOBAL_PROMPT_VERSION,
            model=self.model,
            instructions=GLOBAL_INSTRUCTIONS,
            input_text=topics_text,
            output_model=GlobalOutline,
        )
        outline_result = await self.provider.extract(outline_request)
        outline = GlobalOutline.model_validate(outline_result.model_dump())
        topic_map = {topic["id"]: topic for topic in all_topics}
        result_sections: list[ProposedSection] = []
        keys = {item.temporary_id for item in outline.sections}
        for item in outline.sections:
            if item.parent_temporary_id and item.parent_temporary_id not in keys:
                raise ValueError(f"unknown parent section: {item.parent_temporary_id}")
            segment_ids: list[UUID] = []
            for topic_id in item.source_topic_ids:
                local_topic = topic_map.get(topic_id)
                if local_topic is None:
                    raise ValueError(f"unknown local topic: {topic_id}")
                segment_ids.extend(local_topic["segment_ids"])
            role = (
                item.role
                if item.role in {role.value for role in SectionRole}
                else SectionRole.TOPIC.value
            )
            result_sections.append(
                ProposedSection(
                    key=item.temporary_id,
                    parent_key=item.parent_temporary_id,
                    title=item.title,
                    summary=item.summary,
                    role=role,
                    confidence=item.confidence,
                    sort_order=item.sort_order,
                    segment_ids=tuple(dict.fromkeys(segment_ids)),
                )
            )
        self._validate_outline(result_sections)
        return PipelineResult(tuple(result_sections), len(windows), input_hash)

    @staticmethod
    def _validate_outline(sections: list[ProposedSection]) -> None:
        keys = {section.key for section in sections}
        if len(keys) != len(sections):
            raise ValueError("duplicate section IDs")
        for section in sections:
            if section.parent_key == section.key:
                raise ValueError("section cannot parent itself")
            if section.parent_key and section.parent_key not in keys:
                raise ValueError(f"orphan section parent: {section.parent_key}")
        for section in sections:
            seen: set[str] = set()
            current: ProposedSection | None = section
            while current and current.parent_key:
                if current.key in seen:
                    raise ValueError("cycle in section hierarchy")
                seen.add(current.key)
                current = next(
                    (item for item in sections if item.key == current.parent_key), None
                )


def transcript_input_hash(
    source: Source, segments: list[SourceSegment], configuration: dict[str, Any]
) -> str:
    payload = {
        "source_id": str(source.id),
        "segments": [(str(item.id), item.content_hash) for item in segments],
        "configuration": configuration,
        "prompt_versions": [LOCAL_PROMPT_VERSION, GLOBAL_PROMPT_VERSION],
    }
    return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
