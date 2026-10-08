"""Studio shell routes against a real migrated database (Phase 2)."""

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from alembic import command
from app.briefs.domain import BriefStatus
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
from app.ops.settings.service import StudioSettingsService
from app.production.service import ProductionService
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


def _disable_web_research(url: str) -> None:
    """Persist the owner override the test app runs with."""

    from app.ops.settings.service import StudioSettingsService

    async def apply() -> None:
        database = Database(url)
        try:
            await StudioSettingsService(database).set_many(
                {"web_research_enabled": False}
            )
        finally:
            await database.dispose()

    asyncio.run(apply())


@pytest.fixture
def studio_client(tmp_path: Path) -> Iterator[tuple[TestClient, str]]:
    """Disposable migrated database behind a TestClient.

    Web research is switched off through an owner override. With it on,
    ``plan_research`` sends live queries to whatever answers on
    ``web_research_base_url`` (the default is a local SearXNG port), so the
    suite depended on the internet and on a container it does not own, and
    real searches pushed the background step past the job timeout. The
    override is the owner's own mechanism, and it is what the services read:
    ``StudioSettingsService`` resolves its fallback through
    ``get_settings()``, not through the ``Settings`` passed to
    ``create_app``, so setting the field here would have no effect.
    """

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
    _disable_web_research(url)
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


def _wait_for_job(brief_id: object, timeout: float = 30.0) -> None:
    """Production steps run in the background; wait and fail loudly."""

    import time

    from app.web.jobs import jobs

    key = str(brief_id)
    deadline = time.monotonic() + timeout
    while jobs.is_running(key):
        assert time.monotonic() < deadline, "background step did not finish"
        time.sleep(0.05)
    job = jobs.get(key)
    assert job is None or job.error is None, job.error if job else None


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
        _wait_for_job(brief.id)

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


@pytest.mark.asyncio
async def test_settings_web_research_roundtrip(studio_client) -> None:
    """Owner toggles web research; the API key is masked on re-render."""

    client, database_url = studio_client
    page = client.get("/settings")
    assert page.status_code == 200
    assert "Internet-Recherche" in page.text
    assert "Video-Länge" in page.text

    response = client.post(
        "/settings",
        data={
            "web_research_enabled": "on",
            "web_research_provider": "tavily",
            "web_research_base_url": "https://api.tavily.test",
            "web_research_model": "",
            "web_research_api_key": "sk-owner-key-9999",
            "web_research_max_results": "7",
            "web_research_timeout_seconds": "45",
            "target_duration_default_minutes": "22",
            "target_duration_min_minutes": "20",
            "target_duration_max_minutes": "25",
            "units_per_video_minute": "2",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    database = Database(database_url)
    try:
        service = StudioSettingsService(database)
        effective = await service.effective()
        assert effective["web_research_enabled"] is True
        assert effective["web_research_provider"] == "tavily"
        assert effective["web_research_base_url"] == "https://api.tavily.test"
        assert effective["web_research_api_key"] == "sk-owner-key-9999"
        assert effective["web_research_max_results"] == 7
        assert effective["units_per_video_minute"] == 2.0
    finally:
        await database.dispose()

    page = client.get("/settings")
    assert "sk-owner-key-9999" not in page.text
    assert "••" in page.text

    # Submitting again with the masked placeholder must not clobber the key.
    response = client.post(
        "/settings",
        data={
            "web_research_enabled": "on",
            "web_research_provider": "tavily",
            "web_research_base_url": "https://api.tavily.test",
            "web_research_api_key": "••••••9999",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    database = Database(database_url)
    try:
        effective = await StudioSettingsService(database).effective()
        assert effective["web_research_api_key"] == "sk-owner-key-9999"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_brief_defaults_to_27_5_minutes_and_shows_gap(studio_client) -> None:
    """Brief creation clamps to the configured 25–30 range, default 27.5."""

    client, database_url = studio_client
    _seed(client)
    database = Database(database_url)
    try:
        service = EditorialChannelService(database)
        channel = await service.get_channel("emtedad")
        strategies = await service.list_strategies(channel.id)
        active = next(s for s in strategies if s.status.value == "ACTIVE")
        candidate = await TopicService(database).create_manual(
            channel.id,
            active.id,
            question="Why do we forget names?",
            thesis="Names fail because they lack semantic hooks.",
        )
        response = client.post(
            f"/studio/topics/{candidate.id}/brief", follow_redirects=False
        )
        assert response.status_code == 303
        briefs = await BriefService(database).list_for_candidate(candidate.id)
        assert len(briefs) == 1
        assert briefs[0].target_duration_minutes == 27.5

        # No units yet → the workspace flags the material gap in German.
        page = client.get(f"/studio/production/{briefs[0].id}")
        assert page.status_code == 200
        assert "Lücke:" in page.text
        # With web research on, the workspace offers the manual button. The
        # fixture keeps it off so the suite stays offline, so turn it on
        # here — rendering the button makes no outbound call.
        await StudioSettingsService(database).set_many({"web_research_enabled": True})
        page = client.get(f"/studio/production/{briefs[0].id}")
        assert "Im Internet recherchieren" in page.text
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_web_research_button_and_disabled_notice(studio_client) -> None:
    """With the toggle on, the workspace offers manual research; the POST
    reports 'disabled' only when the owner turned it off."""

    client, database_url = studio_client
    _seed(client)
    database = Database(database_url)
    try:
        service = EditorialChannelService(database)
        channel = await service.get_channel("emtedad")
        strategies = await service.list_strategies(channel.id)
        active = next(s for s in strategies if s.status.value == "ACTIVE")
        candidate = await TopicService(database).create_manual(
            channel.id, active.id, question="Gap question?"
        )
        brief = await BriefService(database).create_for_candidate(
            candidate.id,
            BriefInput(
                question="Gap question?",
                thesis="T.",
                target_duration_minutes=22,
            ),
        )

        # Owner turns web research off → POST reports the feature is off.
        from app.ops.settings.service import StudioSettingsService

        await StudioSettingsService(database).set_many({"web_research_enabled": False})
        response = client.post(
            f"/studio/production/{brief.id}/web-research",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "deaktiviert" in response.headers["location"]

        # Enable via owner settings → the button appears.
        await StudioSettingsService(database).set_many({"web_research_enabled": True})
        page = client.get(f"/studio/production/{brief.id}")
        assert "Im Internet recherchieren" in page.text
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_workspace_stepper_truthful_not_positional(studio_client) -> None:
    """Audit §3: the stepper marks stages done only for real artifacts.

    A READY evidence matrix without a research plan must show Evidence as
    done and Recherche as NOT done — positional inference would mark every
    step before Evidence complete.
    """

    client, database_url = studio_client
    _seed(client)
    database = Database(database_url)
    try:
        provider = _Provider()
        channel_service = EditorialChannelService(database)
        channel = await channel_service.get_channel("emtedad")
        source = await _build_source_with_units(database)
        await SourceStructureService(database, provider=provider).process_source(
            source.id
        )
        await KnowledgeUnitService(database, provider=provider).extract_for_source(
            source.id
        )
        await channel_service.assign_resource(
            channel.id, source.id, role=ChannelResourceRole.PRIMARY
        )
        candidates = await TopicService(database, provider=provider).mine("emtedad")
        brief = await BriefService(database).create_for_candidate(
            candidates[0].id,
            BriefInput(question="Q?", thesis="T.", target_duration_minutes=10),
        )
        await BriefService(database).mark_ready(brief.id)
        # Evidence matrix built without ever creating a research plan.
        await GenericResearchService(database).build_evidence_matrix(brief.id)

        page = client.get(f"/studio/production/{brief.id}")
        assert page.status_code == 200
        # Evidence must show done; Recherche must NOT — it has no artifact.
        import re as _re

        done_steps = _re.findall(
            r'class="step[^"]*done[^"]*"[^>]*>\s*'
            r'(?:<span class="step-icon">[^<]*</span>)?([^<]+)<',
            page.text,
        )
        done_steps = [s.strip() for s in done_steps]
        assert "Evidence" in done_steps
        assert "Recherche" not in done_steps
        assert "Argument" not in done_steps
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_failed_action_surfaces_error_to_owner(studio_client) -> None:
    """Audit §45: action failures must not redirect as if nothing happened."""

    client, database_url = studio_client
    _seed(client)
    database = Database(database_url)
    try:
        service = EditorialChannelService(database)
        channel = await service.get_channel("emtedad")
        strategies = await service.list_strategies(channel.id)
        active = next(s for s in strategies if s.status.value == "ACTIVE")
        candidate = await TopicService(database).create_manual(
            channel.id, active.id, question="Error surfacing?"
        )
        brief = await BriefService(database).create_for_candidate(
            candidate.id,
            BriefInput(
                question="Error surfacing?", thesis="T.", target_duration_minutes=22
            ),
        )
        # Approve with no draft at all — must surface an error, not no-op.
        response = client.post(
            f"/studio/production/{brief.id}/actions/approve",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "error=" in response.headers["location"]
        # The error notice renders on the workspace page.
        page = client.get(response.headers["location"])
        assert page.status_code == 200
        assert "im aktuellen Zustand nicht möglich" in page.text
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_freeze_research_action_freezes_package(studio_client) -> None:
    """The UI freeze action produces the FROZEN package the master gate needs."""

    client, database_url = studio_client
    _seed(client)
    database = Database(database_url)
    try:
        provider = _Provider()
        channel_service = EditorialChannelService(database)
        channel = await channel_service.get_channel("emtedad")
        source = await _build_source_with_units(database)
        await SourceStructureService(database, provider=provider).process_source(
            source.id
        )
        await KnowledgeUnitService(database, provider=provider).extract_for_source(
            source.id
        )
        await channel_service.assign_resource(
            channel.id, source.id, role=ChannelResourceRole.PRIMARY
        )
        candidates = await TopicService(database, provider=provider).mine("emtedad")
        brief = await BriefService(database).create_for_candidate(
            candidates[0].id,
            BriefInput(question="Q?", thesis="T.", target_duration_minutes=10),
        )
        await BriefService(database).mark_ready(brief.id)
        research = GenericResearchService(database)
        await research.create_plan_for_brief(brief.id)
        await research.build_evidence_matrix(brief.id)

        page = client.get(f"/studio/production/{brief.id}")
        assert "Recherche einfrieren" in page.text

        response = client.post(
            f"/studio/production/{brief.id}/actions/freeze_research",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "error=" not in response.headers["location"]
        _wait_for_job(brief.id)

        from sqlalchemy import select

        from app.research.domain import PackageStatus
        from app.research.models import ResearchPackage

        async with database.transaction() as session:
            package = await session.scalar(
                select(ResearchPackage).where(
                    ResearchPackage.content_brief_id == brief.id
                )
            )
        assert package is not None
        assert package.status is PackageStatus.FROZEN
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_waive_finding_route(studio_client) -> None:
    """Owner waiver via POST flips an open finding; wrong brief → 404."""

    client, database_url = studio_client
    _seed(client)
    database = Database(database_url)
    try:
        provider = _Provider()
        channel_service = EditorialChannelService(database)
        channel = await channel_service.get_channel("emtedad")
        source = await _build_source_with_units(database)
        await SourceStructureService(database, provider=provider).process_source(
            source.id
        )
        await KnowledgeUnitService(database, provider=provider).extract_for_source(
            source.id
        )
        await channel_service.assign_resource(
            channel.id, source.id, role=ChannelResourceRole.PRIMARY
        )
        candidates = await TopicService(database, provider=provider).mine("emtedad")
        briefs = BriefService(database)
        brief = await briefs.create_for_candidate(
            candidates[0].id,
            BriefInput(
                question="Waive finding?", thesis="T.", target_duration_minutes=22
            ),
        )
        other = await briefs.create_for_candidate(
            candidates[0].id,
            BriefInput(question="Other?", thesis="T.", target_duration_minutes=22),
        )
        await briefs.mark_ready(brief.id)

        research = GenericResearchService(database)
        plan = await research.create_plan_for_brief(brief.id)
        await research.build_evidence_matrix(brief.id)
        await research.freeze_package(plan.id)
        engine = ContentEngineService(database, provider=provider)
        await engine.build_argument(brief.id)
        await engine.build_narrative(brief.id)
        from app.content_engine.review import ScriptService
        from app.lecture.generic_service import GenericMasterService

        await GenericMasterService(database).build_from_content_brief(brief.id)
        draft = await ScriptService(database, provider=provider).build_script(
            brief.id, language="en"
        )

        from app.content_engine.domain import FindingSeverity, FindingStatus
        from app.content_engine.models import ReviewFinding

        async with database.transaction() as session:
            finding = ReviewFinding(
                script_draft_id=draft.id,
                critic_role="FACT",
                severity=FindingSeverity.WARNING,
                location="opening",
                code="WEAK_EVIDENCE",
                explanation="Claim lacks support.",
            )
            session.add(finding)
            await session.flush()
            finding_id = finding.id

        # Wrong brief id → 404, no state change.
        response = client.post(
            f"/studio/production/{other.id}/findings/{finding_id}/waive",
            follow_redirects=False,
        )
        assert response.status_code == 404

        # A waiver without an owner justification must not resolve.
        response = client.post(
            f"/studio/production/{brief.id}/findings/{finding_id}/waive",
            follow_redirects=False,
        )
        assert "error=" in response.headers["location"]

        response = client.post(
            f"/studio/production/{brief.id}/findings/{finding_id}/waive",
            data={"reason": "acceptable minor style risk"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        async with database.transaction() as session:
            from sqlalchemy import select as _select

            stored = await session.scalar(
                _select(ReviewFinding.status).where(ReviewFinding.id == finding_id)
            )
        assert stored is FindingStatus.WAIVED

        # Second waive on the same finding surfaces an error, not silence.
        response = client.post(
            f"/studio/production/{brief.id}/findings/{finding_id}/waive",
            follow_redirects=False,
        )
        assert "error=" in response.headers["location"]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_approved_stage_cost_truth(studio_client) -> None:
    """§40: missing provider cost renders as unavailable, never $0.0000.

    One language with all-NULL costs must show the honest label; a second
    language with partial coverage shows the reported sum plus the
    coverage count.
    """

    client, database_url = studio_client
    _seed(client)
    database = Database(database_url)
    try:
        import hashlib

        from app.content_engine.domain import DraftStatus, PlanStatus
        from app.content_engine.models import (
            ArgumentPlan,
            NarrativePlan,
            ScriptDraft,
        )
        from app.knowledge.llm.models import LLMCallEvent
        from app.research.domain import EvidenceMatrixStatus
        from app.research.models import EvidenceMatrix

        channel = await EditorialChannelService(database).get_channel("emtedad")
        strategies = await EditorialChannelService(database).list_strategies(channel.id)
        active = next(s for s in strategies if s.status.value == "ACTIVE")
        candidate = await TopicService(database).create_manual(
            channel.id, active.id, question="Cost truth?"
        )
        brief = await BriefService(database).create_for_candidate(
            candidate.id,
            BriefInput(
                question="Cost truth?",
                thesis="T.",
                target_duration_minutes=27.5,
            ),
        )
        async with database.transaction() as session:
            matrix = EvidenceMatrix(
                content_brief_id=brief.id,
                version_number=1,
                status=EvidenceMatrixStatus.READY,
                content_hash=hashlib.sha256(b"matrix").hexdigest(),
            )
            session.add(matrix)
            await session.flush()
            argument = ArgumentPlan(
                content_brief_id=brief.id,
                evidence_matrix_id=matrix.id,
                version_number=1,
                status=PlanStatus.READY,
                content_hash=hashlib.sha256(b"argument").hexdigest(),
            )
            session.add(argument)
            await session.flush()
            narrative = NarrativePlan(
                content_brief_id=brief.id,
                argument_plan_id=argument.id,
                version_number=1,
                status=PlanStatus.READY,
                content_hash=hashlib.sha256(b"narrative").hexdigest(),
            )
            session.add(narrative)
            await session.flush()
            text = "word " * 3000
            session.add(
                ScriptDraft(
                    content_brief_id=brief.id,
                    narrative_plan_id=narrative.id,
                    language="fa",
                    version_number=1,
                    text=text,
                    status=DraftStatus.APPROVED,
                    provenance_json={},
                    content_hash=hashlib.sha256(text.encode()).hexdigest(),
                    target_duration_minutes=27.5,
                    actual_word_count=3000,
                )
            )
            # de: all calls lack provider cost; en: one of two reported.
            for _ in range(2):
                session.add(
                    LLMCallEvent(
                        provider="apimaster",
                        model="gpt-6.1-sol",
                        agent_role="localization_fidelity_critic",
                        task="localization_review",
                        prompt_tokens=100,
                        completion_tokens=50,
                        latency_ms=10,
                        ok=True,
                        language="de",
                        content_brief_id=brief.id,
                        cost_usd=None,
                    )
                )
            session.add(
                LLMCallEvent(
                    provider="apimaster",
                    model="gpt-6.1-sol",
                    agent_role="localization_fidelity_critic",
                    task="localization_review",
                    prompt_tokens=100,
                    completion_tokens=50,
                    latency_ms=10,
                    ok=True,
                    language="en",
                    content_brief_id=brief.id,
                    cost_usd=0.0123,
                )
            )
            session.add(
                LLMCallEvent(
                    provider="apimaster",
                    model="gpt-6.1-sol",
                    agent_role="localization_fidelity_critic",
                    task="localization_review",
                    prompt_tokens=100,
                    completion_tokens=50,
                    latency_ms=10,
                    ok=True,
                    language="en",
                    content_brief_id=brief.id,
                    cost_usd=None,
                )
            )

        page = client.get(f"/studio/production/{brief.id}?stage=APPROVED")
        assert page.status_code == 200
        body = page.text
        assert "Modellkosten (provider-gemeldet)" in body
        assert "nicht vom Provider gemeldet" in body
        assert "$0.0000" not in body
        assert "0.0123" in body
        assert "(1/2 Calls)" in body
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_brief_created_from_a_topic_is_ready_to_produce(studio_client) -> None:
    """Regression: a new brief was stranded in DRAFT.

    "Brief erstellen" on a topic was the only brief control in the whole
    Studio — nothing could move the brief from DRAFT to READY — so the
    workspace answered every production attempt with "Der Brief ist noch
    ein Entwurf" and the pipeline could never be started for a new topic.
    """

    client, database_url = studio_client
    _seed(client)
    database = Database(database_url)
    try:
        channels = EditorialChannelService(database)
        channel = await channels.get_channel("emtedad")
        strategy = next(
            s
            for s in await channels.list_strategies(channel.id)
            if s.status.value == "ACTIVE"
        )
        candidate = await TopicService(database).create_manual(
            channel.id,
            strategy.id,
            question="Warum Rituale?",
            thesis="Rituale tragen Bedeutung, die Argumente allein nicht tragen.",
        )
        response = client.post(
            f"/studio/topics/{candidate.id}/brief", follow_redirects=False
        )
        assert response.status_code == 303
        brief_id = UUID(response.headers["location"].rsplit("/", 1)[-1])

        brief = await BriefService(database).get(brief_id)
        assert brief is not None
        assert brief.status is BriefStatus.READY

        state = await ProductionService(database).state_for_brief(brief_id)
        assert state.next_action == "plan_research"
        page = client.get(f"/studio/production/{brief_id}")
        assert "noch ein Entwurf" not in page.text
    finally:
        await database.dispose()
