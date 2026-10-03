"""Integration coverage for concept mapping and Knowledge Unit retrieval."""

import hashlib
import os
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import select
from sqlalchemy.engine import make_url

from alembic import command
from app.db.session import Database
from app.knowledge.domain import IngestionStatus, SourceType
from app.knowledge.models import (
    ExternalConcept,
    Source,
    SourceSegment,
    SourceVersion,
)
from app.knowledge.structure.domain import StructureNodeType
from app.knowledge.structure.schemas import (
    SourceStructureOutput,
    StructureNodeProposal,
)
from app.knowledge.structure.service import SourceStructureService
from app.knowledge.units.concepts import ConceptProposal, UnitConceptBatch
from app.knowledge.units.domain import KnowledgeUnitType
from app.knowledge.units.mapping_service import ConceptMappingService
from app.knowledge.units.models import ConceptRelationship
from app.knowledge.units.schemas import (
    UnitMetadataBatch,
    UnitMetadataProposal,
)
from app.knowledge.units.service import KnowledgeUnitService
from app.retrieval.unit_retrieval import (
    ExpansionMode,
    KnowledgeUnitSearchService,
    UnitEmbeddingService,
)

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


class _Provider:
    """Fake provider covering structure, unit metadata, and concepts."""

    name = "fixture"

    async def extract(self, request):
        import json

        if request.task == "source_structure_local":
            return SourceStructureOutput(
                nodes=[
                    StructureNodeProposal(
                        temp_id="t1",
                        node_type=StructureNodeType.TOPIC,
                        title="Decision making",
                        summary="How decisions are made",
                        start_segment_sequence=1,
                        end_segment_sequence=10,
                        ordinal=1,
                    ),
                    StructureNodeProposal(
                        temp_id="s1",
                        parent_temp_id="t1",
                        node_type=StructureNodeType.STORY,
                        title="Sunk cost story",
                        summary="A story about sunk cost",
                        start_segment_sequence=3,
                        end_segment_sequence=8,
                        ordinal=1,
                    ),
                ]
            )
        if request.task == "knowledge_unit_metadata":
            nodes = json.loads(request.input_text)
            return UnitMetadataBatch(
                units=[
                    UnitMetadataProposal(
                        node_id=item["node_id"],
                        unit_type=(
                            KnowledgeUnitType.STORY
                            if item["node_type"] == "STORY"
                            else KnowledgeUnitType.EXPLANATION
                        ),
                        title=item["title"],
                        summary=item["summary"],
                    )
                    for item in nodes
                ]
            )
        if request.task == "unit_concept_mapping":
            return UnitConceptBatch(
                concepts=[
                    ConceptProposal(
                        canonical_name="Sunk cost fallacy",
                        relation_role="PRIMARY_TOPIC",
                        confidence=0.9,
                    ),
                    ConceptProposal(
                        canonical_name="Decision making",
                        relation_role="MENTIONED",
                        confidence=0.7,
                    ),
                ]
            )
        raise AssertionError(f"unexpected task: {request.task}")


class _FakeEmbeddings:
    provider_name = "fake-embed"
    model_name = "fixture"
    revision = "0"
    dimensions = 8

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        return [digest[index] / 255.0 for index in range(self.dimensions)]


async def _build_units(database: Database) -> Source:
    async with database.transaction() as session:
        source = Source(
            source_type=SourceType.YOUTUBE_VIDEO,
            platform="youtube",
            external_id=f"retr{uuid4().hex[:8]}",
            canonical_url="https://example.test/video",
            title="Retrieval fixture",
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
                    raw_text=f"segment {index} about sunk cost decisions",
                    normalized_text=f"segment {index} about sunk cost decisions",
                    language="en",
                    content_hash=hashlib.sha256(f"seg{index}".encode()).hexdigest(),
                )
            )
        await session.flush()
        return source


@pytest.mark.asyncio
async def test_concepts_retrieval_and_structural_expansion(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        source = await _build_units(database)
        provider = _Provider()
        structure = SourceStructureService(database, provider=provider)
        await structure.process_source(source.id)
        units = KnowledgeUnitService(database, provider=provider)
        await units.extract_for_source(source.id)

        async with database.transaction() as session:
            version_id = (
                await session.scalars(
                    select(SourceVersion.id).where(SourceVersion.source_id == source.id)
                )
            ).first()
        assert version_id is not None

        mapping = ConceptMappingService(database, provider=provider)
        stats = await mapping.map_source_units(version_id)
        assert stats["units"] == 1
        assert stats["links"] == 2

        async with database.transaction() as session:
            concept_count = len(list(await session.scalars(select(ExternalConcept))))
            relations = list(await session.scalars(select(ConceptRelationship)))
        assert concept_count == 2
        # The two co-occurring concepts produce one RELATED_TO edge.
        assert len(relations) == 1
        assert relations[0].relation_type.value == "RELATED_TO"

        embeddings = UnitEmbeddingService(database, _FakeEmbeddings())
        assert await embeddings.build(version_id) == 2  # summary + full_text
        assert await embeddings.build(version_id) == 0  # idempotent

        search = KnowledgeUnitSearchService(database, _FakeEmbeddings())
        results = await search.search("sunk cost", expansion=ExpansionMode.PARENT)
        assert results
        hit = results[0]
        assert hit.unit_type == "STORY"
        assert hit.atomic
        assert "Sunk cost fallacy" in hit.matched_concepts
        assert hit.source_title == "Retrieval fixture"
        assert hit.source_url == "https://example.test/video"
        assert hit.structure_path == ("Decision making", "Sunk cost story")
        assert "sunk cost" in hit.full_text.lower()
        # Expansion adds context units or node siblings; parent has no unit.
        assert isinstance(hit.expanded_context, tuple)

        concept_hit = await search.search("decision making")
        assert concept_hit

        family = await search.search("sunk cost", expansion=ExpansionMode.SUBTREE)
        assert family
    finally:
        await database.dispose()
