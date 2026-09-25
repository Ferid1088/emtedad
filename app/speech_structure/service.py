"""Application service for generating and querying speech structures."""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.knowledge.llm.base import LLMProvider
from app.knowledge.llm.codex import CodexCliProvider
from app.knowledge.models import Source, SourceSegment, SourceVersion
from app.speech_structure.domain import SegmentRelation, StructureStatus
from app.speech_structure.models import (
    SpeechSection,
    SpeechSectionSegment,
    SpeechStructure,
    SpeechStructureRun,
)
from app.speech_structure.pipeline import (
    ProposedSection,
    SpeechStructurePipeline,
    transcript_input_hash,
)
from app.speech_structure.schemas import ValidationReport
from app.speech_structure.validator import StructureValidator

logger = logging.getLogger(__name__)


class SpeechStructureService:
    def __init__(
        self,
        database: Database,
        provider: LLMProvider | None = None,
        *,
        model: str = "configured-default",
        window_seconds: int = 480,
        overlap_seconds: int = 60,
        coverage_threshold: float = 0.95,
    ) -> None:
        self.database = database
        self.provider = provider or CodexCliProvider()
        self.model = model
        self.window_seconds = window_seconds
        self.overlap_seconds = overlap_seconds
        self.coverage_threshold = coverage_threshold

    async def create_for_source(
        self, source_id: UUID, *, force: bool = False
    ) -> SpeechStructure:
        async with self.database.transaction() as session:
            source, source_version, segments = await self._load_transcript(
                session, source_id
            )
            input_hash = transcript_input_hash(
                source,
                segments,
                {
                    "window_seconds": self.window_seconds,
                    "overlap_seconds": self.overlap_seconds,
                },
            )
            cached = await session.scalar(
                select(SpeechStructure)
                .where(
                    SpeechStructure.source_id == source_id,
                    SpeechStructure.input_hash == input_hash,
                )
                .order_by(SpeechStructure.version.desc())
            )
            if (
                cached is not None
                and not force
                and cached.status
                in {StructureStatus.READY.value, StructureStatus.REVIEW.value}
            ):
                return cached
            latest = await session.scalar(
                select(func.max(SpeechStructure.version)).where(
                    SpeechStructure.source_id == source_id
                )
            )
            structure = SpeechStructure(
                id=uuid4(),
                source_id=source.id,
                source_version_id=source_version.id,
                version=int(latest or 0) + 1,
                status=StructureStatus.PROCESSING.value,
                language=source.language,
                title=source.title,
                input_hash=input_hash,
            )
            session.add(structure)
            await session.flush()
            run = SpeechStructureRun(
                speech_structure_id=structure.id,
                provider=getattr(self.provider, "name", type(self.provider).__name__),
                model=self.model,
                prompt_version="speech_structure_local_topics_v1+speech_structure_global_outline_v1",
                input_hash=input_hash,
                status=StructureStatus.PROCESSING.value,
            )
            session.add(run)
            try:
                result = await SpeechStructurePipeline(
                    self.provider,
                    model=self.model,
                    window_seconds=self.window_seconds,
                    overlap_seconds=self.overlap_seconds,
                ).analyze(source, segments, input_hash)
                await self._persist_sections(session, structure, result.sections)
                await session.flush()
                sections = list(
                    await session.scalars(
                        select(SpeechSection).where(
                            SpeechSection.speech_structure_id == structure.id
                        )
                    )
                )
                mappings = (
                    list(
                        await session.scalars(
                            select(SpeechSectionSegment).where(
                                SpeechSectionSegment.section_id.in_(
                                    [item.id for item in sections]
                                )
                            )
                        )
                    )
                    if sections
                    else []
                )
                report = StructureValidator(
                    coverage_threshold=self.coverage_threshold
                ).validate(sections, mappings, segments)
                structure.status = report.status
                structure.completed_at = datetime.now(UTC)
                run.status = report.status
                run.completed_at = structure.completed_at
                run.metrics = report.model_dump(mode="json") | {
                    "windows": result.windows
                }
                await self._supersede_previous(session, source_id, structure.id)
            except Exception as exc:
                structure.status = StructureStatus.FAILED.value
                run.status = StructureStatus.FAILED.value
                run.error = str(exc)[:2000]
                run.completed_at = datetime.now(UTC)
                logger.exception(
                    "speech_structure.failed",
                    extra={"source_id": str(source_id), "run_id": str(run.id)},
                )
                return structure
            return structure

    async def regenerate(self, source_id: UUID) -> SpeechStructure:
        return await self.create_for_source(source_id, force=True)

    async def backfill_all(
        self, *, limit: int | None = None, force: bool = False
    ) -> dict[str, Any]:
        async with self.database.transaction() as session:
            source_ids = list(
                await session.scalars(
                    select(Source.id)
                    .join(SourceVersion, SourceVersion.source_id == Source.id)
                    .join(
                        SourceSegment,
                        SourceSegment.source_version_id == SourceVersion.id,
                    )
                    .distinct()
                    .order_by(Source.id)
                    .limit(limit)
                )
            )
        results: list[dict[str, Any]] = []
        for source_id in source_ids:
            try:
                structure = await self.create_for_source(source_id, force=force)
                results.append(
                    {
                        "source_id": str(source_id),
                        "status": structure.status,
                        "version": structure.version,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "source_id": str(source_id),
                        "status": StructureStatus.FAILED.value,
                        "error": str(exc),
                    }
                )
        return {"sources": len(source_ids), "results": results}

    async def get_tree(self, structure_id: UUID) -> list[dict[str, Any]]:
        async with self.database.transaction() as session:
            sections = list(
                await session.scalars(
                    select(SpeechSection)
                    .where(SpeechSection.speech_structure_id == structure_id)
                    .order_by(
                        SpeechSection.level,
                        SpeechSection.sort_order,
                        SpeechSection.section_number,
                    )
                )
            )
        by_parent: dict[UUID | None, list[SpeechSection]] = {}
        for section in sections:
            by_parent.setdefault(section.parent_id, []).append(section)

        def build(section: SpeechSection) -> dict[str, Any]:
            return {
                "id": section.id,
                "number": section.section_number,
                "title": section.title,
                "summary": section.summary,
                "role": section.section_role,
                "confidence": section.confidence,
                "children": [build(child) for child in by_parent.get(section.id, [])],
            }

        return [build(section) for section in by_parent.get(None, [])]

    async def get_section(self, section_id: UUID) -> SpeechSection | None:
        async with self.database.transaction() as session:
            return await session.get(SpeechSection, section_id)

    async def get_section_segments(self, section_id: UUID) -> list[SourceSegment]:
        async with self.database.transaction() as session:
            return list(
                await session.scalars(
                    select(SourceSegment)
                    .join(
                        SpeechSectionSegment,
                        SpeechSectionSegment.source_segment_id == SourceSegment.id,
                    )
                    .where(SpeechSectionSegment.section_id == section_id)
                    .order_by(SpeechSectionSegment.sequence)
                )
            )

    async def validate(self, structure_id: UUID) -> ValidationReport:
        async with self.database.transaction() as session:
            structure = await session.get(SpeechStructure, structure_id)
            if structure is None:
                raise ValueError("speech structure not found")
            segments = list(
                await session.scalars(
                    select(SourceSegment)
                    .where(
                        SourceSegment.source_version_id == structure.source_version_id
                    )
                    .order_by(SourceSegment.sequence)
                )
            )
            sections = list(
                await session.scalars(
                    select(SpeechSection).where(
                        SpeechSection.speech_structure_id == structure_id
                    )
                )
            )
            mappings = list(
                await session.scalars(
                    select(SpeechSectionSegment)
                    .join(SpeechSection)
                    .where(SpeechSection.speech_structure_id == structure_id)
                )
            )
            return StructureValidator(
                coverage_threshold=self.coverage_threshold
            ).validate(sections, mappings, segments)

    async def get_root_family(self, section_id: UUID) -> list[SpeechSection]:
        async with self.database.transaction() as session:
            section = await session.get(SpeechSection, section_id)
            if section is None:
                return []
            root_id = section.root_id
            all_sections = list(
                await session.scalars(
                    select(SpeechSection)
                    .where(
                        SpeechSection.speech_structure_id == section.speech_structure_id
                    )
                    .order_by(
                        SpeechSection.level,
                        SpeechSection.sort_order,
                        SpeechSection.section_number,
                    )
                )
            )
            return [item for item in all_sections if item.root_id == root_id]

    async def _load_transcript(
        self, session: AsyncSession, source_id: UUID
    ) -> tuple[Source, SourceVersion, list[SourceSegment]]:
        source = await session.get(Source, source_id)
        if source is None:
            raise ValueError("source not found")
        source_version = await session.scalar(
            select(SourceVersion)
            .where(SourceVersion.source_id == source_id)
            .order_by(SourceVersion.created_at.desc())
        )
        if source_version is None:
            raise ValueError("source has no transcript version")
        segments = list(
            await session.scalars(
                select(SourceSegment)
                .where(SourceSegment.source_version_id == source_version.id)
                .order_by(SourceSegment.sequence)
            )
        )
        if not segments:
            raise ValueError("source has no transcript segments")
        return source, source_version, segments

    async def _persist_sections(
        self,
        session: AsyncSession,
        structure: SpeechStructure,
        proposed: Sequence[ProposedSection],
    ) -> None:
        ids = {item.key: uuid4() for item in proposed}
        by_key = {item.key: item for item in proposed}
        depths: dict[str, int] = {}

        def depth(key: str) -> int:
            if key in depths:
                return depths[key]
            parent = by_key[key].parent_key
            depths[key] = 1 if parent is None else depth(parent) + 1
            return depths[key]

        for item in proposed:
            depth(item.key)
        roots = [item for item in proposed if item.parent_key is None]
        for index, item in enumerate(roots, start=1):
            session.add(
                SpeechSection(
                    id=ids[item.key],
                    speech_structure_id=structure.id,
                    parent_id=None,
                    root_id=ids[item.key],
                    section_number=str(index),
                    level=1,
                    title=item.title,
                    summary=item.summary,
                    section_role=item.role,
                    sort_order=item.sort_order or index,
                    confidence=item.confidence,
                )
            )
        await session.flush()
        ordered = sorted(
            (item for item in proposed if item.parent_key is not None),
            key=lambda item: depth(item.key),
        )
        child_numbers: dict[str, int] = {}
        for item in ordered:
            parent = by_key[item.parent_key or ""]
            child_numbers[item.parent_key or ""] = (
                child_numbers.get(item.parent_key or "", 0) + 1
            )
            parent_row = await session.scalar(
                select(SpeechSection).where(SpeechSection.id == ids[parent.key])
            )
            if parent_row is None:
                raise ValueError("parent section was not persisted")
            parent_number = parent_row.section_number
            number = f"{parent_number}.{child_numbers[item.parent_key or '']}"
            session.add(
                SpeechSection(
                    id=ids[item.key],
                    speech_structure_id=structure.id,
                    parent_id=ids[parent.key],
                    root_id=ids[parent.key]
                    if parent.parent_key is None
                    else ids[self._root_key(parent.key, by_key)],
                    section_number=number,
                    level=depth(item.key),
                    title=item.title,
                    summary=item.summary,
                    section_role=item.role,
                    sort_order=item.sort_order or child_numbers[item.parent_key or ""],
                    confidence=item.confidence,
                )
            )
        await session.flush()
        segment_to_primary: set[UUID] = set()
        sequence = 0
        for item in proposed:
            for segment_id in item.segment_ids:
                relation = (
                    SegmentRelation.PRIMARY.value
                    if segment_id not in segment_to_primary
                    else SegmentRelation.SUPPORTING.value
                )
                if relation == SegmentRelation.PRIMARY.value:
                    segment_to_primary.add(segment_id)
                sequence += 1
                session.add(
                    SpeechSectionSegment(
                        section_id=ids[item.key],
                        source_segment_id=segment_id,
                        sequence=sequence,
                        relation_type=relation,
                        confidence=item.confidence,
                    )
                )

    @staticmethod
    def _root_key(key: str, by_key: dict[str, ProposedSection]) -> str:
        current = by_key[key]
        while current.parent_key is not None:
            current = by_key[current.parent_key]
        return current.key

    async def _supersede_previous(
        self, session: AsyncSession, source_id: UUID, current_id: UUID
    ) -> None:
        previous = list(
            await session.scalars(
                select(SpeechStructure).where(
                    SpeechStructure.source_id == source_id,
                    SpeechStructure.id != current_id,
                    SpeechStructure.status == StructureStatus.READY.value,
                )
            )
        )
        for item in previous:
            item.status = StructureStatus.SUPERSEDED.value
