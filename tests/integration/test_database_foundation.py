"""PostgreSQL, pgvector, namespace, migration, and readiness integration tests."""

import asyncio
import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response
from psycopg import sql
from pydantic import SecretStr
from pypdf import PdfWriter
from sqlalchemy import select, text
from sqlalchemy.engine import URL, make_url

from alembic import command
from app.core.config import Environment, Settings
from app.db.base import SCHEMA_NAMES
from app.db.health import DatabaseReadinessService
from app.db.session import Database
from app.knowledge.adapters.base import ExternalSourceSnapshot, TranscriptEntry
from app.knowledge.domain import (
    EntityType,
    KnowledgeReviewStatus,
    ResolutionProvider,
    SourceType,
    VerificationStatus,
    WorkType,
)
from app.knowledge.extraction_schema import (
    ExtractedClaim,
    ExtractedMention,
    WindowExtraction,
)
from app.knowledge.importer import ExternalKnowledgeImporter
from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.media import MediaService
from app.knowledge.models import (
    ExternalClaim,
    ExternalIdentifier,
    ReviewFlag,
    SourceSegment,
    SourceVersion,
    Work,
)
from app.knowledge.resolution import ProviderCandidate
from app.knowledge.resolution_service import ResolutionService
from app.main import create_app
from app.storage.local import LocalObjectStore

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


def _url_for_database(url: str, database: str) -> str:
    parsed: URL = make_url(url)
    return parsed.set(database=database).render_as_string(hide_password=False)


@pytest.fixture
def disposable_database_url() -> Iterator[str]:
    """Create a dedicated database so migration rollback cannot touch dev data."""

    base_url = _database_url()
    database_name = f"emtedad_test_{uuid4().hex}"
    admin_url = _sync_url(_url_for_database(base_url, "postgres"))

    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )

    test_url = _url_for_database(base_url, database_name)
    try:
        yield test_url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            connection.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name))
            )


def _alembic_config(database_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _schema_names(database_url: str) -> set[str]:
    with psycopg.connect(_sync_url(database_url)) as connection:
        rows = connection.execute(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name = ANY(%s)",
            (list(SCHEMA_NAMES),),
        ).fetchall()
    return {str(row[0]) for row in rows}


def test_clean_migration_downgrade_and_second_upgrade_are_safe(
    disposable_database_url: str,
) -> None:
    config = _alembic_config(disposable_database_url)

    command.upgrade(config, "head")
    command.check(config)

    with psycopg.connect(_sync_url(disposable_database_url)) as connection:
        version_row = connection.execute("SHOW server_version_num").fetchone()
        vector_version = connection.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
        domain_table_rows = connection.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema = ANY(%s)",
            (list(SCHEMA_NAMES),),
        ).fetchall()
        review_status_default = connection.execute(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_schema = 'knowledge' "
            "AND table_name = 'dialogue_relations' "
            "AND column_name = 'review_status'"
        ).fetchone()
        classifier_key_unique = connection.execute(
            "SELECT count(*) FROM information_schema.table_constraints "
            "WHERE constraint_schema = 'knowledge' "
            "AND table_name = 'dialogue_proposal_run_candidates' "
            "AND constraint_type = 'UNIQUE' "
            "AND constraint_name = "
            "'uq_dialogue_proposal_run_candidates_classifier_cache_key'"
        ).fetchone()

    assert version_row is not None
    version = int(version_row[0])
    domain_tables = {(str(row[0]), str(row[1])) for row in domain_table_rows}

    assert version // 10_000 == 17
    assert vector_version is not None
    assert _schema_names(disposable_database_url) == set(SCHEMA_NAMES)
    assert ("core", "canon_documents") in domain_tables
    assert ("core", "canon_versions") in domain_tables
    assert ("core", "canon_passages") in domain_tables
    assert ("ops", "object_assets") in domain_tables
    assert ("ritual", "versions") in domain_tables
    assert ("ritual", "ritual_versions") in domain_tables
    assert ("knowledge", "sources") in domain_tables
    assert ("knowledge", "source_segments") in domain_tables
    assert ("retrieval", "chunks") in domain_tables
    assert ("retrieval", "chunk_embeddings") in domain_tables
    assert ("retrieval", "evaluation_runs") in domain_tables
    assert ("knowledge", "dialogue_relations") in domain_tables
    assert ("knowledge", "dialogue_proposal_runs") in domain_tables
    assert ("knowledge", "dialogue_review_decisions") in domain_tables
    assert ("content", "research_projects") in domain_tables
    assert ("content", "ayin_spines") in domain_tables
    assert ("content", "research_plans") in domain_tables
    assert ("content", "research_packages") in domain_tables
    assert ("content", "lecture_projects") in domain_tables
    assert ("content", "lecture_master_versions") in domain_tables
    assert ("content", "lecture_claims") in domain_tables
    assert ("content", "lecture_claim_evidence") in domain_tables
    assert not any(
        schema == "content" and "localization" in table_name
        for schema, table_name in domain_tables
    )
    assert review_status_default is not None
    assert "PROPOSED" in str(review_status_default[0])
    assert classifier_key_unique == (0,)

    command.downgrade(config, "base")
    assert _schema_names(disposable_database_url) == set()

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    assert _schema_names(disposable_database_url) == set(SCHEMA_NAMES)


@pytest.mark.asyncio
async def test_database_readiness_and_transaction_contract() -> None:
    database = Database(_database_url())
    try:
        readiness = await DatabaseReadinessService(database.engine).check()
        assert readiness.ready is True
        assert all(readiness.checks.values())

        async with database.transaction() as session:
            assert await session.scalar(text("SELECT 1")) == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_media_pdf_dedup_and_inaccessible_status(
    disposable_database_url: str, tmp_path: Path
) -> None:
    await asyncio.to_thread(
        command.upgrade, _alembic_config(disposable_database_url), "head"
    )
    database = Database(disposable_database_url)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = BytesIO()
    writer.write(buffer)
    pdf = buffer.getvalue()

    async def handler(request: Request) -> Response:
        if request.url.path.endswith("missing.pdf"):
            return Response(403, request=request)
        return Response(
            200,
            content=pdf,
            headers={"content-type": "application/pdf"},
            request=request,
        )

    try:
        async with database.transaction() as session:
            work = Work(
                work_type=WorkType.PAPER,
                canonical_title="Fixture",
                normalized_title="fixture",
                metadata_json={},
            )
            session.add(work)
            await session.flush()
            work_id = work.id
        async with AsyncClient(transport=MockTransport(handler)) as client:
            media = MediaService(
                database, LocalObjectStore(tmp_path / "objects"), client=client
            )
            first_pdf, first_page = await media.work_pdf(
                work_id, "https://example.test/paper.pdf"
            )
            second_pdf, second_page = await media.work_pdf(
                work_id, "https://example.test/paper.pdf"
            )
            missing, rendered = await media.work_pdf(
                work_id, "https://example.test/missing.pdf"
            )
        assert first_pdf.id == second_pdf.id
        assert first_page is not None and second_page is not None
        assert first_page.id == second_page.id
        assert missing.status.value == "no_accessible_pdf_found"
        assert rendered is None
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_application_reports_ready_against_migrated_database(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(_database_url()),
        storage_root=tmp_path / "storage",
        log_level="INFO",
        log_json=True,
    )
    app = create_app(settings)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_external_import_is_versioned_idempotent_and_attributed(
    disposable_database_url: str, tmp_path: Path
) -> None:
    await asyncio.to_thread(
        command.upgrade, _alembic_config(disposable_database_url), "head"
    )

    class Adapter:
        snapshot = ExternalSourceSnapshot(
            source_type=SourceType.YOUTUBE_VIDEO,
            platform="youtube",
            external_id="331XLUCCybU",
            canonical_url="https://www.youtube.com/watch?v=331XLUCCybU",
            title="Pilot",
            description="fixture",
            language="fa",
            published_at=datetime(2024, 1, 1, tzinfo=UTC),
            duration_seconds=20,
            channel_external_id="channel-1",
            channel_title="Channel",
            channel_url="https://youtube.com/channel/channel-1",
            creator_name="Creator",
            transcript_kind="manual",
            metadata={"availability": "public"},
            transcript=(
                TranscriptEntry(1, 0.125, 4.5, "متن خام يک"),
                TranscriptEntry(2, 4.625, 5.0, "Clark نام یک نویسنده است"),
            ),
            thumbnail_url=None,
        )

        async def acquire(self, locator: str) -> ExternalSourceSnapshot:
            return self.snapshot

    class Provider:
        name = "fixture"
        calls = 0

        async def extract(self, request: object) -> WindowExtraction:
            self.calls += 1
            return WindowExtraction(
                mentions=[
                    ExtractedMention(
                        entity_type=EntityType.PERSON,
                        surface_text="Clark",
                        normalized_candidate="Clark",
                        start_segment_sequence=2,
                        end_segment_sequence=2,
                        context="نام یک نویسنده است",
                        confidence=0.8,
                    )
                ],
                claims=[
                    ExtractedClaim(
                        claim_text="Clark نام یک نویسنده است",
                        claim_domain="attribution",
                        claim_type="source_assertion",
                        source_segment_sequence=2,
                        confidence=0.7,
                    )
                ],
            )

    database = Database(disposable_database_url)
    adapter = Adapter()
    provider = Provider()
    try:
        importer = ExternalKnowledgeImporter(
            database, adapter, provider, window_size=2, overlap=0
        )
        first = await importer.ingest("331XLUCCybU")
        second = await importer.ingest("331XLUCCybU")
        assert first.source_version_id == second.source_version_id
        assert second.cache_hits == 1
        assert provider.calls == 1

        adapter.snapshot = replace(
            adapter.snapshot,
            transcript=adapter.snapshot.transcript
            + (TranscriptEntry(3, 9.625, 3.0, "بخش تازه"),),
        )
        changed = await importer.ingest("331XLUCCybU")
        assert changed.source_version_id != first.source_version_id

        class Resolver:
            provider = ResolutionProvider.WIKIDATA

            async def search(
                self, query: str, entity_type: EntityType
            ) -> list[ProviderCandidate]:
                if query != "Clark":
                    return []
                return [
                    ProviderCandidate(
                        provider=self.provider,
                        candidate_key="Q123",
                        entity_type=entity_type,
                        name="Clark",
                        identifiers={"wikidata": "Q123"},
                        url="https://www.wikidata.org/wiki/Q123",
                        metadata={},
                    )
                ]

        resolution = await ResolutionService(database, [Resolver()]).resolve_pending(
            first.source_id
        )
        assert resolution.resolved >= 1

        async with database.transaction() as session:
            versions = list(await session.scalars(select(SourceVersion)))
            segments = list(
                await session.scalars(
                    select(SourceSegment).order_by(SourceSegment.sequence)
                )
            )
            claims = list(await session.scalars(select(ExternalClaim)))
            identifiers = list(await session.scalars(select(ExternalIdentifier)))
            assert len(versions) == 2
            assert versions[0].corpus_zone.value == "EXTERNAL_PRIMARY"
            assert segments[0].raw_text == "متن خام يک"
            assert segments[0].normalized_text == "متن خام یک"
            assert segments[0].start_seconds == Decimal("0.125")
            assert claims[0].verification_status is VerificationStatus.ATTRIBUTED_ONLY
            assert len(identifiers) == 1
            assert identifiers[0].normalized_value == "q123"

        settings = Settings(
            _env_file=None,
            environment=Environment.TEST,
            database_url=SecretStr(disposable_database_url),
            storage_root=tmp_path / "api-storage",
            log_level="INFO",
            log_json=True,
        )
        app = create_app(settings)
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            sources = await client.get("/knowledge/sources")
            segments_response = await client.get(
                f"/knowledge/sources/{first.source_id}/segments"
            )
            mentions_response = await client.get(
                f"/knowledge/sources/{first.source_id}/mentions"
            )
        assert sources.status_code == 200
        assert len(sources.json()) == 1
        assert segments_response.status_code == 200
        assert mentions_response.status_code == 200

        class FlakyProvider:
            name = "flaky-fixture"

            def __init__(self) -> None:
                self.failed_once = False

            async def extract(
                self, request: StructuredExtractionRequest
            ) -> WindowExtraction:
                input_text = request.input_text
                if "[2|" in input_text and not self.failed_once:
                    self.failed_once = True
                    raise RuntimeError("retryable fixture failure")
                return WindowExtraction(mentions=[], claims=[])

        adapter.snapshot = replace(
            adapter.snapshot,
            external_id="retry000001",
            canonical_url="https://www.youtube.com/watch?v=retry000001",
            transcript=(
                TranscriptEntry(1, 0.0, 1.0, "one"),
                TranscriptEntry(2, 1.0, 1.0, "two"),
            ),
        )
        retry_importer = ExternalKnowledgeImporter(
            database, adapter, FlakyProvider(), window_size=1, overlap=0
        )
        partial = await retry_importer.ingest("retry000001")
        recovered = await retry_importer.ingest("retry000001")
        assert partial.failed_windows == 1
        assert recovered.cache_hits == 1
        assert recovered.cache_misses == 1
        assert recovered.failed_windows == 0
        async with database.transaction() as session:
            retry_flag = await session.scalar(
                select(ReviewFlag).where(
                    ReviewFlag.source_version_id == recovered.source_version_id
                )
            )
            assert retry_flag is not None
            assert retry_flag.status is KnowledgeReviewStatus.RESOLVED
    finally:
        await database.dispose()
