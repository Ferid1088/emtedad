import asyncio
import os
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from app.content_strategy.models import ContentTopic
from app.core.config import Environment, Settings
from app.db.session import Database
from app.main import create_app
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
        detail = client.get(f"/topics/{topic_id}")
        assert detail.status_code == 200
        assert title in detail.text
        assert "Analyse aktualisieren" in detail.text

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
