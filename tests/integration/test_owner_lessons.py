import asyncio
import os
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.content_strategy.models import EditorialProject, PersianDraft
from app.core.config import Environment, Settings
from app.db.session import Database
from app.lecture.models import LectureMasterVersion
from app.main import create_app


@pytest.mark.integration
def test_owner_lesson_workflow_and_published_only_memory() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    database = Database(database_url)
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(database_url),
        storage_root=Path("/tmp/emtedad-owner-lessons-test"),
    )

    with TestClient(create_app(settings)) as client:
        library = client.get("/lessons")
        assert library.status_code == 200
        assert library.text.count("data-lesson-id=") == 100
        assert "837" in library.text
        assert "22 Kernbegriffe" in library.text

        searched = client.get("/lessons", params={"q": "آیین امتداد چیست و چه نیست"})
        assert searched.status_code == 200
        assert 'data-lesson-id="1.1"' in searched.text
        assert searched.text.count("data-lesson-id=") < 100

        browser_form_search = client.get(
            "/lessons",
            params={
                "q": "بُن",
                "status": "",
                "concept": "",
                "prerequisites": "ALL",
                "number_from": "",
                "number_to": "",
            },
        )
        assert browser_form_search.status_code == 200
        assert 'data-lesson-id="3.1"' in browser_form_search.text

        filtered = client.get("/lessons", params={"concept": "3.1"})
        assert filtered.status_code == 200
        assert 'data-lesson-id="3.1"' in filtered.text

        detail = client.get("/lessons/3.1")
        assert detail.status_code == 200
        assert "Kanonische Lektionserklärung" in detail.text
        assert "Voraussetzungen" in detail.text
        assert 'href="/lessons/2.1"' in detail.text

        started = client.post("/lessons/3.1/projects", follow_redirects=False)
        assert started.status_code == 303
        project_id = UUID(started.headers["location"].rsplit("/", 1)[-1])

        workspace = client.get(started.headers["location"])
        assert workspace.status_code == 200
        assert "Lektion 11 / 100" in workspace.text
        assert "Ayin-Kern" in workspace.text
        assert "Externe Recherche" in workspace.text
        assert "kein automatisches Ayin-Book-RAG" in workspace.text
        assert "Im Ayin-Buch suchen" not in workspace.text

        texts = client.get("/texts")
        assert texts.status_code == 200
        assert "Lektion 11 / 100" in texts.text
        assert "بُن" in texts.text

        unpublished_archive = client.get("/archive")
        assert unpublished_archive.status_code == 200
        assert "بُن" not in unpublished_archive.text

    asyncio.run(_add_approved_fixture(database, project_id))

    with TestClient(create_app(settings)) as client:
        published = client.post(f"/texts/{project_id}/publish", follow_redirects=False)
        assert published.status_code == 303
        memory = client.get("/archive")
        assert memory.status_code == 200
        assert "بُن" in memory.text
        assert "Lektion 11 / 100" in memory.text

        topics = client.get("/topics")
        assert topics.status_code == 200
        assert "Freie Themen" in topics.text
        assert "Themenbaum öffnen" not in topics.text

    asyncio.run(_cleanup(database, project_id))
    asyncio.run(database.dispose())


async def _add_approved_fixture(database: Database, project_id: UUID) -> None:
    async with database.transaction() as session:
        master = await session.scalar(select(LectureMasterVersion).limit(1))
        assert master is not None
        session.add(
            PersianDraft(
                editorial_project_id=project_id,
                semantic_master_id=master.id,
                version_number=1,
                variant_index=1,
                text="متن فارسی تأییدشده برای آزمون امن انتشار.",
                status="PERSIAN_APPROVED",
                owner_prompt=None,
                target_duration_minutes=5,
                target_word_count_min=1,
                target_word_count_max=1000,
                actual_word_count=7,
                estimated_duration_seconds=15,
                provenance={"fixture": "owner-lesson-ui"},
            )
        )


async def _cleanup(database: Database, project_id: UUID) -> None:
    async with database.transaction() as session:
        await session.execute(
            delete(PersianDraft).where(PersianDraft.editorial_project_id == project_id)
        )
        project = await session.get(EditorialProject, project_id)
        if project is not None:
            await session.delete(project)
