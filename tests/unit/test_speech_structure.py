import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from app.main import create_app
from app.speech_structure import scheduler as scheduler_module
from app.speech_structure.pipeline import SpeechStructurePipeline
from app.speech_structure.routes import _segment_paragraphs
from app.speech_structure.schemas import (
    GlobalOutline,
    LocalTopic,
    LocalTopicAnalysis,
    OutlineSection,
)
from app.speech_structure.validator import StructureValidator


def _segment(text: str, start: float, end: float, sequence: int = 1):
    return SimpleNamespace(
        id=uuid4(),
        sequence=sequence,
        start_seconds=start,
        end_seconds=end,
        raw_text=text,
        normalized_text=text,
    )


class _FakeProvider:
    name = "fake"

    def __init__(self, local: BaseModel, global_: BaseModel):
        self.local = local
        self.global_ = global_
        self.requests = []

    async def extract(self, request):
        self.requests.append(request)
        if request.task == "speech_structure_local_topics":
            return self.local
        return self.global_


def test_window_builder_preserves_segment_boundaries_and_overlap() -> None:
    segments = [
        _segment(f"segment {index} with words", index * 100, index * 100 + 90)
        for index in range(8)
    ]
    windows = SpeechStructurePipeline(
        object(), window_seconds=300, overlap_seconds=100
    ).build_windows(segments)  # type: ignore[arg-type]
    assert windows
    assert all(window.segments for window in windows)
    assert windows[0].segments[-1].id == windows[1].segments[0].id


def test_pipeline_resolves_segment_labels_to_source_ids() -> None:
    segments = [
        _segment("first segment", 0, 90, sequence=1),
        _segment("second segment", 90, 180, sequence=2),
    ]
    provider = _FakeProvider(
        local=LocalTopicAnalysis(
            topics=[
                LocalTopic(temporary_id="t1", title="Topic", segment_ids=["s1", "s2"])
            ]
        ),
        global_=GlobalOutline(
            sections=[
                OutlineSection(
                    temporary_id="sec1", title="Section", source_topic_ids=["w0:t1"]
                )
            ]
        ),
    )
    result = asyncio.run(
        SpeechStructurePipeline(provider).analyze(  # type: ignore[arg-type]
            SimpleNamespace(),
            segments,
            "hash",  # type: ignore[arg-type]
        )
    )
    assert result.sections[0].segment_ids == (segments[0].id, segments[1].id)
    prompt = provider.requests[0].input_text
    assert "[s1]" in prompt and "[s2]" in prompt
    assert str(segments[0].id) not in prompt  # raw UUIDs never reach the model


def test_pipeline_rejects_unknown_segment_labels() -> None:
    segments = [_segment("only segment", 0, 90, sequence=1)]
    provider = _FakeProvider(
        local=LocalTopicAnalysis(
            topics=[LocalTopic(temporary_id="t1", title="T", segment_ids=["s1", "s99"])]
        ),
        global_=GlobalOutline(sections=[]),
    )
    with pytest.raises(ValueError, match="unknown source segment labels"):
        asyncio.run(
            SpeechStructurePipeline(provider).analyze(  # type: ignore[arg-type]
                SimpleNamespace(),
                segments,
                "hash",  # type: ignore[arg-type]
            )
        )


def test_pipeline_rejects_labels_outside_the_window() -> None:
    segments = [
        _segment("early", 0, 50, sequence=1),
        _segment("late", 200, 250, sequence=2),
    ]
    provider = _FakeProvider(
        local=LocalTopicAnalysis(
            topics=[LocalTopic(temporary_id="t1", title="T", segment_ids=["s2"])]
        ),
        global_=GlobalOutline(sections=[]),
    )
    pipeline = SpeechStructurePipeline(  # type: ignore[arg-type]
        provider, window_seconds=60, overlap_seconds=0
    )
    with pytest.raises(ValueError, match="unknown source segment labels"):
        asyncio.run(
            pipeline.analyze(
                SimpleNamespace(),
                segments,
                "hash",  # type: ignore[arg-type]
            )
        )


def test_local_topic_schema_rejects_uuid_shaped_segment_ids() -> None:
    with pytest.raises(ValidationError):
        LocalTopic(temporary_id="t1", title="T", segment_ids=[str(uuid4())])


@pytest.mark.asyncio
async def test_schedule_structure_analysis_enqueues_on_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    class _Service:
        def __init__(self, database):
            pass

        async def create_for_source(
            self, source_id, *, force=False, on_progress=None
        ):
            calls.append((source_id, force))

    scheduler = scheduler_module.SpeechStructureScheduler(
        object(), service_factory=_Service
    )
    monkeypatch.setattr(scheduler_module, "_scheduler", scheduler)
    source_id = uuid4()
    assert scheduler_module.schedule_structure_analysis(object(), source_id)
    assert not scheduler_module.schedule_structure_analysis(object(), source_id)
    await asyncio.gather(*scheduler._tasks)
    assert calls == [(source_id, False)]


@pytest.mark.asyncio
async def test_schedule_structure_analysis_survives_failures(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Service:
        def __init__(self, database):
            pass

        async def create_for_source(
            self, source_id, *, force=False, on_progress=None
        ):
            raise RuntimeError("boom")

    scheduler = scheduler_module.SpeechStructureScheduler(
        object(), service_factory=_Service
    )
    monkeypatch.setattr(scheduler_module, "_scheduler", scheduler)
    assert scheduler_module.schedule_structure_analysis(object(), uuid4())
    await asyncio.gather(*scheduler._tasks, return_exceptions=True)
    assert any(
        record.message == "speech_structure.background_failed"
        for record in caplog.records
    )


def test_segment_paragraphs_break_on_speech_pauses() -> None:
    segments = [
        _segment("first sentence", 0, 2, sequence=1),
        _segment("second sentence", 2, 4, sequence=2),
        _segment("after a long pause", 20, 22, sequence=3),
    ]
    assert _segment_paragraphs(segments) == [
        "first sentence second sentence",
        "after a long pause",
    ]


def test_validator_reports_non_contiguous_primary_mapping_coverage() -> None:
    first = _segment("one meaningful transcript segment", 0, 2)
    second = _segment("another meaningful transcript segment", 2, 4)
    section = SimpleNamespace(
        id=uuid4(), parent_id=None, root_id=None, level=1, confidence=0.9
    )
    section.root_id = section.id
    mappings = [
        SimpleNamespace(
            section_id=section.id,
            source_segment_id=first.id,
            relation_type="PRIMARY",
            confidence=0.9,
        ),
        SimpleNamespace(
            section_id=section.id,
            source_segment_id=second.id,
            relation_type="PRIMARY",
            confidence=0.9,
        ),
    ]
    report = StructureValidator().validate([section], mappings, [first, second])
    assert report.ready
    assert report.assignment_coverage_percent == 100
    assert report.duplicated_primary_assignments == []


def test_validator_flags_duplicate_primary_assignments() -> None:
    segment = _segment("meaningful transcript content", 0, 2)
    root = uuid4()
    sections = [
        SimpleNamespace(id=root, parent_id=None, root_id=root, level=1, confidence=0.9),
        SimpleNamespace(
            id=uuid4(), parent_id=root, root_id=root, level=2, confidence=0.9
        ),
    ]
    mappings = [
        SimpleNamespace(
            section_id=sections[0].id,
            source_segment_id=segment.id,
            relation_type="PRIMARY",
            confidence=0.9,
        ),
        SimpleNamespace(
            section_id=sections[1].id,
            source_segment_id=segment.id,
            relation_type="PRIMARY",
            confidence=0.9,
        ),
    ]
    report = StructureValidator().validate(sections, mappings, [segment])
    assert not report.ready
    assert report.duplicated_primary_assignments == [str(segment.id)]


def test_owner_routes_expose_speech_structure_list_and_detail() -> None:
    paths = create_app().openapi()["paths"]
    assert "/speech-structures" in paths
    assert "/speech-structures/{source_id}" in paths
