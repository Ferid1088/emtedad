"""Shared test fixtures."""

from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.config import Environment, Settings


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Return explicit settings without reading developer environment state."""

    return Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(
            "postgresql+psycopg://emtedad:test-only@127.0.0.1:5432/emtedad"
        ),
        storage_root=tmp_path / "storage",
        log_level="INFO",
        log_json=True,
    )
