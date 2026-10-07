"""Workspace voice section: start a recording job, show audio + QA."""

import asyncio
import hashlib
import json

import pytest

import app.knowledge.llm.factory as factory
from app.content_engine.domain import DraftStatus
from app.content_engine.models import NarrativePlan, ScriptDraft
from app.db.session import Database
from app.production.service import ProductionService
from app.web.jobs import jobs
from tests.integration.test_process_logic import _act, _brief_with_material
from tests.integration.test_studio_ui import _seed, studio_client  # noqa: F401
from tests.integration.test_topics import _Provider

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_voice_section_records_and_shows_quality(
    studio_client,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            narrative = await session.get(NarrativePlan, state.latest_narrative_id)
            assert narrative is not None
            session.add(
                ScriptDraft(
                    content_brief_id=brief_id,
                    narrative_plan_id=narrative.id,
                    lecture_master_version_id=state.latest_master_id,
                    language="fa",
                    lineage="primary",
                    version_number=1,
                    text="او در ملک خدا سیر می‌کرد.",
                    content_hash=hashlib.sha256(b"x").hexdigest(),
                    target_duration_minutes=25,
                    status=DraftStatus.APPROVED,
                    provenance_json={},
                )
            )

        storage = client.app.state.settings.storage_root  # type: ignore[attr-defined]
        calls: list[str] = []

        class _Service:
            async def render(self, brief, language):  # type: ignore[no-untyped-def]
                calls.append(language)
                out = storage / "voice" / str(brief) / language
                out.mkdir(parents=True, exist_ok=True)
                (out / "full.mp3").write_bytes(b"ID3")
                (out / "manifest.json").write_text(
                    json.dumps(
                        {
                            "blocks": [{"index": 0}],
                            "created_at": "2026-10-07T10:00",
                            "note": "",
                            "unresolved": ["ملک"],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return {}

        monkeypatch.setattr(
            "app.voice.factory.build_voice_service", lambda *a, **k: _Service()
        )
        response = client.post(
            f"/studio/production/{brief_id}/voice/fa", follow_redirects=False
        )
        assert response.status_code == 303
        key = f"{brief_id}:voice:fa"
        while jobs.is_running(key):  # noqa: ASYNC110 — job runs in the app loop
            await asyncio.sleep(0.05)
        assert jobs.get(key) is not None and jobs.get(key).error is None  # type: ignore[union-attr]
        assert calls == ["fa"]
        page = client.get(f"/studio/production/{brief_id}?stage=APPROVED")
        assert "Vertonung" in page.text
        assert f"/studio/production/{brief_id}/voice/fa/full.mp3" in page.text
        assert "bitte anhören" in page.text and "ملک" in page.text
        audio = client.get(f"/studio/production/{brief_id}/voice/fa/full.mp3")
        assert audio.status_code == 200 and audio.content == b"ID3"
        bad = client.get(f"/studio/production/{brief_id}/voice/fa/..%2Fmanifest.json")
        assert bad.status_code == 404
    finally:
        await database.dispose()
