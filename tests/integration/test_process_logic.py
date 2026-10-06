"""Owner-facing process logic: one next step, staleness, background jobs,
readable errors, Persian-only workspace drafts, native translations."""

import asyncio
import hashlib
from uuid import UUID

import pytest

import app.knowledge.llm.factory as factory
from app.briefs.service import BriefInput, BriefService
from app.content_engine.domain import DraftStatus, ProductionStage, StageHealth
from app.content_engine.models import ScriptDraft
from app.db.session import Database
from app.editorial_channels.domain import ChannelResourceRole
from app.editorial_channels.service import EditorialChannelService
from app.knowledge.structure.service import SourceStructureService
from app.knowledge.units.service import KnowledgeUnitService
from app.production.service import ProductionService
from app.topics.service import TopicService
from app.web.jobs import jobs
from tests.integration.test_studio_ui import (  # noqa: F401
    _seed,
    _wait_for_job,
    studio_client,
)
from tests.integration.test_topics import _build_source_with_units, _Provider

pytestmark = pytest.mark.integration


async def _brief_with_material(database: Database) -> UUID:
    provider = _Provider()
    channels = EditorialChannelService(database)
    channel = await channels.get_channel("emtedad")
    source = await _build_source_with_units(database)
    await channels.assign_resource(
        channel.id, source.id, role=ChannelResourceRole.PRIMARY
    )
    await SourceStructureService(database, provider=provider).process_source(source.id)
    await KnowledgeUnitService(database, provider=provider).extract_for_source(
        source.id
    )
    candidates = await TopicService(database, provider=provider).mine("emtedad")
    brief = await BriefService(database).create_for_candidate(
        candidates[0].id,
        BriefInput(question="Q?", thesis="T.", target_duration_minutes=25),
    )
    await BriefService(database).mark_ready(brief.id)
    return brief.id


def _act(client, brief_id: UUID, action: str, **form: str) -> str:
    response = client.post(
        f"/studio/production/{brief_id}/actions/{action}",
        data=form or None,
        follow_redirects=False,
    )
    assert response.status_code == 303
    _wait_for_job(brief_id)
    return str(response.headers["location"])


@pytest.mark.asyncio
async def test_steps_follow_one_order_and_mark_stale_work(
    studio_client,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, url = studio_client
    _seed(client)
    database = Database(url)
    monkeypatch.setattr(factory, "_apimaster_provider", lambda **_: _Provider())
    try:
        brief_id = await _brief_with_material(database)
        production = ProductionService(database)

        expected = [
            "plan_research",
            "build_evidence",
            "freeze_research",
            "build_argument",
            "build_narrative",
            "build_master",
        ]
        for action in expected:
            state = await production.state_for_brief(brief_id)
            assert state.next_action == action
            assert "error=" not in _act(client, brief_id, action)

        state = await production.state_for_brief(brief_id)
        assert state.next_action == "build_script"
        # Research is final once frozen.
        assert "plan_research" not in state.allowed_actions
        assert "build_evidence" not in state.allowed_actions

        # Rebuilding the argument makes narrative + master outdated and
        # blocks everything built on top of them.
        _act(client, brief_id, "build_argument")
        state = await production.state_for_brief(brief_id)
        assert state.stage_states[ProductionStage.NARRATIVE] is StageHealth.STALE
        assert state.stage_states[ProductionStage.MASTER] is StageHealth.STALE
        assert "build_master" not in state.allowed_actions
        assert "build_script" not in state.allowed_actions
        assert state.next_action == "build_narrative"
        page = client.get(f"/studio/production/{brief_id}")
        assert "Veraltet" in page.text

        # An action that is not allowed right now is refused by the server.
        location = _act(client, brief_id, "build_script")
        assert "nicht%20m%C3%B6glich" in location
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_missing_api_key_becomes_readable_job_error(
    studio_client,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, url = studio_client
    _seed(client)
    database = Database(url)
    try:
        brief_id = await _brief_with_material(database)
        for action in ("plan_research", "build_evidence", "freeze_research"):
            _act(client, brief_id, action)
        response = client.post(
            f"/studio/production/{brief_id}/actions/build_argument",
            follow_redirects=False,
        )
        assert response.status_code == 303
        while jobs.is_running(  # noqa: ASYNC110 — job runs in the app's loop
            str(brief_id)
        ):
            await asyncio.sleep(0.05)
        job = jobs.get(str(brief_id))
        assert job is not None and job.error is not None
        assert "APIMaster-API-Key" in job.error
        page = client.get(f"/studio/production/{brief_id}")
        assert "APIMaster-API-Key" in page.text
        assert "Internal Server Error" not in page.text
        jobs.clear(str(brief_id))
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_topic_without_material_stops_at_first_step(
    studio_client,  # noqa: F811
) -> None:
    client, url = studio_client
    _seed(client)
    database = Database(url)
    try:
        channels = EditorialChannelService(database)
        channel = await channels.get_channel("emtedad")
        active = next(
            s
            for s in await channels.list_strategies(channel.id)
            if s.status.value == "ACTIVE"
        )
        candidate = await TopicService(database).create_manual(
            channel.id, active.id, question="Ohne Material?"
        )
        brief = await BriefService(database).create_for_candidate(
            candidate.id,
            BriefInput(
                question="Ohne Material?", thesis="T.", target_duration_minutes=25
            ),
        )
        await BriefService(database).mark_ready(brief.id)
        client.post(
            f"/studio/production/{brief.id}/actions/plan_research",
            follow_redirects=False,
        )
        while jobs.is_running(  # noqa: ASYNC110 — job runs in the app's loop
            str(brief.id)
        ):
            await asyncio.sleep(0.05)
        job = jobs.get(str(brief.id))
        assert job is not None and job.error is not None
        assert "kein Quellmaterial" in job.error
        state = await ProductionService(database).state_for_brief(brief.id)
        assert state.next_action == "plan_research"  # nothing half-built
        jobs.clear(str(brief.id))
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_workspace_ignores_localized_drafts(
    studio_client,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A translated draft with a higher version number is never 'the script'."""

    client, url = studio_client
    _seed(client)
    database = Database(url)
    monkeypatch.setattr(factory, "_apimaster_provider", lambda **_: _Provider())
    try:
        brief_id = await _brief_with_material(database)
        for action in (
            "plan_research",
            "build_evidence",
            "freeze_research",
            "build_argument",
            "build_narrative",
            "build_master",
        ):
            _act(client, brief_id, action)
        state = await ProductionService(database).state_for_brief(brief_id)
        async with database.transaction() as session:
            from app.content_engine.models import NarrativePlan

            narrative = await session.get(NarrativePlan, state.latest_narrative_id)
            assert narrative is not None
            persian = ScriptDraft(
                content_brief_id=brief_id,
                narrative_plan_id=narrative.id,
                lecture_master_version_id=state.latest_master_id,
                language="fa",
                lineage="primary",
                version_number=1,
                text="متن فارسی",
                content_hash=hashlib.sha256(b"fa").hexdigest(),
                target_duration_minutes=25,
                status=DraftStatus.DRAFT,
                provenance_json={},
            )
            arabic = ScriptDraft(
                content_brief_id=brief_id,
                narrative_plan_id=narrative.id,
                lecture_master_version_id=state.latest_master_id,
                language="ar",
                lineage="localized",
                version_number=7,
                text="نص عربي مترجم",
                content_hash=hashlib.sha256(b"ar").hexdigest(),
                target_duration_minutes=25,
                status=DraftStatus.DRAFT,
                provenance_json={},
            )
            session.add_all([persian, arabic])
        from app.web.studio_routes import _latest_draft_id

        latest = await _latest_draft_id(database, brief_id)
        async with database.transaction() as session:
            chosen = await session.get(ScriptDraft, latest)
            assert chosen is not None and chosen.lineage == "primary"
        page = client.get(f"/studio/production/{brief_id}?stage=SCRIPT")
        assert "نص عربي مترجم" not in page.text
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_production_pages_do_not_leak_connections(
    studio_client,  # noqa: F811
) -> None:
    client, url = studio_client
    _seed(client)
    database = Database(url)
    try:
        brief_id = await _brief_with_material(database)
        before = database.engine.pool.checkedout()
        for _ in range(5):
            await ProductionService(database).state_for_brief(brief_id)
        assert database.engine.pool.checkedout() == before
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_localize_runs_the_native_pipeline(
    studio_client,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'Übersetzen' drives NativeLocalizationRunner for the chosen language."""

    client, url = studio_client
    _seed(client)
    database = Database(url)
    calls: list[tuple[UUID, str]] = []

    async def fake_run(self, brief_id, language):  # type: ignore[no-untyped-def]
        calls.append((brief_id, language.value))

    import app.localization.runner as runner_module
    import app.production.service as production_module

    monkeypatch.setattr(
        runner_module.NativeLocalizationRunner, "run_language", fake_run
    )
    original = production_module.ProductionService.state_for_brief

    async def approved_state(self, brief_id):  # type: ignore[no-untyped-def]
        state = await original(self, brief_id)
        from dataclasses import replace

        return replace(state, allowed_actions=(*state.allowed_actions, "localize"))

    monkeypatch.setattr(
        production_module.ProductionService, "state_for_brief", approved_state
    )
    try:
        brief_id = await _brief_with_material(database)
        _act(client, brief_id, "localize", language="ar")
        assert calls == [(brief_id, "ar")]
        location = _act(client, brief_id, "localize", language="xx")
        assert "error=" in location
    finally:
        await database.dispose()
