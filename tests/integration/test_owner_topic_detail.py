import asyncio
import os
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.content_strategy.models import (
    ContentTopic,
)
from app.core.config import Environment, Settings
from app.db.session import Database
from app.main import create_app
from app.web.service import TopicAnalysisService


def _sync_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _url_for_database(url: str, database: str) -> str:
    return make_url(url).set(database=database).render_as_string(hide_password=False)


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
