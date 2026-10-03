import asyncio
import os
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.content_strategy.models import (
    EditorialProject,
    PersianDraft,
    PersianReviewFinding,
)
from app.core.config import Environment, Settings
from app.db.session import Database
from app.lecture.models import LectureMasterVersion
from app.main import create_app


@pytest.mark.integration
def test_historical_drafts_stay_editable_reviewable_and_approvable() -> None:
    """The lesson draft-generation POST is retired; draft maintenance remains."""

    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    database = Database(database_url)

    async def seed() -> UUID:
        async with database.transaction() as session:
            master = await session.scalar(select(LectureMasterVersion).limit(1))
            project = EditorialProject(
                title="Historischer persischer Redaktionslauf",
                human_question=(
                    master.central_human_question
                    if master is not None
                    else "Worum geht es?"
                ),
                status="RESEARCH_PENDING",
            )
            session.add(project)
            await session.flush()
            session.add(
                PersianDraft(
                    editorial_project_id=project.id,
                    semantic_master_id=(master.id if master is not None else None),
                    version_number=1,
                    variant_index=1,
                    text="در این متن تاریخی، پرسش انسانی همچنان باز می‌ماند.",
                    status="PERSIAN_DRAFT",
                    owner_prompt=None,
                    target_duration_minutes=15,
                    target_word_count_min=100,
                    target_word_count_max=2000,
                    actual_word_count=12,
                    estimated_duration_seconds=30,
                    provenance={"fixture": "phase21-retirement"},
                )
            )
            return project.id

    project_id = asyncio.run(seed())
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(database_url),
        storage_root=Path("/tmp/emtedad-persian-editorial-test"),
    )
    with TestClient(create_app(settings)) as client:
        # Retired: lesson-canon draft generation.
        assert client.post(
            f"/workspace/{project_id}/persian/drafts",
            data={
                "lesson_id": "1.1",
                "target_duration_minutes": "15",
                "draft_count": "1",
            },
            follow_redirects=False,
        ).status_code in {404, 405}

    async def first_draft_id() -> UUID:
        async with database.transaction() as session:
            draft = await session.scalar(
                select(PersianDraft).where(
                    PersianDraft.editorial_project_id == project_id
                )
            )
            assert draft is not None
            return draft.id

    first_id = asyncio.run(first_draft_id())
    with TestClient(create_app(settings)) as client:
        edited = client.post(
            f"/workspace/{project_id}/persian/drafts/{first_id}/edit",
            data={"text": "در چارچوب آیین امتداد، این متن ویرایش مالک است."},
            follow_redirects=False,
        )
        assert edited.status_code == 303
        latest_id = asyncio.run(_latest_id(database, project_id, 1))
        assert latest_id != first_id
        assert (
            client.post(
                f"/workspace/{project_id}/persian/drafts/{latest_id}/review",
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert (
            client.post(
                f"/workspace/{project_id}/persian/drafts/{latest_id}/approve",
                follow_redirects=False,
            ).status_code
            == 303
        )

    async def cleanup() -> None:
        async with database.transaction() as session:
            await session.execute(
                delete(PersianReviewFinding).where(
                    PersianReviewFinding.draft_id.in_(
                        select(PersianDraft.id).where(
                            PersianDraft.editorial_project_id == project_id
                        )
                    )
                )
            )
            await session.execute(
                delete(PersianDraft).where(
                    PersianDraft.editorial_project_id == project_id
                )
            )
            project = await session.get(EditorialProject, project_id)
            if project is not None:
                await session.delete(project)

    asyncio.run(cleanup())
    asyncio.run(database.dispose())


async def _latest_id(database: Database, project_id: UUID, variant: int) -> UUID:
    async with database.transaction() as session:
        draft = await session.scalar(
            select(PersianDraft)
            .where(
                PersianDraft.editorial_project_id == project_id,
                PersianDraft.variant_index == variant,
            )
            .order_by(PersianDraft.version_number.desc())
        )
        assert draft is not None
        return draft.id
