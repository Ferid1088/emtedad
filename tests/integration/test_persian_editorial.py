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
from app.lecture.models import LectureClaim, LectureMasterVersion
from app.main import create_app


@pytest.mark.integration
def test_persian_drafts_are_researched_versioned_and_owner_approvable() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    database = Database(database_url)

    async def seed() -> tuple[UUID, UUID]:
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
                title="Temporärer persischer Redaktionslauf",
                human_question=master.central_human_question,
                status="RESEARCH_PENDING",
            )
            session.add(project)
            await session.flush()
            return project.id, master.id

    project_id, master_id = asyncio.run(seed())
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(database_url),
        storage_root=Path("/tmp/emtedad-persian-editorial-test"),
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            f"/workspace/{project_id}/persian/drafts",
            data={
                "semantic_master_id": str(master_id),
                "target_duration_minutes": "15",
                "draft_count": "3",
                "owner_prompt": "Ruhig und verständlich.",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    async def drafts() -> list[PersianDraft]:
        async with database.transaction() as session:
            return list(
                await session.scalars(
                    select(PersianDraft).where(
                        PersianDraft.editorial_project_id == project_id
                    )
                )
            )

    created = asyncio.run(drafts())
    assert len(created) == 3
    first = sorted(created, key=lambda item: item.variant_index)[0]
    with TestClient(create_app(settings)) as client:
        edited = client.post(
            f"/workspace/{project_id}/persian/drafts/{first.id}/edit",
            data={"text": "در چارچوب آیین امتداد، این متن ویرایش مالک است."},
            follow_redirects=False,
        )
        assert edited.status_code == 303
        latest_id = asyncio.run(_latest_id(database, project_id, first.variant_index))
        assert latest_id != first.id
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
