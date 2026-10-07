"""Build the voice service from settings (+ owner overrides)."""

from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.db.session import Database
from app.voice.elevenlabs import ElevenLabsClient
from app.voice.render import VoiceConfig, VoiceRenderService


def build_voice_service(
    database: Database, effective: dict[str, Any], storage_root: Path | None = None
) -> VoiceRenderService:
    from app.knowledge.llm.factory import resolve_llm_provider
    from app.knowledge.llm.roles import AgentRole
    from app.voice.listener import get_listener
    from app.voice.pronunciation_key import PronunciationKeyEditor

    settings = get_settings()
    key = (
        settings.elevenlabs_api_key.get_secret_value()
        if settings.elevenlabs_api_key
        else ""
    )
    config = VoiceConfig(
        voice_ids={
            code: str(
                effective.get(f"voice_id_{code}")
                or getattr(settings, f"voice_id_{code}")
            )
            for code in ("fa", "de", "en", "ar")
        },
        model_id=str(effective.get("voice_model_id") or settings.voice_model_id),
        concurrency=int(
            str(effective.get("voice_concurrency") or settings.voice_concurrency)
        ),
        check_languages=tuple(settings.pronunciation_languages),
        max_rounds=int(
            str(
                effective.get("pronunciation_max_rounds")
                or settings.pronunciation_max_rounds
            )
        ),
    )
    model_name = settings.pronunciation_phoneme_model
    return VoiceRenderService(
        database,
        ElevenLabsClient(key),
        config,
        storage_root or settings.storage_root,
        key_editor=PronunciationKeyEditor(
            resolve_llm_provider(role=AgentRole.PRONUNCIATION_EDITOR)
        ),
        listener_factory=lambda: get_listener(model_name),
    )
