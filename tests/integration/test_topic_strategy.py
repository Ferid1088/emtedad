import os
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Environment, Settings
from app.main import create_app


@pytest.mark.integration
def test_strategy_tree_owner_workflow_is_retired() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(database_url),
        storage_root=Path("/tmp/emtedad-topic-strategy-test"),
    )
    retired_id = UUID("00000000-0000-0000-0000-000000000001")
    with TestClient(create_app(settings)) as client:
        requests = (
            client.get("/strategy", follow_redirects=False),
            client.post("/strategy/generate", follow_redirects=False),
            client.post(f"/strategy/{retired_id}/approve", follow_redirects=False),
            client.get(f"/strategy/topics/{retired_id}", follow_redirects=False),
            client.post(f"/strategy/topics/{retired_id}/use", follow_redirects=False),
        )
        for response in requests:
            assert response.status_code == 303
            assert response.headers["location"] == "/lessons"

        lessons = client.get("/lessons")
        assert lessons.status_code == 200
        assert "100-Lektionen-Kanon" in lessons.text

        topics = client.get("/topics")
        assert topics.status_code == 200
        assert "Freie Themen" in topics.text
        assert 'href="/strategy"' not in topics.text
