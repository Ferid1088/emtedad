"""Configuration validation and redaction tests."""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Environment, Settings


def test_required_settings_are_not_silently_defaulted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in (
        "EMTEDAD_ENVIRONMENT",
        "EMTEDAD_DATABASE_URL",
        "EMTEDAD_STORAGE_ROOT",
    ):
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_database_secret_is_redacted_from_representations(tmp_path: Path) -> None:
    sentinel = "database-password-sentinel"
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(
            f"postgresql+psycopg://emtedad:{sentinel}@localhost/emtedad"
        ),
        storage_root=tmp_path,
    )

    assert sentinel not in repr(settings)
    assert sentinel not in str(settings)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://localhost/emtedad",
        "sqlite:///emtedad.db",
        "not-a-url",
    ],
)
def test_database_url_requires_psycopg(database_url: str, tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match=r"postgresql\+psycopg"):
        Settings(
            _env_file=None,
            environment=Environment.TEST,
            database_url=SecretStr(database_url),
            storage_root=tmp_path,
        )


def test_storage_root_must_be_absolute() -> None:
    with pytest.raises(ValidationError, match="absolute"):
        Settings(
            _env_file=None,
            environment=Environment.TEST,
            database_url=SecretStr(
                "postgresql+psycopg://emtedad:test@localhost/emtedad"
            ),
            storage_root=Path("relative/storage"),
        )


def test_production_rejects_temporary_storage() -> None:
    with pytest.raises(ValidationError, match="production storage"):
        Settings(
            _env_file=None,
            environment=Environment.PRODUCTION,
            database_url=SecretStr(
                "postgresql+psycopg://emtedad:test@database/emtedad"
            ),
            storage_root=Path("/tmp/emtedad-production"),
        )
