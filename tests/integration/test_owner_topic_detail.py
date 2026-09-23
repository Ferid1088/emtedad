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
