import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Environment, Settings
from app.main import create_app


@pytest.mark.integration
def test_dashboard_uses_shared_owner_layout_and_css() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(database_url),
        storage_root=Path("/tmp/emtedad-owner-dashboard-test"),
    )
    with TestClient(create_app(settings)) as client:
        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert 'href="/static/owner.css"' in dashboard.text
        assert '<header class="site-header">' in dashboard.text
        assert 'href="/lessons"' in dashboard.text
        assert 'href="/strategy"' not in dashboard.text
        lesson_counts = {
            key: int(value)
            for key, value in re.findall(
                r'data-lesson-metric="([^"]+)" data-value="(\d+)"',
                dashboard.text,
            )
        }
        assert sum(lesson_counts.values()) == 100
        assert 'class="card"' in dashboard.text

        stylesheet = client.get("/static/owner.css")
        assert stylesheet.status_code == 200
        assert stylesheet.headers["content-type"].startswith("text/css")
        assert "font-family" in stylesheet.text
        assert "background: #16262d" in stylesheet.text

        sources = client.get("/sources")
        assert sources.status_code == 200
        assert 'href="/static/owner.css"' in sources.text
