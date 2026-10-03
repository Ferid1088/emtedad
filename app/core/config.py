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
    llm_provider: Literal["devin"] | None = None
    devin_api_key: SecretStr | None = None
    # Bounded in-call retry for transient 429s; hard quota is never retried.
    devin_rate_limit_max_attempts: int = 3
    devin_rate_limit_initial_backoff_seconds: float = 20.0
    devin_rate_limit_max_backoff_seconds: float = 120.0
    speech_structure_concurrency: int = 2
    speech_structure_scan_interval_seconds: int = 300
    speech_structure_max_attempts: int = 3
    speech_structure_retry_backoff_seconds: int = 300
    speech_structure_quota_backoff_seconds: int = 1800
    # Soft quality warnings for KnowledgeUnit granularity (review triggers,
    # not hard splitting boundaries).
    unit_soft_max_duration_seconds: int = 180
    unit_soft_max_words: int = 1300
    youtube_mcp_enabled: bool = False
    youtube_mcp_url: str = "http://127.0.0.1:8790"
    youtube_mcp_timeout_seconds: int = 60

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
