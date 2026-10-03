"""Studio shell routes against a real migrated database (Phase 2)."""

import os
from collections.abc import Iterator
from datetime import UTC, datetime
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
from app.channel_monitoring.domain import CandidateStatus
from app.channel_monitoring.models import (
    ChannelVideoCandidate,
    MonitoredChannel,
)
from app.content_engine.service import ContentEngineService
from app.core.config import Environment, Settings
from app.db.session import Database
from app.editorial_channels.domain import (
    EDITORIAL_CHANNEL_SEEDS,
    ChannelResourceRole,
)
from app.editorial_channels.service import EditorialChannelService
from app.knowledge.adapters.base import (
    ChannelSnapshot,
    ChannelVideoSnapshot,
)
from app.knowledge.domain import IngestionStatus, SourceType
from app.knowledge.models import Source
from app.knowledge.structure.domain import SourceProcessingStatus
from app.knowledge.structure.models import SourceProcessingState
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
        assert "Semantic Master erstellen" in page.text
        assert "Skript erstellen" not in page.text  # gated until a master exists
        assert "lesson" not in page.text.lower()

        response = client.post(
            f"/studio/production/{brief.id}/actions/build_master",
            follow_redirects=False,
        )
        assert response.status_code == 303

        page = client.get(f"/studio/production/{brief.id}")
        assert page.status_code == 200
        assert "MASTER" in page.text  # stage advanced past NARRATIVE
        assert "Skript erstellen" in page.text
        assert "lesson" not in page.text.lower()
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_resource_tabs_and_topic_detail(studio_client) -> None:
    """Resource tab family + channel topic detail render persisted state."""

    client, database_url = studio_client
    _seed(client)
    database = Database(database_url)
    try:
        provider = _Provider()
        source = await _build_source_with_units(database)
        await SourceStructureService(database, provider=provider).process_source(
            source.id
        )
        await KnowledgeUnitService(database, provider=provider).extract_for_source(
            source.id
        )
        channel_service = EditorialChannelService(database)
        channel = await channel_service.get_channel("emtedad")
        await channel_service.assign_resource(
            channel.id, source.id, role=ChannelResourceRole.PRIMARY
        )

        for suffix in (
            "",
            "/original",
            "/structure",
            "/units",
            "/concepts",
            "/processing",
        ):
            response = client.get(f"/library/{source.id}{suffix}")
            assert response.status_code == 200, suffix

        overview = client.get(f"/library/{source.id}")
        assert "Wissens-Pipeline" in overview.text
        assert "Vortragsstruktur" in overview.text

        processing = client.get(f"/library/{source.id}/processing")
        assert "Vortragsstruktur" in processing.text
        assert "Retrieval Index" in processing.text

        # Library search narrows by title.
        filtered = client.get("/library", params={"q": "no-such-title-xyz"})
        assert filtered.status_code == 200
        assert f"/library/{source.id}" not in filtered.text
        filtered = client.get("/library", params={"q": "fixture"})
        assert filtered.status_code == 200

        candidates = await TopicService(database, provider=provider).mine("emtedad")
        assert candidates
        detail = client.get(f"/studio/channels/emtedad/topics/{candidates[0].id}")
        assert detail.status_code == 200
        assert "Eigenständigkeit" in detail.text
        assert "Wissens-Abdeckung" in detail.text

        # Cross-channel isolation: another channel must not see the candidate.
        other = client.get(
            f"/studio/channels/science-mystery/topics/{candidates[0].id}"
        )
        assert other.status_code == 404

        # Manual question creates a real candidate.
        manual = client.post(
            "/studio/channels/emtedad/topics/manual",
            data={"video_question": "Why do manual topics exist?"},
            follow_redirects=False,
        )
        assert manual.status_code == 303
        topics_page = client.get("/studio/channels/emtedad/topics")
        assert "Why do manual topics exist?" in topics_page.text
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_strategy_draft_and_activation_flow(studio_client) -> None:
    """Draft creation clones active; activation archives the old version."""

    client, database_url = studio_client
    _seed(client)
    database = Database(database_url)
    try:
        response = client.post(
            "/studio/channels/emtedad/strategy/draft",
            data={"core_question": "Sprint draft question?"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        page = client.get("/studio/channels/emtedad/strategy")
        assert "Sprint draft question?" in page.text
        assert "Entwurf aktivieren" in page.text

        service = EditorialChannelService(database)
        channel = await service.get_channel("emtedad")
        strategies = await service.list_strategies(channel.id)
        draft = next(s for s in strategies if s.status.value == "DRAFT")
        active_before = next(s for s in strategies if s.status.value == "ACTIVE")

        activate = client.post(
            f"/studio/channels/emtedad/strategy/{draft.id}/activate",
            follow_redirects=False,
        )
        assert activate.status_code == 303
        strategies = await service.list_strategies(channel.id)
        by_id = {s.id: s for s in strategies}
        assert by_id[draft.id].status.value == "ACTIVE"
        assert by_id[active_before.id].status.value == "ARCHIVED"

        # Cross-channel: a foreign version id must not activate via this route.
        science = await service.get_channel("science-mystery")
        wrong = client.post(
            f"/studio/channels/emtedad/strategy/{science.id}/activate",
            follow_redirects=False,
        )
        assert wrong.status_code == 404
    finally:
        await database.dispose()


# ---------------------------------------------------------------------------
# Final Studio UI redesign — new screens, workflows, error UX
# ---------------------------------------------------------------------------


class _FakeChannelAdapter:
    async def resolve_channel(self, _locator: str) -> ChannelSnapshot:
        return ChannelSnapshot(
            external_channel_id="UCtest-channel-000001",
            name="Fixture Quellkanal",
            channel_url="https://www.youtube.com/channel/UCtest-channel-000001",
            handle="@fixture-kanal",
        )

    async def list_channel_videos(
        self, _locator: str
    ) -> tuple[ChannelVideoSnapshot, ...]:
        return (
            ChannelVideoSnapshot(
                youtube_video_id="FIXTUREVIDEO1",
                title="Fixture Video Eins",
                published_at=datetime.now(UTC),
                thumbnail_url=None,
                duration_seconds=300,
            ),
        )


def _seed_monitored_channel(session) -> MonitoredChannel:
    channel = MonitoredChannel(
        platform="YOUTUBE",
        external_channel_id=f"UC{uuid4().hex[:20]}",
        name="Beobachteter Testkanal",
        channel_url="https://www.youtube.com/channel/test",
        handle="@testkanal",
        active=True,
        last_checked_at=datetime.now(UTC),
    )
    session.add(channel)
    return channel


def test_dashboard_shows_shell_five_channels_and_workflow(studio_client) -> None:
    client, _ = studio_client
    page = client.get("/studio")
    assert page.status_code == 200
    body = page.text
    # Sidebar separation: editorial vs. source channels.
    assert "Meine Kanäle" in body
    assert "YouTube-Kanäle" in body
    assert "sidebar" in body
    # Exactly five editorial channel cards with real DB counts.
    for slug in CHANNEL_SLUGS:
        assert f"/studio/channels/{slug}" in body
    assert body.count("chan-card") == 5
    # Seven-step workflow explainer.
    assert "Dein Workflow" in body
    assert body.count("wf-step") == 7
    # Attention is a secondary card, not the headline.
    assert "Meine 5 Kanäle" in body


def test_youtube_channels_page_and_detail(studio_client) -> None:
    client, database_url = studio_client
    _seed(client)

    import asyncio

    from app.db.session import Database as _Db

    async def _insert() -> str:
        db = _Db(database_url)
        try:
            async with db.transaction() as session:
                channel = _seed_monitored_channel(session)
                await session.flush()
                session.add(
                    ChannelVideoCandidate(
                        channel_id=channel.id,
                        youtube_video_id="CANDIDATE1",
                        title="Neues Kandidaten-Video",
                        status=CandidateStatus.NEW,
                        discovered_at=datetime.now(UTC),
                    )
                )
                return str(channel.id)
        finally:
            await db.dispose()

    channel_id = asyncio.run(_insert())

    page = client.get("/studio/youtube")
    assert page.status_code == 200
    assert "Beobachteter Testkanal" in page.text
    assert "YouTube-Kanal hinzufügen" in page.text
    assert "Neues Kandidaten-Video" in page.text

    detail = client.get(f"/studio/youtube/{channel_id}")
    assert detail.status_code == 200
    assert "Neues Kandidaten-Video" in detail.text
    assert "Ausgewählte importieren" in detail.text
    assert "Kanal entfernen" in detail.text

    missing = client.get(f"/studio/youtube/{uuid4()}")
    assert missing.status_code == 404


def test_youtube_add_channel_flow_with_injected_adapter(studio_client) -> None:
    client, _ = studio_client
    _seed(client)
    client.app.state.channel_adapter = _FakeChannelAdapter()
    try:
        response = client.post(
            "/studio/youtube",
            data={"locator": "https://www.youtube.com/@fixture-kanal"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "msg=Kanal" in response.headers["location"]

        page = client.get("/studio/youtube")
        assert "Fixture Quellkanal" in page.text
    finally:
        client.app.state.channel_adapter = None


def test_youtube_add_channel_error_is_human_readable(studio_client) -> None:
    client, _ = studio_client
    _seed(client)
    client.app.state.channel_adapter = _FakeChannelAdapter()
    try:
        # Empty locator → friendly error, no traceback.
        response = client.post(
            "/studio/youtube", data={"locator": ""}, follow_redirects=False
        )
        assert response.status_code == 303
        assert "error=" in response.headers["location"]
    finally:
        client.app.state.channel_adapter = None


def test_global_topics_page_and_manual_topic(studio_client) -> None:
    client, _ = studio_client
    _seed(client)
    page = client.get("/studio/topics")
    assert page.status_code == 200
    assert "+ Neues Thema" in page.text
    assert "Video-Frage" in page.text

    response = client.post(
        "/studio/topics",
        data={
            "channel_slug": "emtedad",
            "video_question": "Warum testen wir manuelle Themen?",
            "tentative_thesis": "Weil der Owner sie braucht.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/studio/topics?channel=emtedad")
    assert "Warum testen wir manuelle Themen?" in page.text

    # Missing fields → error redirect, not a crash.
    bad = client.post(
        "/studio/topics",
        data={"channel_slug": "emtedad"},
        follow_redirects=False,
    )
    assert bad.status_code == 303
    assert "error=" in bad.headers["location"]


def test_translations_and_publishing_pages_render(studio_client) -> None:
    client, _ = studio_client
    _seed(client)
    page = client.get("/studio/translations")
    assert page.status_code == 200
    assert "Übersetzungen" in page.text
    assert "Persisch" in page.text or "Noch keine" in page.text

    page = client.get("/studio/publishing")
    assert page.status_code == 200
    assert "Veröffentlichung" in page.text
    assert "YouTube-Veröffentlichung ist noch nicht verbunden" in page.text


@pytest.mark.asyncio
async def test_processing_error_is_humanized_not_raw(studio_client) -> None:
    """Raw provider codes must only appear inside a tech-details element."""

    client, database_url = studio_client
    _seed(client)
    database = Database(database_url)
    try:
        async with database.transaction() as session:
            source = Source(
                source_type=SourceType.YOUTUBE_VIDEO,
                platform="youtube",
                external_id=f"err{uuid4().hex[:8]}",
                canonical_url="https://www.youtube.com/watch?v=err-fixture",
                title="Error fixture source",
                language="en",
                ingestion_status=IngestionStatus.INGESTED,
            )
            session.add(source)
            await session.flush()
            session.add(
                SourceProcessingState(
                    source_id=source.id,
                    status=SourceProcessingStatus.FAILED,
                    last_error='PROVIDER_QUOTA_EXHAUSTED: {"detail": "quota exceeded"}',
                )
            )
            source_id = source.id

        for path in (f"/library/{source_id}", f"/library/{source_id}/processing"):
            page = client.get(path)
            assert page.status_code == 200, path
            body = page.text
            # Human-readable German error present.
            assert "Provider-Kapazität erreicht" in body
            # Raw code appears at most inside a tech-details element.
            occurrences = body.count("PROVIDER_QUOTA_EXHAUSTED")
            assert occurrences <= 1, path
            if occurrences:
                assert "tech-details" in body
            # Never rendered as a bare error banner with the raw code.
            assert '<p class="error">PROVIDER_QUOTA_EXHAUSTED' not in body
    finally:
        await database.dispose()
