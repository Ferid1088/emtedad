"""Shared test fixtures."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.config import Environment, Settings, get_settings

# Minimum process settings so code paths that call ``get_settings()`` work in a
# clean checkout without a developer ``.env``. Real environment values win.
_TEST_ENV_DEFAULTS = {
    "EMTEDAD_ENVIRONMENT": "test",
    "EMTEDAD_DATABASE_URL": (
        "postgresql+psycopg://emtedad:local-development-only@127.0.0.1:5432/emtedad"
    ),
    "EMTEDAD_STORAGE_ROOT": "/tmp/emtedad-test-storage",
}


@pytest.fixture(autouse=True)
def _default_process_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key, value in _TEST_ENV_DEFAULTS.items():
        if not os.environ.get(key):
            monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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
