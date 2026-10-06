"""Owner settings service: DB overrides on top of environment defaults."""

from typing import Any

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.db.session import Database
from app.ops.settings.models import OwnerSetting

# Setting keys the owner may edit in the UI. Every key maps to a Settings
# field; the DB row overrides the environment default when present.
EDITABLE_KEYS: tuple[str, ...] = (
    "web_research_enabled",
    "web_research_provider",
    "web_research_base_url",
    "web_research_api_key",
    "web_research_model",
    "web_research_max_results",
    "web_research_timeout_seconds",
    "target_duration_default_minutes",
    "target_duration_min_minutes",
    "target_duration_max_minutes",
    "max_revision_rounds",
    "first_draft_min_duration_ratio",
    "first_draft_max_duration_ratio",
    "generation_max_correction_attempts",
    "units_per_video_minute",
    "speech_wpm_fa",
    "speech_wpm_en",
    "speech_wpm_de",
    "speech_wpm_ar",
    "background_processing_paused",
    "model_role_high_volume",
    "model_role_reasoning",
    "model_role_editorial",
    "model_role_premium",
)


class StudioSettingsService:
    """Resolve owner-facing settings: DB override → env default."""

    def __init__(self, database: Database, settings: Settings | None = None) -> None:
        self.database = database
        self.settings = settings or get_settings()

    async def overrides(self) -> dict[str, Any]:
        async with self.database.transaction() as session:
            rows = (
                await session.scalars(
                    select(OwnerSetting).where(OwnerSetting.key.in_(EDITABLE_KEYS))
                )
            ).all()
        return {row.key: row.value for row in rows}

    async def effective(self) -> dict[str, Any]:
        """Current effective value for every editable key."""

        overrides = await self.overrides()
        effective: dict[str, Any] = {}
        for key in EDITABLE_KEYS:
            env_value = getattr(self.settings, key)
            if hasattr(env_value, "get_secret_value"):
                env_value = env_value.get_secret_value()
            effective[key] = overrides.get(key, env_value)
        return effective

    async def set_many(
        self, values: dict[str, Any], *, updated_by: str = "owner"
    ) -> None:
        """Persist owner overrides; ``None`` removes the override."""

        async with self.database.transaction() as session:
            for key, value in values.items():
                if key not in EDITABLE_KEYS:
                    raise ValueError(f"Unknown setting key: {key}")
                if value is not None:
                    value = self._coerce(key, value)
                row = await session.scalar(
                    select(OwnerSetting).where(OwnerSetting.key == key)
                )
                if value is None:
                    if row is not None:
                        await session.delete(row)
                    continue
                if row is None:
                    row = OwnerSetting(key=key, value=value, updated_by=updated_by)
                    session.add(row)
                else:
                    row.value = value
                    row.updated_by = updated_by

    def _coerce(self, key: str, value: Any) -> Any:
        """Coerce a submitted value to the Settings field type."""

        target = _KEY_TYPES[key]
        if target is bool and not isinstance(value, bool):
            return str(value).strip().lower() in {"1", "true", "on", "yes", "an"}
        if target in (int, float) and not isinstance(value, target):
            return target(value)
        return value


_KEY_TYPES: dict[str, type] = {
    "web_research_enabled": bool,
    "web_research_provider": str,
    "web_research_base_url": str,
    "web_research_api_key": str,
    "web_research_model": str,
    "web_research_max_results": int,
    "web_research_timeout_seconds": int,
    "target_duration_default_minutes": float,
    "target_duration_min_minutes": float,
    "target_duration_max_minutes": float,
    "max_revision_rounds": int,
    "first_draft_min_duration_ratio": float,
    "first_draft_max_duration_ratio": float,
    "generation_max_correction_attempts": int,
    "units_per_video_minute": float,
    "speech_wpm_fa": int,
    "speech_wpm_en": int,
    "speech_wpm_de": int,
    "speech_wpm_ar": int,
    "background_processing_paused": bool,
    "model_role_high_volume": str,
    "model_role_reasoning": str,
    "model_role_editorial": str,
    "model_role_premium": str,
}


_WPM_KEYS = {
    "fa": "speech_wpm_fa",
    "en": "speech_wpm_en",
    "de": "speech_wpm_de",
    "ar": "speech_wpm_ar",
}
_DEFAULT_WPM = 110


def speech_wpm(effective: dict[str, Any], language: str) -> int:
    """Owner-configured spoken rate for a language (words per minute)."""

    raw = effective.get(_WPM_KEYS.get(language, ""), _DEFAULT_WPM)
    try:
        return max(1, int(str(raw)))
    except (TypeError, ValueError):
        return _DEFAULT_WPM
