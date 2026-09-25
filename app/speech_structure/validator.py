"""Structural and provenance validation for persisted structures."""

from collections import Counter
from collections.abc import Iterable

from app.knowledge.models import SourceSegment
from app.speech_structure.models import SpeechSection, SpeechSectionSegment
from app.speech_structure.schemas import ValidationReport


class StructureValidator:
    def __init__(self, *, coverage_threshold: float = 0.95) -> None:
        self.coverage_threshold = coverage_threshold

    def validate(
        self,
        sections: Iterable[SpeechSection],
        mappings: Iterable[SpeechSectionSegment],
        segments: Iterable[SourceSegment],
    ) -> ValidationReport:
        section_list = list(sections)
        mapping_list = list(mappings)
        segment_list = list(segments)
        known = {segment.id for segment in segment_list}
        meaningful = {
            segment.id
            for segment in segment_list
            if len(segment.raw_text.strip().split()) >= 3
        }
        primary = [item for item in mapping_list if item.relation_type == "PRIMARY"]
        primary_ids = [item.source_segment_id for item in primary]
        counts = Counter(primary_ids)
        duplicated = [str(key) for key, value in counts.items() if value > 1]
        invalid = [
            str(item.source_segment_id)
            for item in mapping_list
            if item.source_segment_id not in known
        ]
        section_ids = {item.id for item in section_list}
        orphan = [
            str(item.id)
            for item in section_list
            if item.parent_id and item.parent_id not in section_ids
        ]
        invalid_parent = list(orphan)
        invalid_root = [
            str(item.id) for item in section_list if item.root_id not in section_ids
        ]
        children = {
            item.parent_id for item in section_list if item.parent_id is not None
        }
        mapped_by_section = {item.section_id for item in mapping_list}
        empty_leaves = [
            str(item.id)
            for item in section_list
            if item.id not in children and item.id not in mapped_by_section
        ]
        assigned = len(meaningful & set(primary_ids))
        coverage = (assigned / len(meaningful) * 100) if meaningful else 100.0
        depths = {item.id: item.level for item in section_list}
        errors = duplicated or invalid or orphan or invalid_root or empty_leaves
        ready = not errors and coverage >= self.coverage_threshold * 100
        return ValidationReport(
            total_transcript_segments=len(segment_list),
            meaningful_transcript_segments=len(meaningful),
            assigned_meaningful_segments=assigned,
            unassigned_meaningful_segments=len(meaningful) - assigned,
            assignment_coverage_percent=round(coverage, 2),
            duplicated_primary_assignments=duplicated,
            invalid_source_segment_ids=invalid,
            orphan_sections=orphan,
            invalid_parent_links=invalid_parent,
            invalid_root_links=invalid_root,
            empty_leaf_sections=empty_leaves,
            section_count=len(section_list),
            maximum_hierarchy_depth=max(depths.values(), default=0),
            low_confidence_sections=[
                str(item.id)
                for item in section_list
                if item.confidence is not None and item.confidence < 0.5
            ],
            low_confidence_mappings=[
                str(item.id)
                for item in mapping_list
                if item.confidence is not None and item.confidence < 0.5
            ],
            ready=ready,
            status="READY" if ready else "REVIEW",
        )
