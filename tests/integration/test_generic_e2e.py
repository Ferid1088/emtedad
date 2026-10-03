"""Phase 21 E2E: YouTube fixture → generic ContentBrief production → ScriptDraft.

This is the strongest Phase 21 gate: the whole resource-first chain runs
without creating or requiring a LessonCanon/LessonContentPackage, and the
canonical ``knowledge/structure`` pipeline is the only structure system in
play. Retrying a failed structure run must reuse the dedup-keyed
ExtractionRun and must not duplicate the hierarchy.
"""

import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from alembic import command
from app.briefs.service import BriefInput, BriefService
from app.content_engine.review import ScriptService
from app.content_engine.service import ContentEngineService
from app.db.session import Database
from app.editorial_channels.domain import ChannelResourceRole
from app.editorial_channels.service import EditorialChannelService
from app.knowledge.adapters.base import (
    ExternalSourceSnapshot,
    TranscriptEntry,
)
from app.knowledge.domain import RunStatus, SourceType
from app.knowledge.extraction_schema import WindowExtraction
from app.knowledge.importer import ExternalKnowledgeImporter
from app.knowledge.models import ExtractionRun, Source, SourceSegment
from app.knowledge.processing import SourceProcessingService
from app.knowledge.structure.domain import SourceProcessingStatus
from app.knowledge.structure.models import (
    SourceProcessingState,
    SourceStructureNode,
)
from app.knowledge.structure.service import SourceStructureService
from app.lecture.domain import MasterOriginType, MasterStatus
from app.research.generic import GenericResearchService
from app.research.models import EvidenceMatrixItem, ResearchPackage
from app.topics.service import TopicService
from tests.integration.test_topics import _Provider

pytestmark = pytest.mark.integration


def _database_url() -> str:
    try:
        return os.environ["EMTEDAD_DATABASE_URL"]
    except KeyError as exc:
        raise RuntimeError(
            "EMTEDAD_DATABASE_URL is required for integration tests"
        ) from exc


@pytest.fixture
def migrated_database_url() -> Iterator[str]:
    base_url = _database_url()
    name = f"emtedad_test_{uuid4().hex}"
    admin_url = (
        make_url(base_url.replace("postgresql+psycopg://", "postgresql://", 1))
        .set(database="postgres")
        .render_as_string(hide_password=False)
    )
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = make_url(base_url).set(database=name).render_as_string(hide_password=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        yield url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


class _E2EProvider(_Provider):
    """test_topics provider plus the importer's window-extraction task."""

    name = "fixture"

    async def extract(self, request):
        if request.task == "external-knowledge-extraction":
            return WindowExtraction(mentions=[], claims=[])
        return await super().extract(request)


class _YouTubeFixtureAdapter:
    """Serves one immutable transcript snapshot like a YouTube import."""

    def __init__(self) -> None:
        self.snapshot = ExternalSourceSnapshot(
            source_type=SourceType.YOUTUBE_VIDEO,
            platform="youtube",
            external_id=f"e2e{uuid4().hex[:8]}",
            canonical_url="https://youtube.com/watch?v=e2e-fixture",
            title="Why we stick with losing choices",
            description="A talk about sunk cost.",
            language="en",
            published_at=None,
            duration_seconds=120,
            channel_external_id="channel-e2e",
            channel_title="E2E Channel",
            channel_url="https://youtube.com/channel/channel-e2e",
            creator_name="Creator",
            transcript_kind="manual",
            metadata={},
            transcript=tuple(
                TranscriptEntry(
                    index,
                    float(index * 10),
                    9.0,
                    f"segment {index} about sunk cost decisions",
                )
                for index in range(1, 11)
            ),
            thumbnail_url=None,
        )

    async def acquire(self, locator: str) -> ExternalSourceSnapshot:
        return self.snapshot


@pytest.mark.asyncio
async def test_full_generic_production_from_youtube_import(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        provider = _E2EProvider()

        # YouTube fixture → Source import → SourceVersion → transcript segments.
        importer = ExternalKnowledgeImporter(
            database, _YouTubeFixtureAdapter(), provider
        )
        result = await importer.ingest("e2e-fixture")
        assert result.segment_count == 10
        async with database.transaction() as session:
            source = await session.get(Source, result.source_id)
            assert source is not None

        # One SourceVersion → one canonical SourceStructure (Vortragsstruktur).
        processing = SourceProcessingService(database, provider=provider)
        await SourceStructureService(database, provider=provider).mark_ingested(
            source.id
        )
        state = await processing.process_source(source.id)
        assert state.status is SourceProcessingStatus.READY

        async with database.transaction() as session:
            nodes = list(
                await session.scalars(
                    select(SourceStructureNode).where(
                        SourceStructureNode.source_version_id
                        == result.source_version_id
                    )
                )
            )
            segments = list(
                await session.scalars(
                    select(SourceSegment).where(
                        SourceSegment.source_version_id == result.source_version_id
                    )
                )
            )
            states = list(await session.scalars(select(SourceProcessingState)))
            runs = list(await session.scalars(select(ExtractionRun)))
        assert len(states) == 1  # one authoritative state machine row
        assert len(nodes) == 2
        # Structure maps to exact SourceSegments.
        segment_ids = {segment.id for segment in segments}
        assert all(
            node.start_segment_id in segment_ids and node.end_segment_id in segment_ids
            for node in nodes
        )
        # One dedup-keyed run each for structure and unit extraction
        # (the importer adds its own external-knowledge-extraction run).
        assert {run.task for run in runs} >= {
            "source_structure",
            "knowledge_units",
        }
        tasks = [run.task for run in runs]
        assert tasks.count("source_structure") == 1
        assert tasks.count("knowledge_units") == 1

        # Retry after failure reuses the run row; the hierarchy is not duped.
        async with database.transaction() as session:
            state_row = await session.get(SourceProcessingState, source.id)
            assert state_row is not None
            state_row.status = SourceProcessingStatus.FAILED
            state_row.last_error = "simulated provider outage"
            failed_run = next(run for run in runs if run.task == "source_structure")
            failed_run.status = RunStatus.FAILED
        await SourceStructureService(database, provider=provider).process_source(
            source.id
        )
        async with database.transaction() as session:
            node_count = await session.scalar(
                select(func.count(SourceStructureNode.id))
            )
            run_count = await session.scalar(
                select(func.count(ExtractionRun.id)).where(
                    ExtractionRun.task == "source_structure"
                )
            )
        assert node_count == 2  # replace_nodes, not append
        assert run_count == 1  # upserted, not duplicated

        # Assign to EditorialChannel → mine topic → select Video Question.
        channel_service = EditorialChannelService(database)
        await channel_service.seed_channels()
        channel = await channel_service.get_channel("emtedad")
        await channel_service.assign_resource(
            channel.id, source.id, role=ChannelResourceRole.PRIMARY
        )
        candidates = await TopicService(database, provider=provider).mine("emtedad")
        candidate = next(c for c in candidates if "bad investments" in c.title)
        assert candidate.video_question is not None

        # ContentBrief → ResearchPackage → EvidenceMatrix → plans → master.
        briefs = BriefService(database)
        brief = await briefs.create_for_candidate(
            candidate.id,
            BriefInput(
                question="Why do we stick with losing choices?",
                thesis="Loss aversion keeps us locked in.",
                target_duration_minutes=10,
            ),
        )
        await briefs.mark_ready(brief.id)
        research = GenericResearchService(database)
        plan = await research.create_plan_for_brief(brief.id)
        matrix = await research.build_evidence_matrix(brief.id)
        await research.freeze_package(plan.id)
        async with database.transaction() as session:
            matrix_item_count = await session.scalar(
                select(func.count(EvidenceMatrixItem.id)).where(
                    EvidenceMatrixItem.evidence_matrix_id == matrix.id
                )
            )
        assert matrix_item_count
        engine = ContentEngineService(database, provider=provider)
        await engine.build_argument(brief.id)
        narrative = await engine.build_narrative(brief.id)

        from app.lecture.generic_service import GenericMasterService

        master = await GenericMasterService(database).build_from_content_brief(brief.id)
        assert master.status == MasterStatus.READY
        assert master.origin_type == MasterOriginType.CONTENT_BRIEF

        # Generic writer → ScriptDraft.
        draft = await ScriptService(database, provider=provider).build_script(
            brief.id, language="en"
        )
        assert draft.lecture_master_version_id == master.id
        assert draft.narrative_plan_id == narrative.id

        # No lesson canon object anywhere in the chain.
        async with database.transaction() as session:
            package = await session.scalar(
                select(ResearchPackage).where(
                    ResearchPackage.content_brief_id == brief.id
                )
            )
            assert package is not None
        assert package.lesson_id is None
        assert package.lesson_canon_hash is None
        assert narrative.id is not None
        payload = master.architecture
        assert "lesson" not in str(payload).lower()
    finally:
        await database.dispose()
