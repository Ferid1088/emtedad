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
    # Bounded in-call retry for transient 429s and hard quota; quota
    # contention clears in minutes (foreign sessions share the account cap),
    # so both classes back off rather than fail on the first hit.
    devin_rate_limit_max_attempts: int = 5
    devin_rate_limit_initial_backoff_seconds: float = 20.0
    devin_rate_limit_max_backoff_seconds: float = 120.0
    provider_max_concurrency: int = 5
    provider_background_max_concurrency: int = 2
    background_processing_paused: bool = False
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
    # Owner-configurable web research. Provider-agnostic: "openrouter" calls a
    # chat-completions endpoint with web-search annotations, "tavily" calls a
    # search endpoint, "custom" posts {query} to base_url and parses common
    # result shapes. Owner overrides persist in the owner_settings table.
    web_research_enabled: bool = False
    web_research_provider: Literal["openrouter", "tavily", "custom"] = "openrouter"
    web_research_base_url: str = "https://openrouter.ai/api/v1"
    web_research_api_key: SecretStr | None = None
    web_research_model: str = "openai/gpt-4o-mini:online"
    web_research_max_results: int = 5
    web_research_timeout_seconds: int = 90
    web_research_max_page_bytes: int = 1_500_000
    # Video length target (minutes): plan at 27.5, accept 25–30.
    # These three settings are the single source of truth for the duration
    # band — services must read them, never hardcode the numbers.
    target_duration_default_minutes: float = 27.5
    target_duration_min_minutes: float = 25.0
    target_duration_max_minutes: float = 30.0
    # Maximum automatic critic→revision loops before OWNER_REVIEW_REQUIRED.
    max_revision_rounds: int = 3
    # First-draft generation tolerance band around the planning target:
    # a draft outside [target × min_ratio, target × max_ratio] is a
    # generation defect and triggers bounded corrective generation before
    # review — it must not consume semantic revision rounds.
    first_draft_min_duration_ratio: float = 0.85
    first_draft_max_duration_ratio: float = 1.15
    # Bounded automatic generation-correction attempts per build_script;
    # afterwards the draft is marked GENERATION_REVIEW_REQUIRED.
    generation_max_correction_attempts: int = 2
    # Rough material estimate: usable knowledge units needed per video minute
    # before gap research is suggested/triggered.
    units_per_video_minute: float = 1.5
    # Spoken words per minute per draft language — drives the duration band
    # check and the estimated_duration_seconds stored on each ScriptDraft.
    speech_wpm_fa: int = 110
    speech_wpm_en: int = 140
    speech_wpm_de: int = 130
    speech_wpm_ar: int = 120

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
