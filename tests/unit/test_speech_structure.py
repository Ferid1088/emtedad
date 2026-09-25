from types import SimpleNamespace
from uuid import uuid4

from app.main import create_app
from app.speech_structure.pipeline import SpeechStructurePipeline
from app.speech_structure.validator import StructureValidator


def _segment(text: str, start: float, end: float):
    return SimpleNamespace(
        id=uuid4(),
        start_seconds=start,
        end_seconds=end,
        raw_text=text,
        normalized_text=text,
    )


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
