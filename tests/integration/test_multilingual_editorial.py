import asyncio
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.content_strategy.models import (
    EditorialLanguageTrack,
    EditorialProject,
    PersianDraft,
)
from app.content_strategy.multilingual_service import MultilingualEditorialService
from app.core.config import Environment, Settings
from app.db.session import Database
from app.lecture.models import LectureClaim, LectureMasterVersion
from app.main import create_app


@pytest.mark.integration
def test_approved_persian_is_exact_source_for_tracks_and_voice() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    database = Database(database_url)

    async def run() -> None:
        async with database.transaction() as session:
            master = await session.scalar(
                select(LectureMasterVersion)
                .join(
                    LectureClaim,
                    LectureClaim.lecture_master_version_id == LectureMasterVersion.id,
                )
                .where(LectureMasterVersion.status == "READY")
                .where(LectureClaim.semantic_proposition.is_not(None))
                .order_by(LectureMasterVersion.created_at)
            )
            assert master is not None
            project = EditorialProject(
                title="Temporärer multilingualer Lauf",
                human_question=master.central_human_question,
            )
            session.add(project)
            await session.flush()
            text = "در چارچوب آیین امتداد، این متنِ تأییدشده منبع چهار زبان است."
            draft = PersianDraft(
                editorial_project_id=project.id,
                semantic_master_id=master.id,
                version_number=1,
                variant_index=1,
                text=text,
                status="PERSIAN_APPROVED",
                target_duration_minutes=5,
                target_word_count_min=495,
                target_word_count_max=605,
                actual_word_count=10,
                estimated_duration_seconds=5,
                provenance={"test": True},
            )
            session.add(draft)
            await session.flush()
            draft_id, project_id = draft.id, project.id

        service = MultilingualEditorialService(database)
        track_ids = await service.create(draft_id, ("fa",))
        assert len(track_ids) == 1
        await service.prepare_voice(track_ids[0])

        async with database.transaction() as session:
            track = await session.get(EditorialLanguageTrack, track_ids[0])
            assert track is not None
            assert track.display_text == text
            assert track.voice_ready_text == text
            assert track.source_persian_draft_id == draft_id
            await session.execute(
                delete(EditorialLanguageTrack).where(
                    EditorialLanguageTrack.editorial_project_id == project_id
                )
            )
            await session.delete(draft)
            await session.flush()
            await session.delete(project)

    asyncio.run(run())
    asyncio.run(database.dispose())


@pytest.mark.integration
def test_standalone_voice_preparation_needs_no_topic() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(database_url),
        storage_root=Path("/tmp/emtedad-voice-test"),
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/studio/voice", data={"language": "fa", "text": "آیین امتداد"}
        )
    assert response.status_code == 200
    assert "آیین امتداد" in response.text
