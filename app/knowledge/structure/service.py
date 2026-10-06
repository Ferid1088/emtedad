"""Source structure extraction service.

Turns an ingested transcript into a validated hierarchical node tree. Runs are
idempotent via ``ExtractionRun`` dedup keys
(source_version_id + provider + model + prompt_version + configuration_hash).
"""

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.knowledge.domain import RunStatus
from app.knowledge.llm.base import LLMProvider
from app.knowledge.llm.factory import resolve_llm_provider
from app.knowledge.llm.roles import AgentRole
from app.knowledge.models import ExtractionRun, Source, SourceSegment
from app.knowledge.structure.agent import SourceStructureAgent
from app.knowledge.structure.domain import (
    LOCAL_PASS_PROMPT_VERSION,
    MERGE_PASS_PROMPT_VERSION,
    STRUCTURE_TASK,
    FailureClass,
    SourceProcessingStatus,
    classify_failure,
)
from app.knowledge.structure.models import (
    SourceProcessingState,
    SourceStructureNode,
)
from app.knowledge.structure.repository import SourceStructureRepository
from app.knowledge.structure.schemas import (
    SourceStructureOutput,
    StructureValidationReport,
)
from app.knowledge.structure.validator import (
    SourceStructureValidator,
    StagedNode,
)

logger = logging.getLogger(__name__)


class SourceStructureService:
    """Builds and validates the structure tree for one source version."""

    def __init__(
        self,
        database: Database,
        provider: LLMProvider | None = None,
        *,
        model: str = "configured-default",
        window_size: int = 120,
        overlap: int = 16,
    ) -> None:
        self.database = database
        self.provider = provider or resolve_llm_provider(role=AgentRole.LEGACY_DEFAULT)
        self.model = model
        self.window_size = window_size
        self.overlap = overlap

    async def mark_ingested(self, source_id: UUID) -> SourceProcessingState:
        async with self.database.transaction() as session:
            repo = SourceStructureRepository(session)
            source = await session.get(Source, source_id)
            if source is None:
                raise ValueError("source not found")
            version = await repo.latest_version(source_id)
            state = await repo.ensure_processing_state(
                source, version.id if version else None
            )
            if state.status == SourceProcessingStatus.FAILED or version is None:
                state.status = SourceProcessingStatus.INGESTED
            else:
                state.status = SourceProcessingStatus.STRUCTURE_PENDING
            return state

    async def process_source(
        self,
        source_id: UUID,
        *,
        force: bool = False,
        on_progress: Callable[[str], None] | None = None,
    ) -> SourceProcessingState:
        """Extract + persist the structure tree for the source's latest version."""

        async with self.database.transaction() as session:
            repo = SourceStructureRepository(session)
            source = await session.get(Source, source_id)
            if source is None:
                raise ValueError("source not found")
            version = await repo.latest_version(source_id)
            state = await repo.ensure_processing_state(
                source, version.id if version else None
            )
            if version is None:
                state.status = SourceProcessingStatus.INGESTED
                return state
            segments = await repo.segments(version.id)
            if not segments:
                state.status = SourceProcessingStatus.INGESTED
                return state

            provider_name = getattr(self.provider, "name", type(self.provider).__name__)
            configuration = {
                "window_size": self.window_size,
                "overlap": self.overlap,
                "prompt_versions": [
                    LOCAL_PASS_PROMPT_VERSION,
                    MERGE_PASS_PROMPT_VERSION,
                ],
            }
            config_hash = self._configuration_hash(version.id, configuration, segments)
            existing = await session.scalar(
                select(ExtractionRun).where(
                    ExtractionRun.source_version_id == version.id,
                    ExtractionRun.task == STRUCTURE_TASK,
                    ExtractionRun.provider == provider_name,
                    ExtractionRun.model == self.model,
                    ExtractionRun.prompt_version
                    == f"{LOCAL_PASS_PROMPT_VERSION}+{MERGE_PASS_PROMPT_VERSION}",
                    ExtractionRun.configuration_hash == config_hash,
                )
            )
            if (
                existing is not None
                and existing.status == RunStatus.SUCCEEDED
                and not force
            ):
                if state.status not in {
                    SourceProcessingStatus.READY,
                    SourceProcessingStatus.UNIT_EXTRACTION_PENDING,
                    SourceProcessingStatus.UNIT_EXTRACTING,
                    SourceProcessingStatus.UNIT_REVIEW_REQUIRED,
                }:
                    state.status = SourceProcessingStatus.STRUCTURED
                return state

            state.source_version_id = version.id
            state.status = SourceProcessingStatus.STRUCTURING
            state.last_error = None
            await session.flush()

            if existing is not None:
                # Retry/force reuses the dedup-keyed run row; the unique key
                # forbids a second row for identical inputs.
                run = existing
                run.status = RunStatus.RUNNING
                run.completed_at = None
            else:
                run = ExtractionRun(
                    source_version_id=version.id,
                    task=STRUCTURE_TASK,
                    provider=provider_name,
                    model=self.model,
                    prompt_version=(
                        f"{LOCAL_PASS_PROMPT_VERSION}+{MERGE_PASS_PROMPT_VERSION}"
                    ),
                    configuration=configuration,
                    configuration_hash=config_hash,
                    window_size=self.window_size,
                    overlap=self.overlap,
                    status=RunStatus.RUNNING,
                )
                session.add(run)
            await session.flush()

            try:
                output = await SourceStructureAgent(
                    self.provider,
                    model=self.model,
                    window_size=self.window_size,
                    overlap=self.overlap,
                ).propose(segments, on_progress=on_progress)
                staged, stage_errors = self._stage(output, segments)
                report = SourceStructureValidator().validate(
                    staged, [segment.sequence for segment in segments]
                )
                report.errors.extend(stage_errors)
                if not report.valid:
                    run.status = RunStatus.FAILED
                    run.completed_at = datetime.now(UTC)
                    state.status = SourceProcessingStatus.STRUCTURE_REVIEW_REQUIRED
                    state.last_error = "; ".join(report.errors[:10])
                    state.attempt_count += 1
                    return state
                await repo.replace_nodes(version.id)
                await self._persist(session, staged, run)
                run.status = RunStatus.SUCCEEDED
                run.completed_at = datetime.now(UTC)
                state.status = SourceProcessingStatus.STRUCTURED
                state.attempt_count = 0
                if report.warnings:
                    state.last_error = "; ".join(report.warnings[:10])
                logger.info(
                    "source_structure.structured",
                    extra={
                        "source_id": str(source_id),
                        "source_version_id": str(version.id),
                        "nodes": report.node_count,
                        "coverage": report.coverage_percent,
                    },
                )
                return state
            except Exception as exc:
                run.status = RunStatus.FAILED
                run.completed_at = datetime.now(UTC)
                state.status = SourceProcessingStatus.FAILED
                state.last_error = str(exc)[:2000]
                # Quota/rate-limit failures stay retryable and must not
                # burn a real attempt — only analysis failures count.
                if classify_failure(state.last_error) is FailureClass.FAILED:
                    state.attempt_count += 1
                logger.exception(
                    "source_structure.failed",
                    extra={"source_id": str(source_id)},
                )
                return state

    async def validate_stored(
        self, source_version_id: UUID
    ) -> StructureValidationReport:
        """Re-run all structural rules against persisted nodes."""

        async with self.database.transaction() as session:
            repo = SourceStructureRepository(session)
            nodes = await repo.nodes(source_version_id)
            segments = await repo.segments(source_version_id)
            seq_by_id = {segment.id: segment.sequence for segment in segments}
            staged = [
                StagedNode(
                    temp_id=str(node.id),
                    parent_temp_id=(str(node.parent_id) if node.parent_id else None),
                    node_type=node.node_type,
                    title=node.title,
                    summary=node.summary,
                    start_segment_id=node.start_segment_id,
                    end_segment_id=node.end_segment_id,
                    start_sequence=seq_by_id.get(node.start_segment_id, 0),
                    end_sequence=seq_by_id.get(node.end_segment_id, 0),
                    start_seconds=node.start_seconds,
                    end_seconds=node.end_seconds,
                    ordinal=node.ordinal,
                    confidence=node.confidence or 0.0,
                    level=node.level,
                )
                for node in nodes
            ]
            return SourceStructureValidator().validate(staged, list(seq_by_id.values()))

    async def get_tree(self, source_version_id: UUID) -> list[dict[str, object]]:
        async with self.database.transaction() as session:
            repo = SourceStructureRepository(session)
            return repo.build_tree(await repo.nodes(source_version_id))

    async def get_node_detail(
        self, node_id: UUID
    ) -> tuple[SourceStructureNode, list[SourceSegment]] | None:
        async with self.database.transaction() as session:
            repo = SourceStructureRepository(session)
            node = await repo.node(node_id)
            if node is None:
                return None
            return node, await repo.node_segments(node)

    @staticmethod
    def _configuration_hash(
        source_version_id: UUID,
        configuration: dict[str, object],
        segments: list[SourceSegment],
    ) -> str:
        payload = {
            "source_version_id": str(source_version_id),
            "segments": [
                (str(segment.id), segment.content_hash) for segment in segments
            ],
            "configuration": configuration,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _stage(
        output: SourceStructureOutput, segments: list[SourceSegment]
    ) -> tuple[list[StagedNode], list[str]]:
        by_sequence = {segment.sequence: segment for segment in segments}
        errors: list[str] = []
        staged: list[StagedNode] = []
        for node in output.nodes:
            start = by_sequence.get(node.start_segment_sequence)
            end = by_sequence.get(node.end_segment_sequence)
            if start is None or end is None:
                errors.append(
                    f"node {node.temp_id}: segment sequence "
                    f"{node.start_segment_sequence}-"
                    f"{node.end_segment_sequence} not in source version"
                )
            staged.append(
                StagedNode(
                    temp_id=node.temp_id,
                    parent_temp_id=node.parent_temp_id,
                    node_type=node.node_type,
                    title=node.title,
                    summary=node.summary,
                    start_segment_id=start.id if start else None,
                    end_segment_id=end.id if end else None,
                    start_sequence=node.start_segment_sequence,
                    end_sequence=node.end_segment_sequence,
                    start_seconds=start.start_seconds if start else None,
                    end_seconds=end.end_seconds if end else None,
                    ordinal=node.ordinal,
                    confidence=node.confidence,
                )
            )
        return staged, errors

    async def _persist(
        self,
        session: AsyncSession,
        staged: list[StagedNode],
        run: ExtractionRun,
    ) -> None:
        ids: dict[str, UUID] = {}
        pending = list(staged)
        level_by_temp: dict[str, int] = {}
        while pending:
            progress = False
            for node in list(pending):
                parent = node.parent_temp_id
                if parent is None or parent in ids:
                    level = 1 if parent is None else level_by_temp[parent] + 1
                    new_id = uuid4()
                    session.add(
                        SourceStructureNode(
                            id=new_id,
                            source_version_id=run.source_version_id,
                            parent_id=ids.get(parent) if parent else None,
                            level=level,
                            ordinal=node.ordinal,
                            node_type=node.node_type,
                            title=node.title,
                            summary=node.summary,
                            start_segment_id=node.start_segment_id,
                            end_segment_id=node.end_segment_id,
                            start_seconds=node.start_seconds,
                            end_seconds=node.end_seconds,
                            confidence=node.confidence,
                            extraction_run_id=run.id,
                            metadata_json={},
                        )
                    )
                    ids[node.temp_id] = new_id
                    level_by_temp[node.temp_id] = level
                    pending.remove(node)
                    progress = True
            if not progress:
                raise ValueError("structure hierarchy contains a cycle")
        await session.flush()
