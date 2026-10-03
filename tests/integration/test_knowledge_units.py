"""Integration coverage for Knowledge Unit extraction (Phase 5)."""

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
from app.knowledge.domain import IngestionStatus, SourceType
from app.knowledge.models import Source, SourceSegment, SourceVersion
from app.knowledge.structure.domain import (
    SourceProcessingStatus,
    StructureNodeType,
)
from app.knowledge.structure.models import SourceStructureNode
from app.knowledge.structure.schemas import (
    SourceStructureOutput,
    StructureNodeProposal,
)
from app.knowledge.structure.service import SourceStructureService
from app.knowledge.units.domain import (
    ClaimType,
    EvidenceLevel,
    KnowledgeUnitType,
)
from app.knowledge.units.models import KnowledgeUnit
from app.knowledge.units.schemas import (
    UnitMetadataBatch,
    UnitMetadataProposal,
)
from app.knowledge.units.service import KnowledgeUnitService

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


class _PipelineProvider:
    """Fake provider serving both structure and unit extraction calls."""

    name = "fixture"

    async def extract(self, request):
        if request.task == "source_structure_local":
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
        if request.task == "knowledge_unit_metadata":
            nodes = __import__("json").loads(request.input_text)
            return UnitMetadataBatch(
                units=[
                    UnitMetadataProposal(
                        node_id=item["node_id"],
                        unit_type=(
                            KnowledgeUnitType.STORY
                            if item["node_type"] == "STORY"
                            else KnowledgeUnitType.EXPLANATION
                        ),
                        title=f"Unit {item['title']}",
                        summary="described",
                        evidence_level=EvidenceLevel.ANECDOTAL,
                        claim_type=ClaimType.INTERPRETATION,
                    )
                    for item in nodes
                ]
            )
        raise AssertionError(f"unexpected task: {request.task}")


async def _pipeline(database: Database) -> Source:
    async with database.transaction() as session:
        source = Source(
            source_type=SourceType.YOUTUBE_VIDEO,
            platform="youtube",
            external_id=f"units{uuid4().hex[:8]}",
            canonical_url="https://example.test/video",
            title="Units fixture",
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
                    raw_text=f"segment {index} raw",
                    normalized_text=f"segment {index} normalized",
                    language="en",
                    content_hash=hashlib.sha256(f"seg{index}".encode()).hexdigest(),
                )
            )
        await session.flush()
        return source


@pytest.mark.asyncio
async def test_story_becomes_one_atomic_unit_with_source_text(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        source = await _pipeline(database)
        provider = _PipelineProvider()
        structure = SourceStructureService(database, provider=provider)
        await structure.process_source(source.id)

        units = KnowledgeUnitService(database, provider=provider)
        state = await units.extract_for_source(source.id)
        assert state.status is SourceProcessingStatus.READY

        async with database.transaction() as session:
            rows = list(await session.scalars(select(KnowledgeUnit)))
            story_node = await session.scalar(
                select(SourceStructureNode).where(
                    SourceStructureNode.node_type == StructureNodeType.STORY
                )
            )
        # TOPIC has children -> not eligible; STORY is the only unit.
        assert len(rows) == 1
        unit = rows[0]
        assert unit.unit_type is KnowledgeUnitType.STORY
        assert unit.atomic
        assert unit.structure_node_id == story_node.id
        expected = "\n".join(f"segment {index} normalized" for index in range(3, 9))
        assert unit.full_text == expected
        assert unit.content_hash == hashlib.sha256(expected.encode()).hexdigest()

        # Idempotent: a second run reuses the succeeded extraction run.
        await units.extract_for_source(source.id)
        async with database.transaction() as session:
            count = await session.scalar(select(func.count(KnowledgeUnit.id)))
        assert count == 1
    finally:
        await database.dispose()
