"""Integration coverage for source structure extraction (Phase 4)."""

import hashlib
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from alembic import command
from app.db.session import Database
from app.knowledge.domain import IngestionStatus, RunStatus, SourceType
from app.knowledge.models import (
    ExtractionRun,
    Source,
    SourceSegment,
    SourceVersion,
)
from app.knowledge.structure.domain import (
    SourceProcessingStatus,
    StructureNodeType,
)
from app.knowledge.structure.models import (
    SourceProcessingState,
    SourceStructureNode,
)
from app.knowledge.structure.schemas import (
    SourceStructureOutput,
    StructureNodeProposal,
)
from app.knowledge.structure.service import SourceStructureService

pytestmark = pytest.mark.integration


def _database_url() -> str:
    try:
        return os.environ["EMTEDAD_DATABASE_URL"]
    except KeyError as exc:
        raise RuntimeError(
            "EMTEDAD_DATABASE_URL is required for integration tests"
        ) from exc


def _sync_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def migrated_database_url() -> Iterator[str]:
    base_url = _database_url()
    name = f"emtedad_test_{uuid4().hex}"
    admin_url = _sync_url(
        make_url(base_url)
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


async def _create_transcript_source(database: Database) -> Source:
    async with database.transaction() as session:
        source = Source(
            source_type=SourceType.YOUTUBE_VIDEO,
            platform="youtube",
            external_id=f"struct{uuid4().hex[:8]}",
            canonical_url="https://example.test/video",
            title="Structure fixture",
            language="en",
            ingestion_status=IngestionStatus.INGESTED,
        )
        session.add(source)
        await session.flush()
        version = SourceVersion(
            source_id=source.id,
            content_hash=hashlib.sha256(b"content").hexdigest(),
            transcript_hash=hashlib.sha256(b"transcript").hexdigest(),
            acquisition_tool="fixture",
            acquisition_version="0",
            normalization_version="0",
            acquired_at=datetime.now(UTC),
        )
        session.add(version)
        await session.flush()
        for index in range(1, 11):
            session.add(
                SourceSegment(
                    source_version_id=version.id,
                    sequence=index,
                    start_seconds=Decimal(index * 10),
                    end_seconds=Decimal(index * 10 + 9),
                    raw_text=f"segment {index} of the transcript",
                    normalized_text=f"segment {index} of the transcript",
                    language="en",
                    content_hash=hashlib.sha256(f"seg{index}".encode()).hexdigest(),
                )
            )
        await session.flush()
        return source


class _TreeProvider:
    """Returns one nested hierarchy: topic(1-10) -> story(3-8)."""

    name = "fixture"

    async def extract(self, request):
        return SourceStructureOutput(
            nodes=[
                StructureNodeProposal(
                    temp_id="t1",
                    node_type=StructureNodeType.TOPIC,
                    title="Main topic",
                    summary="The whole talk",
                    start_segment_sequence=1,
                    end_segment_sequence=10,
                    ordinal=1,
                ),
                StructureNodeProposal(
                    temp_id="s1",
                    parent_temp_id="t1",
                    node_type=StructureNodeType.STORY,
                    title="Long story",
                    summary="A complete narrative arc",
                    start_segment_sequence=3,
                    end_segment_sequence=8,
                    ordinal=1,
                ),
            ]
        )


@pytest.mark.asyncio
async def test_process_source_builds_and_validates_tree(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        source = await _create_transcript_source(database)
        service = SourceStructureService(database, provider=_TreeProvider())
        state = await service.mark_ingested(source.id)
        assert state.status is SourceProcessingStatus.STRUCTURE_PENDING

        state = await service.process_source(source.id)
        assert state.status is SourceProcessingStatus.STRUCTURED

        async with database.transaction() as session:
            nodes = list(
                await session.scalars(
                    select(SourceStructureNode).order_by(
                        SourceStructureNode.level, SourceStructureNode.ordinal
                    )
                )
            )
            run = await session.scalar(select(ExtractionRun))
        assert len(nodes) == 2
        story = next(
            item for item in nodes if item.node_type is StructureNodeType.STORY
        )
        topic = next(
            item for item in nodes if item.node_type is StructureNodeType.TOPIC
        )
        assert story.parent_id == topic.id
        assert story.level == 2
        assert story.extraction_run_id == run.id
        assert run.status is RunStatus.SUCCEEDED

        # Node detail resolves the full transcript span.
        detail = await service.get_node_detail(story.id)
        assert detail is not None
        node, segments = detail
        assert [segment.sequence for segment in segments] == list(range(3, 9))

        # Stored tree passes validation and builds a nested tree.
        version = node.source_version_id
        report = await service.validate_stored(version)
        assert report.valid
        tree = await service.get_tree(version)
        assert tree[0]["children"][0]["node_type"] == "STORY"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_process_source_is_idempotent(migrated_database_url: str) -> None:
    database = Database(migrated_database_url)
    try:
        source = await _create_transcript_source(database)
        provider = _TreeProvider()
        service = SourceStructureService(database, provider=provider)
        await service.mark_ingested(source.id)
        await service.process_source(source.id)
        await service.process_source(source.id)
        async with database.transaction() as session:
            node_count = await session.scalar(
                select(func.count(SourceStructureNode.id))
            )
            run_count = await session.scalar(
                select(func.count(ExtractionRun.id)).where(
                    ExtractionRun.status == RunStatus.SUCCEEDED
                )
            )
            states = list(await session.scalars(select(SourceProcessingState)))
        assert node_count == 2
        assert run_count == 1
        assert states[0].status is SourceProcessingStatus.STRUCTURED
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_invalid_structure_marks_review_required(
    migrated_database_url: str,
) -> None:
    class _BadProvider:
        name = "fixture"

        async def extract(self, request):
            return SourceStructureOutput(
                nodes=[
                    StructureNodeProposal(
                        temp_id="a",
                        title="Parent",
                        summary="x",
                        start_segment_sequence=1,
                        end_segment_sequence=5,
                        ordinal=1,
                    ),
                    StructureNodeProposal(
                        temp_id="b",
                        parent_temp_id="a",
                        title="Child escapes",
                        summary="x",
                        start_segment_sequence=4,
                        end_segment_sequence=9,
                        ordinal=1,
                    ),
                ]
            )

    database = Database(migrated_database_url)
    try:
        source = await _create_transcript_source(database)
        service = SourceStructureService(database, provider=_BadProvider())
        state = await service.process_source(source.id)
        assert state.status is SourceProcessingStatus.STRUCTURE_REVIEW_REQUIRED
        assert state.last_error
        async with database.transaction() as session:
            count = await session.scalar(select(func.count(SourceStructureNode.id)))
        assert count == 0
    finally:
        await database.dispose()
