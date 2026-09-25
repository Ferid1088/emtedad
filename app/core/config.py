"""Typed application configuration loaded from environment variables."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Supported runtime environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Validated runtime settings; secrets remain redacted in representations."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="EMTEDAD_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Environment
    database_url: SecretStr
    storage_root: Path
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = True
    claude_oauth_token_work: SecretStr | None = None
    claude_oauth_token_personal: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        raw_url = value.get_secret_value()
        if not raw_url.startswith("postgresql+psycopg://"):
            raise ValueError("database URL must use postgresql+psycopg")
        return value

    @field_validator("storage_root")
    @classmethod
    def validate_storage_root(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("storage root must be an absolute path")
        return value

    @model_validator(mode="after")
    def reject_insecure_production_storage(self) -> Self:
        if (
            self.environment is Environment.PRODUCTION
            and self.storage_root.is_relative_to("/tmp")
        ):
            raise ValueError("production storage root cannot be under /tmp")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache process settings."""

    return Settings()
