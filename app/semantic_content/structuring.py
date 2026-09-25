"""Build hierarchical semantic trees from immutable transcript segments."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.knowledge.models import Source, SourceSegment, SourceVersion
from app.semantic_content.domain import SemanticNodeKind, SemanticStructureStatus
from app.semantic_content.models import (
    PreferredSemanticStructureRun,
    SemanticNode,
    SemanticNodeSegment,
    SemanticStructureRun,
)
from app.semantic_content.schemas import (
    GlobalOutline,
    GlobalOutlineNode,
    LocalOutline,
    SemanticNodeRead,
    SemanticStructureRequest,
    SemanticStructureRunRead,
    SemanticTreeRead,
)

LOCAL_INSTRUCTIONS = """Structure this transcript window into ordered semantic sections.
Use only ideas supported by the supplied segments. Every node must use exact inclusive
segment sequence numbers. Prefer conceptual boundaries over equal token sizes. Merge
repetition. Do not invent claims, examples, names, or references."""

GLOBAL_INSTRUCTIONS = """Merge the local outlines into one coherent nested agenda for the
whole speech. Preserve source order and exact segment ranges. Remove overlap introduced
by windows. Children must stay inside parent ranges. Prefer 3-8 top-level sections and
create deeper children only when the source genuinely has conceptual substructure."""


class SemanticStructureService:
    """Derive and persist a versioned semantic hierarchy for one transcript."""

    def __init__(self, database: Database, provider: LLMProvider) -> None:
        self._database = database
        self._provider = provider

    async def build(
        self, source_version_id: UUID, request: SemanticStructureRequest
    ) -> SemanticTreeRead:
        async with self._database.transaction() as session:
            version = await session.get(SourceVersion, source_version_id)
            if version is None:
                raise ValueError("source version not found")
            source = await session.get(Source, version.source_id)
            if source is None:
                raise ValueError("source not found")
            segments = list(
                await session.scalars(
                    select(SourceSegment)
                    .where(SourceSegment.source_version_id == source_version_id)
                    .order_by(SourceSegment.sequence)
                )
            )
            if not segments:
                raise ValueError("source version has no transcript segments")
            input_hash = self._input_hash(version, segments, request)
            existing = await session.scalar(
                select(SemanticStructureRun).where(
                    SemanticStructureRun.source_version_id == source_version_id,
                    SemanticStructureRun.input_hash == input_hash,
                    SemanticStructureRun.prompt_version == request.prompt_version,
                    SemanticStructureRun.provider == self._provider.name,
                    SemanticStructureRun.model == request.model,
                    SemanticStructureRun.status
                    == SemanticStructureStatus.SUCCEEDED.value,
                )
            )
            if existing is not None:
                if request.make_preferred:
                    await self._set_preferred(session, source_version_id, existing.id)
                return await self._read(session, existing)
            run = SemanticStructureRun(
                source_version_id=source_version_id,
                input_hash=input_hash,
                prompt_version=request.prompt_version,
                provider=self._provider.name,
                model=request.model,
                configuration={
                    "max_window_characters": request.max_window_characters,
                    "overlap_segments": request.overlap_segments,
                },
                status=SemanticStructureStatus.RUNNING.value,
            )
            session.add(run)
            await session.flush()
            run_id = run.id

        try:
            windows = self._windows(
                segments,
                request.max_window_characters,
                request.overlap_segments,
            )
            local: list[LocalOutline] = []
            for index, window in enumerate(windows, start=1):
                raw = await self._provider.extract(
                    StructuredExtractionRequest(
                        task="semantic-transcript-window",
                        prompt_version=request.prompt_version,
                        model=request.model,
                        instructions=(
                            LOCAL_INSTRUCTIONS
                            + f"\nWindow {index}/{len(windows)}; title: {source.title}"
                        ),
                        input_text=window,
                        output_model=LocalOutline,
                    )
                )
                local.append(LocalOutline.model_validate(raw))
            merge_input = json.dumps(
                {
                    "source_title": source.title,
                    "local_outlines": [item.model_dump(mode="json") for item in local],
                },
                ensure_ascii=False,
            )
            raw_tree = await self._provider.extract(
                StructuredExtractionRequest(
                    task="semantic-transcript-global-tree",
                    prompt_version=request.prompt_version,
                    model=request.model,
                    instructions=GLOBAL_INSTRUCTIONS,
                    input_text=merge_input,
                    output_model=GlobalOutline,
                    timeout_seconds=240,
                )
            )
            outline = GlobalOutline.model_validate(raw_tree)
            self._validate_outline(
                outline, segments[0].sequence, segments[-1].sequence
            )
            async with self._database.transaction() as session:
                run = await session.get(SemanticStructureRun, run_id)
                if run is None:
                    raise RuntimeError("semantic structure run disappeared")
                await self._persist(session, run, outline, segments)
                nodes = list(
                    await session.scalars(
                        select(SemanticNode)
                        .where(SemanticNode.semantic_structure_run_id == run.id)
                        .order_by(SemanticNode.ordinal)
                    )
                )
                run.window_count = len(windows)
                run.node_count = len(nodes)
                run.output_hash = hashlib.sha256(
                    "\n".join(node.content_hash for node in nodes).encode()
                ).hexdigest()
                run.status = SemanticStructureStatus.SUCCEEDED.value
                run.completed_at = datetime.now(UTC)
                if request.make_preferred:
                    await self._set_preferred(session, source_version_id, run.id)
                return await self._read(session, run)
        except Exception as exc:
            async with self._database.transaction() as session:
                failed = await session.get(SemanticStructureRun, run_id)
                if failed is not None:
                    failed.status = SemanticStructureStatus.FAILED.value
                    failed.error_message = f"{type(exc).__name__}: {str(exc)[:1800]}"
                    failed.completed_at = datetime.now(UTC)
            raise

    async def preferred_tree(self, source_version_id: UUID) -> SemanticTreeRead:
        async with self._database.transaction() as session:
            pointer = await session.get(
                PreferredSemanticStructureRun, source_version_id
            )
            if pointer is None:
                raise ValueError("source version has no preferred semantic structure")
            run = await session.get(
                SemanticStructureRun, pointer.semantic_structure_run_id
            )
            if run is None:
                raise RuntimeError("preferred semantic structure run disappeared")
            return await self._read(session, run)

    @staticmethod
    def _input_hash(
        version: SourceVersion,
        segments: list[SourceSegment],
        request: SemanticStructureRequest,
    ) -> str:
        payload = {
            "version": str(version.id),
            "transcript_hash": version.transcript_hash,
            "segment_hashes": [segment.content_hash for segment in segments],
            "max_window_characters": request.max_window_characters,
            "overlap_segments": request.overlap_segments,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def _windows(
        segments: list[SourceSegment], max_chars: int, overlap: int
    ) -> list[str]:
        windows: list[str] = []
        start = 0
        while start < len(segments):
            rendered: list[str] = []
            size = 0
            index = start
            while index < len(segments):
                segment = segments[index]
                line = (
                    f"[S{segment.sequence:06d} "
                    f"{float(segment.start_seconds):.3f}-"
                    f"{float(segment.end_seconds):.3f}] "
                    f"{segment.raw_text.strip()}"
                )
                if rendered and size + len(line) > max_chars:
                    break
                rendered.append(line)
                size += len(line)
                index += 1
            windows.append("\n".join(rendered))
            if index >= len(segments):
                break
            start = max(start + 1, index - overlap)
        return windows

    @staticmethod
    def _validate_outline(
        outline: GlobalOutline, minimum: int, maximum: int
    ) -> None:
        if not outline.sections:
            raise ValueError("global semantic outline has no sections")

        def visit(node: GlobalOutlineNode, parent: GlobalOutlineNode | None) -> None:
            if node.start_sequence > node.end_sequence:
                raise ValueError("semantic node has reversed source range")
            if node.start_sequence < minimum or node.end_sequence > maximum:
                raise ValueError("semantic node range is outside transcript")
            if parent is not None and (
                node.start_sequence < parent.start_sequence
                or node.end_sequence > parent.end_sequence
            ):
                raise ValueError("semantic child range escapes parent range")
            for child in node.children:
                visit(child, node)

        previous_end = minimum - 1
        for section in outline.sections:
            if section.start_sequence <= previous_end:
                raise ValueError("top-level semantic sections are not source ordered")
            visit(section, None)
            previous_end = section.end_sequence

    async def _persist(
        self,
        session: AsyncSession,
        run: SemanticStructureRun,
        outline: GlobalOutline,
        segments: list[SourceSegment],
    ) -> None:
        by_sequence = {segment.sequence: segment for segment in segments}
        ordinal = 0

        async def add_node(
            node: GlobalOutlineNode,
            path: str,
            depth: int,
            parent_id: UUID | None,
        ) -> None:
            nonlocal ordinal
            ordinal += 1
            selected = [
                by_sequence[seq]
                for seq in range(node.start_sequence, node.end_sequence + 1)
                if seq in by_sequence
            ]
            if not selected:
                raise ValueError(f"semantic node {path} has no source segments")
            content_hash = hashlib.sha256(
                json.dumps(
                    {
                        "path": path,
                        "title": node.title,
                        "summary": node.summary,
                        "main_idea": node.main_idea,
                        "segments": [item.content_hash for item in selected],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            kind = (
                SemanticNodeKind.SECTION
                if depth == 1
                else SemanticNodeKind.SUBSECTION
                if depth == 2
                else SemanticNodeKind.DETAIL
            )
            row = SemanticNode(
                semantic_structure_run_id=run.id,
                parent_id=parent_id,
                path=path,
                depth=depth,
                ordinal=ordinal,
                node_kind=kind.value,
                title=node.title.strip(),
                summary=node.summary.strip(),
                main_idea=node.main_idea.strip(),
                claims=node.claims,
                definitions=node.definitions,
                examples=node.examples,
                qualifications=node.qualifications,
                start_sequence=node.start_sequence,
                end_sequence=node.end_sequence,
                start_seconds=float(selected[0].start_seconds),
                end_seconds=float(selected[-1].end_seconds),
                content_hash=content_hash,
            )
            session.add(row)
            await session.flush()
            session.add_all(
                [
                    SemanticNodeSegment(
                        semantic_node_id=row.id,
                        source_segment_id=segment.id,
                        position=position,
                    )
                    for position, segment in enumerate(selected, start=1)
                ]
            )
            for child_index, child in enumerate(node.children, start=1):
                await add_node(
                    child,
                    f"{path}.{child_index}",
                    depth + 1,
                    row.id,
                )

        for section_index, section in enumerate(outline.sections, start=1):
            await add_node(section, str(section_index), 1, None)

    @staticmethod
    async def _set_preferred(
        session: AsyncSession, source_version_id: UUID, run_id: UUID
    ) -> None:
        pointer = await session.get(
            PreferredSemanticStructureRun, source_version_id
        )
        if pointer is None:
            session.add(
                PreferredSemanticStructureRun(
                    source_version_id=source_version_id,
                    semantic_structure_run_id=run_id,
                )
            )
        else:
            pointer.semantic_structure_run_id = run_id
            pointer.selected_at = datetime.now(UTC)

    @staticmethod
    async def _read(
        session: AsyncSession, run: SemanticStructureRun
    ) -> SemanticTreeRead:
        nodes = list(
            await session.scalars(
                select(SemanticNode)
                .where(SemanticNode.semantic_structure_run_id == run.id)
                .order_by(SemanticNode.ordinal)
            )
        )
        return SemanticTreeRead(
            run=SemanticStructureRunRead.model_validate(run),
            nodes=[SemanticNodeRead.model_validate(node) for node in nodes],
        )
