"""Section-parallel writing and the transition editor's safety net."""

import asyncio
import json

import pytest
from pydantic import BaseModel

from app.content_engine.section_writer import (
    smooth_transitions,
    write_sections_parallel,
)
from app.knowledge.llm.base import StructuredExtractionRequest


class _Writer:
    name = "fake"

    def __init__(self) -> None:
        self.running = 0
        self.peak = 0
        self.payloads: list[dict[str, object]] = []

    async def extract(self, request: StructuredExtractionRequest) -> BaseModel:
        self.running += 1
        self.peak = max(self.peak, self.running)
        await asyncio.sleep(0.02)
        self.running -= 1
        payload = json.loads(request.input_text)
        self.payloads.append(payload)
        section = payload["section"]
        return request.output_model.model_validate(
            {"text": f"متن بخش {section['ordinal']}", "estimated_duration_seconds": 60}
        )


@pytest.mark.asyncio
async def test_each_section_is_written_by_its_own_parallel_agent() -> None:
    writer = _Writer()
    sections = [
        {"ordinal": i, "purpose": f"p{i}", "narrative_role": "r", "target_words": 300}
        for i in range(4)
    ]
    texts = await write_sections_parallel(
        provider=writer,
        model="m",
        base_instructions="write",
        base_payload={"brief": {"question": "q"}},
        sections=sections,
        claims_by_section={1: [{"proposition": "only-for-1"}]},
        general_claims=[{"proposition": "general"}],
        concurrency=4,
    )
    assert texts == [f"متن بخش {i}" for i in range(4)]  # order preserved
    assert writer.peak == 4  # really parallel
    by_ordinal = {p["section"]["ordinal"]: p for p in writer.payloads}
    assert {"proposition": "only-for-1"} in by_ordinal[1]["claims"]
    assert {"proposition": "only-for-1"} not in by_ordinal[2]["claims"]
    assert by_ordinal[0]["previous_section"] is None
    assert by_ordinal[3]["next_section"] is None
    assert by_ordinal[2]["previous_section"]["purpose"] == "p1"


class _Editor:
    name = "fake"

    def __init__(self, text: str | None) -> None:
        self.text = text

    async def extract(self, request: StructuredExtractionRequest) -> BaseModel:
        if self.text is None:
            raise RuntimeError("down")
        return request.output_model.model_validate({"text": self.text})


@pytest.mark.asyncio
async def test_editor_result_is_kept_only_when_length_is_stable() -> None:
    original = " ".join(["کلمه"] * 100)
    smoothed = " ".join(["کلمه"] * 102)
    assert (
        await smooth_transitions(
            provider=_Editor(smoothed), model="m", text=original, language="fa"
        )
        == smoothed
    )
    shortened = " ".join(["کلمه"] * 60)
    assert (
        await smooth_transitions(
            provider=_Editor(shortened), model="m", text=original, language="fa"
        )
        == original
    )
    assert (
        await smooth_transitions(
            provider=_Editor(None), model="m", text=original, language="fa"
        )
        == original
    )
