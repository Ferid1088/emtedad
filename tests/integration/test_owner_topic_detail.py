import asyncio
import os
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.content_strategy.models import (
    ContentTopic,
    EditorialProject,
    TopicSuggestionBatch,
)
from app.core.config import Environment, Settings
from app.db.session import Database
from app.main import create_app
from app.research.models import ResearchProject
from app.web.service import TopicAnalysisService


@pytest.mark.integration
def test_topic_detail_renders_current_and_older_phase10_topics() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    database = Database(database_url)

    async def topics() -> list[tuple[UUID, str]]:
        async with database.transaction() as session:
            rows = list(
                await session.scalars(
                    select(ContentTopic).order_by(ContentTopic.id.desc()).limit(2)
                )
            )
            return [(row.id, row.title) for row in rows]

    records = asyncio.run(topics())
    if len(records) < 2:
        pytest.skip("development corpus needs two Phase 10 topics")
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(database_url),
        storage_root=Path("/tmp/emtedad-owner-web-test"),
    )
    with TestClient(create_app(settings)) as client:
        for topic_id, title in records:
            response = client.get(f"/topics/{topic_id}")
            assert response.status_code == 200
            assert title in response.text

    asyncio.run(database.dispose())


@pytest.mark.integration
def test_topic_analysis_is_persisted_and_refreshable() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    database = Database(database_url)

    async def first_topic() -> tuple[UUID, str]:
        async with database.transaction() as session:
            topic = await session.scalar(select(ContentTopic).order_by(ContentTopic.id))
            assert topic is not None
            return topic.id, topic.title

    topic_id, title = asyncio.run(first_topic())
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(database_url),
        storage_root=Path("/tmp/emtedad-owner-web-test"),
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(f"/topics/{topic_id}/analyze", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == f"/topics/{topic_id}?analysis=updated"
        detail = client.get(response.headers["location"])
        assert detail.status_code == 200
        assert title in detail.text
        assert "Analyse aktualisieren" in detail.text
        assert "Analyse aktualisiert" in detail.text

        created = client.post(
            "/topics/save",
            data={
                "title": "Temporäres Analysenthema",
                "question": "Warum verändern sich Muster?",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        created_id = created.headers["location"].rsplit("/", 1)[-1]
        refresh_response = client.post(
            f"/topics/{created_id}/analyze", follow_redirects=False
        )
        assert refresh_response.status_code == 303
        assert refresh_response.headers["location"] == (
            f"/topics/{created_id}?analysis=updated"
        )
        assert (
            "Analyse aktualisiert"
            in client.get(refresh_response.headers["location"]).text
        )

    async def remove_temporary_topic() -> None:
        async with database.transaction() as session:
            topic = await session.get(ContentTopic, UUID(created_id))
            if topic is not None:
                await session.delete(topic)

    asyncio.run(remove_temporary_topic())

    async def refreshed() -> tuple[dict[str, object] | None, str | None]:
        async with database.transaction() as session:
            topic = await session.get(ContentTopic, topic_id)
            assert topic is not None
            return topic.analysis_json, topic.primary_concept_key

    analysis, primary = asyncio.run(refreshed())
    assert analysis is not None
    concepts = analysis.get("concepts", [])
    if not concepts:
        assert primary is None
    else:
        assert isinstance(concepts, list)
        first = concepts[0]
        assert isinstance(first, dict)
        assert primary == first["stable_key"]
    asyncio.run(database.dispose())


@pytest.mark.integration
def test_topic_analysis_does_not_fabricate_concept_for_unmatched_text() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    database = Database(database_url)

    async def analyze() -> dict[str, object]:
        async with database.transaction() as session:
            return await TopicAnalysisService().analyze(
                session, "qzxv-unmatched-topic-83917"
            )

    result = asyncio.run(analyze())
    assert result["primary_concept_key"] is None
    assert result["concepts"] == []
    warnings = result["warnings"]
    assert isinstance(warnings, list)
    assert "Keine belastbare Zuordnung gefunden." in warnings
    asyncio.run(database.dispose())


@pytest.mark.integration
def test_dynamic_topics_enter_the_canonical_editorial_workflow() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    database = Database(database_url)
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(database_url),
        storage_root=Path("/tmp/emtedad-owner-web-test"),
    )
    created_ids: list[UUID] = []
    project_ids: list[UUID] = []
    with TestClient(create_app(settings)) as client:
        for origin in ("USER_CREATED", "AI_SUGGESTED"):
            response = client.post(
                "/topics/save",
                data={
                    "title": f"Temporäres {origin}-Thema",
                    "question": (
                        "Wie kann ein Muster nach der Einsicht anders weitergehen?"
                    ),
                    "origin": origin,
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            topic_id = UUID(response.headers["location"].rsplit("/", 1)[-1])
            created_ids.append(topic_id)
            detail = client.get(f"/topics/{topic_id}")
            assert detail.status_code == 200
            assert "Recherche starten ist in dieser Phase bewusst deaktiviert" not in (
                detail.text
            )
            assert "Thema verwenden" in detail.text
            used = client.post(f"/topics/{topic_id}/use", follow_redirects=False)
            assert used.status_code == 303
            assert used.headers["location"].startswith("/workspace/")
            project_ids.append(UUID(used.headers["location"].rsplit("/", 1)[-1]))
            duplicate = client.post(f"/topics/{topic_id}/use", follow_redirects=False)
            assert duplicate.headers["location"] == used.headers["location"]

    async def verify_and_cleanup() -> None:
        async with database.transaction() as session:
            projects = list(
                await session.scalars(
                    select(EditorialProject).where(EditorialProject.id.in_(project_ids))
                )
            )
            assert len(projects) == 2
            assert all(project.content_topic_id in created_ids for project in projects)
            research_ids = [
                project.research_project_id
                for project in projects
                if project.research_project_id is not None
            ]
            await session.execute(
                delete(EditorialProject).where(EditorialProject.id.in_(project_ids))
            )
            await session.execute(
                delete(ResearchProject).where(ResearchProject.id.in_(research_ids))
            )
            await session.execute(
                delete(ContentTopic).where(ContentTopic.id.in_(created_ids))
            )

    asyncio.run(verify_and_cleanup())
    asyncio.run(database.dispose())


@pytest.mark.integration
def test_topic_discovery_batches_and_workspace_actions() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    database = Database(database_url)
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(database_url),
        storage_root=Path("/tmp/emtedad-owner-web-test"),
    )
    batch_id: UUID | None = None
    topic_ids: list[UUID] = []
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/topics/suggestions",
            data={"requested_count": "3", "owner_instruction": "Beziehungen"},
        )
        assert response.status_code == 200
        assert "Neue Themen generieren" in response.text
        assert "AI_SUGGESTED" not in response.text

    async def inspect_batch() -> None:
        nonlocal batch_id, topic_ids
        async with database.transaction() as session:
            batch = await session.scalar(
                select(TopicSuggestionBatch).order_by(
                    TopicSuggestionBatch.created_at.desc()
                )
            )
            assert batch is not None
            batch_id = batch.id
            topics = list(
                await session.scalars(
                    select(ContentTopic).where(
                        ContentTopic.suggestion_batch_id == batch.id
                    )
                )
            )
            assert len(topics) == 3
            topic_ids = [topic.id for topic in topics]

    asyncio.run(inspect_batch())
    assert topic_ids
    with TestClient(create_app(settings)) as client:
        assert (
            client.post(
                f"/topics/{topic_ids[0]}/later", follow_redirects=False
            ).status_code
            == 303
        )
        assert (
            client.post(
                f"/topics/{topic_ids[0]}/archive", follow_redirects=False
            ).status_code
            == 303
        )
        assert (
            client.post(
                f"/topics/{topic_ids[0]}/restore", follow_redirects=False
            ).status_code
            == 303
        )

    async def cleanup() -> None:
        async with database.transaction() as session:
            await session.execute(
                delete(ContentTopic).where(ContentTopic.id.in_(topic_ids))
            )
            if batch_id is not None:
                batch = await session.get(TopicSuggestionBatch, batch_id)
                if batch is not None:
                    await session.delete(batch)

    asyncio.run(cleanup())
    asyncio.run(database.dispose())
