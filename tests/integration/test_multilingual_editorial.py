import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Environment, Settings
from app.main import create_app


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
