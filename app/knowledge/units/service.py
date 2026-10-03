"""Knowledge Unit extraction service.

Derives atomic units from the persisted structure tree. Full text is always
reconstructed from the ordered source segments — LLM output only supplies
metadata (unit type, title, summary, evidence level, claim type).
"""

import hashlib
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, or_, select

from app.db.session import Database
from app.knowledge.domain import RunStatus
from app.knowledge.llm.base import LLMProvider
from app.knowledge.llm.factory import resolve_llm_provider
from app.knowledge.models import (
    ExtractionRun,
    Source,
    SourceSegment,
)
from app.knowledge.structure.domain import SourceProcessingStatus
from app.knowledge.structure.models import (
    SourceProcessingState,
    SourceStructureNode,
)
from app.knowledge.structure.repository import SourceStructureRepository
from app.knowledge.units.domain import (
    ATOMIC_UNIT_TYPES,
    UNIT_EXTRACTION_TASK,
    UNIT_EXTRACTION_VERSION,
    UNIT_PROMPT_VERSION,
    ClaimType,
    EvidenceLevel,
    default_unit_type,
    node_is_unit_eligible,
)
from app.knowledge.units.extractor import KnowledgeUnitExtractor
from app.knowledge.units.models import KnowledgeUnit
from app.knowledge.units.schemas import UnitMetadataProposal
from app.knowledge.units.validator import (
    KnowledgeUnitValidator,
    StagedUnit,
)

logger = logging.getLogger(__name__)


class KnowledgeUnitService:
    def __init__(
        self,
        database: Database,
        provider: LLMProvider | None = None,
        *,
        model: str = "configured-default",
        batch_size: int = 10,
    ) -> None:
        self.database = database
        self.provider = provider or resolve_llm_provider()
        self.model = model
        self.batch_size = batch_size

    async def extract_for_source(
        self, source_id: UUID, *, force: bool = False
    ) -> SourceProcessingState:
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
            nodes = await repo.nodes(version.id)
            segments = await repo.segments(version.id)
            if not nodes or not segments:
                state.status = SourceProcessingStatus.STRUCTURE_PENDING
                return state

            eligible = self._eligible(nodes)
            configuration = {
                "extraction_version": UNIT_EXTRACTION_VERSION,
                "batch_size": self.batch_size,
                "prompt_version": UNIT_PROMPT_VERSION,
            }
            provider_name = getattr(self.provider, "name", type(self.provider).__name__)
            config_hash = self._configuration_hash(version.id, configuration, segments)
            existing = await session.scalar(
                select(ExtractionRun).where(
                    ExtractionRun.source_version_id == version.id,
                    ExtractionRun.task == UNIT_EXTRACTION_TASK,
                    ExtractionRun.provider == provider_name,
                    ExtractionRun.model == self.model,
                    ExtractionRun.prompt_version == UNIT_PROMPT_VERSION,
                    ExtractionRun.configuration_hash == config_hash,
                )
            )
            if (
                existing is not None
                and existing.status == RunStatus.SUCCEEDED
                and not force
            ):
                state.status = SourceProcessingStatus.READY
                return state

            state.status = SourceProcessingStatus.UNIT_EXTRACTING
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
                    task=UNIT_EXTRACTION_TASK,
                    provider=provider_name,
                    model=self.model,
                    prompt_version=UNIT_PROMPT_VERSION,
                    configuration=configuration,
                    configuration_hash=config_hash,
                    window_size=self.batch_size,
                    overlap=0,
                    status=RunStatus.RUNNING,
                )
                session.add(run)
            await session.flush()

            try:
                proposals = await KnowledgeUnitExtractor(
                    self.provider,
                    model=self.model,
                    batch_size=self.batch_size,
                ).propose(
                    eligible,
                    {
                        segment.id: segment
                        for segment in sorted(segments, key=lambda item: item.sequence)
                    },
                )
                staged = [
                    self._stage_unit(node, segments, proposals.get(str(node.id)))
                    for node in eligible
                ]
                report = KnowledgeUnitValidator().validate(staged)
                if not report.valid:
                    run.status = RunStatus.FAILED
                    run.completed_at = datetime.now(UTC)
                    state.status = SourceProcessingStatus.UNIT_REVIEW_REQUIRED
                    state.last_error = "; ".join(report.errors[:10])
                    state.attempt_count += 1
                    return state
                if force:
                    await session.execute(
                        delete(KnowledgeUnit).where(
                            KnowledgeUnit.source_version_id == version.id
                        )
                    )
                    await session.flush()
                for unit in staged:
                    session.add(
                        KnowledgeUnit(
                            source_version_id=version.id,
                            structure_node_id=unit.structure_node_id,
                            unit_type=unit.unit_type,
                            title=unit.title,
                            summary=unit.summary,
                            full_text=unit.full_text,
                            start_segment_id=unit.start_segment_id,
                            end_segment_id=unit.end_segment_id,
                            atomic=unit.atomic,
                            evidence_level=unit.evidence_level,
                            claim_type=unit.claim_type,
                            content_hash=unit.content_hash,
                            extraction_version=UNIT_EXTRACTION_VERSION,
                            extraction_run_id=run.id,
                            metadata_json={"node_id": str(unit.structure_node_id)},
                        )
                    )
                run.status = RunStatus.SUCCEEDED
                run.completed_at = datetime.now(UTC)
                state.status = SourceProcessingStatus.READY
                state.attempt_count = 0
                logger.info(
                    "knowledge_units.extracted",
                    extra={
                        "source_id": str(source_id),
                        "units": len(staged),
                    },
                )
                return state
            except Exception as exc:
                run.status = RunStatus.FAILED
                run.completed_at = datetime.now(UTC)
                state.status = SourceProcessingStatus.FAILED
                state.last_error = str(exc)[:2000]
                state.attempt_count += 1
                logger.exception(
                    "knowledge_units.failed",
                    extra={"source_id": str(source_id)},
                )
                return state

    async def list_units(
        self, source_version_id: UUID, query: str | None = None
    ) -> list[KnowledgeUnit]:
        async with self.database.transaction() as session:
            statement = (
                select(KnowledgeUnit)
                .where(KnowledgeUnit.source_version_id == source_version_id)
                .order_by(KnowledgeUnit.created_at, KnowledgeUnit.title)
            )
            if query:
                like = f"%{query}%"
                statement = statement.where(
                    or_(
                        KnowledgeUnit.title.ilike(like),
                        KnowledgeUnit.summary.ilike(like),
                        KnowledgeUnit.full_text.ilike(like),
                    )
                )
            return list(await session.scalars(statement))

    @staticmethod
    def _eligible(
        nodes: Sequence[SourceStructureNode],
    ) -> list[SourceStructureNode]:
        children = {node.parent_id for node in nodes if node.parent_id is not None}
        return [
            node
            for node in nodes
            if node_is_unit_eligible(node.node_type, has_children=node.id in children)
        ]

    @staticmethod
    def _stage_unit(
        node: SourceStructureNode,
        segments: list[SourceSegment],
        proposal: UnitMetadataProposal | None,
    ) -> StagedUnit:
        by_id = {segment.id: segment for segment in segments}
        start = by_id.get(node.start_segment_id)
        end = by_id.get(node.end_segment_id)
        span = [
            segment
            for segment in segments
            if start is not None
            and end is not None
            and start.sequence <= segment.sequence <= end.sequence
        ]
        full_text = "\n".join(segment.normalized_text for segment in span)
        unit_type = (
            proposal.unit_type
            if proposal is not None
            else default_unit_type(node.node_type)
        )
        return StagedUnit(
            structure_node_id=node.id,
            node_version_id=node.source_version_id,
            source_version_id=node.source_version_id,
            unit_type=unit_type,
            title=proposal.title if proposal is not None else node.title,
            summary=(proposal.summary if proposal is not None else node.summary),
            full_text=full_text,
            start_segment_id=node.start_segment_id,
            end_segment_id=node.end_segment_id,
            start_sequence=start.sequence if start else 0,
            end_sequence=end.sequence if end else 0,
            atomic=unit_type in ATOMIC_UNIT_TYPES,
            evidence_level=(
                proposal.evidence_level if proposal is not None else EvidenceLevel.NONE
            ),
            claim_type=(
                proposal.claim_type if proposal is not None else ClaimType.UNKNOWN
            ),
            content_hash=hashlib.sha256(full_text.encode()).hexdigest(),
        )

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
