"""Studio shell routes against a real migrated database (Phase 2)."""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from alembic import command
from app.briefs.service import BriefInput, BriefService
from app.content_engine.service import ContentEngineService
from app.core.config import Environment, Settings
from app.db.session import Database
from app.editorial_channels.domain import (
    EDITORIAL_CHANNEL_SEEDS,
    ChannelResourceRole,
)
from app.editorial_channels.service import EditorialChannelService
from app.knowledge.domain import IngestionStatus, SourceType
from app.knowledge.models import Source
from app.knowledge.structure.service import SourceStructureService
from app.knowledge.units.service import KnowledgeUnitService
from app.main import create_app
from app.research.generic import GenericResearchService
from app.topics.service import TopicService
from tests.integration.test_topics import _build_source_with_units, _Provider

pytestmark = pytest.mark.integration

CHANNEL_SLUGS = [seed.slug for seed in EDITORIAL_CHANNEL_SEEDS]


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
    return make_url(url).set(database=database).render_as_string(hide_password=False)


@pytest.fixture
def studio_client(tmp_path: Path) -> Iterator[tuple[TestClient, str]]:
    """Disposable migrated database behind a TestClient."""

    base_url = _database_url()
    name = f"emtedad_test_{uuid4().hex}"
    admin_url = _sync_url(_url_for_database(base_url, "postgres"))
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = _url_for_database(base_url, name)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(url),
        storage_root=tmp_path / "storage",
    )
    try:
        with TestClient(create_app(settings)) as client:
            yield client, url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def _seed(client: TestClient) -> None:
    # The /studio home lazily runs the idempotent channel seed on first access.
    assert client.get("/studio").status_code == 200


def test_all_five_channel_routes_return_200(studio_client) -> None:
    client, _ = studio_client
    _seed(client)
    assert client.get("/studio/channels").status_code == 200
    for slug in CHANNEL_SLUGS:
        for suffix in (
            "",
            "/strategy",
            "/resources",
            "/topics",
            "/production",
            "/published",
        ):
            response = client.get(f"/studio/channels/{slug}{suffix}")
            assert response.status_code == 200, f"{slug}{suffix}"
    for path in ("/library", "/production", "/analytics", "/settings"):
        assert client.get(path).status_code == 200, path


def test_channel_switcher_shows_five_real_channels(studio_client) -> None:
    client, _ = studio_client
    response = client.get("/studio")
    assert response.status_code == 200
    body = response.text
    for slug in CHANNEL_SLUGS:
        assert f"/studio/channels/{slug}" in body
    assert 'href="/static/studio.css"' in body


def test_switching_slug_changes_channel_context(studio_client) -> None:
    client, _ = studio_client
    _seed(client)
    emtedad = client.get("/studio/channels/emtedad")
    science = client.get("/studio/channels/science-mystery")
    assert emtedad.status_code == 200 and science.status_code == 200
    assert "Emtedad" in emtedad.text
    assert (
        "Science &amp; Mystery" in science.text or "Science & Mystery" in science.text
    )


def test_unknown_channel_slug_returns_404(studio_client) -> None:
    client, _ = studio_client
    _seed(client)
    response = client.get("/studio/channels/not-a-channel")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_assignment_visible_in_channel_and_source_not_duplicated(
    studio_client,
) -> None:
    client, database_url = studio_client
    _seed(client)
    database = Database(database_url)
    try:
        async with database.transaction() as session:
            source = Source(
                source_type=SourceType.YOUTUBE_VIDEO,
                platform="youtube",
                external_id=f"studio{uuid4().hex[:8]}",
                canonical_url="https://www.youtube.com/watch?v=studio-fixture",
                title="Studio fixture source",
                language="en",
                ingestion_status=IngestionStatus.INGESTED,
            )
            session.add(source)
            await session.flush()
            source_id = source.id

        response = client.post(
            "/studio/channels/emtedad/resources",
            data={"source_id": str(source_id), "role": "PRIMARY"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        page = client.get("/studio/channels/emtedad/resources")
        assert page.status_code == 200
        assert "Studio fixture source" in page.text

        library = client.get(f"/library/{source_id}")
        assert library.status_code == 200
        assert "emtedad" in library.text

        async with database.transaction() as session:
            from sqlalchemy import func, select

            count = await session.scalar(
                select(func.count(Source.id)).where(Source.id == source_id)
            )
        assert count == 1

        unassign = client.post(
            f"/studio/channels/emtedad/resources/{source_id}/unassign",
            follow_redirects=False,
        )
        assert unassign.status_code == 303
        page = client.get("/studio/channels/emtedad/resources")
        # The source returns to the assignable list but is no longer linked.
        assert f"/library/{source_id}" not in page.text
        assert f'value="{source_id}"' in page.text
        async with database.transaction() as session:
            persisted = await session.get(Source, source_id)
        assert persisted is not None
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_production_workspace_generic_master_flow(studio_client) -> None:
    """§18 UI: Build Semantic Master action, stage update, no lesson fields."""

    client, database_url = studio_client
    _seed(client)
    database = Database(database_url)
    try:
        provider = _Provider()
        channel_service = EditorialChannelService(database)
        channel = await channel_service.get_channel("emtedad")
        source = await _build_source_with_units(database)
        await channel_service.assign_resource(
            channel.id, source.id, role=ChannelResourceRole.PRIMARY
        )
        await SourceStructureService(database, provider=provider).process_source(
            source.id
        )
        await KnowledgeUnitService(database, provider=provider).extract_for_source(
            source.id
        )
        candidates = await TopicService(database, provider=provider).mine("emtedad")
        briefs = BriefService(database)
        brief = await briefs.create_for_candidate(
            candidates[0].id,
            BriefInput(question="Q?", thesis="T.", target_duration_minutes=10),
        )
        await briefs.mark_ready(brief.id)
        research = GenericResearchService(database)
        plan = await research.create_plan_for_brief(brief.id)
        await research.build_evidence_matrix(brief.id)
        await research.freeze_package(plan.id)
        engine = ContentEngineService(database, provider=provider)
        await engine.build_argument(brief.id)
        await engine.build_narrative(brief.id)

        page = client.get(f"/studio/production/{brief.id}")
        assert page.status_code == 200
        assert "Build Semantic Master" in page.text
        assert "Build script" not in page.text  # gated until a master exists
        assert "lesson" not in page.text.lower()

        response = client.post(
            f"/studio/production/{brief.id}/actions/build_master",
            follow_redirects=False,
        )
        assert response.status_code == 303

        page = client.get(f"/studio/production/{brief.id}")
        assert page.status_code == 200
        assert "MASTER" in page.text  # stage advanced past NARRATIVE
        assert "Build script" in page.text
        assert "lesson" not in page.text.lower()
    finally:
        await database.dispose()
