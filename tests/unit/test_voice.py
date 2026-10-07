"""Voice: ElevenLabs client, blocks, phonetics, render loop with listening."""

import base64
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.voice.elevenlabs import ElevenLabsClient, VoiceProviderError
from app.voice.phonetics import find_word, judge
from app.voice.pronunciation_key import PronunciationKey
from app.voice.render import VoiceConfig, VoiceRenderService, split_blocks


def _tts_transport(seen: list[dict[str, object]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/voices":
            return httpx.Response(
                200,
                json={
                    "voices": [
                        {
                            "voice_id": "v1",
                            "name": "Fereidoun FA",
                            "category": "cloned",
                            "labels": {"language": "fa"},
                        }
                    ]
                },
            )
        body = json.loads(request.content)
        seen.append(
            {
                "path": request.url.path,
                **body,
                "format": request.url.params.get("output_format"),
            }
        )
        text = body["text"]
        n = len(text)
        return httpx.Response(
            200,
            json={
                "audio_base64": base64.b64encode(b"ID3audio").decode(),
                "alignment": {
                    "characters": list(text),
                    "character_start_times_seconds": [i * 0.05 for i in range(n)],
                    "character_end_times_seconds": [(i + 1) * 0.05 for i in range(n)],
                },
            },
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_elevenlabs_client_sends_language_and_parses_timing() -> None:
    seen: list[dict[str, object]] = []
    client = ElevenLabsClient("k", transport=_tts_transport(seen))
    result = await client.synthesize("سلام", voice_id="v1", language_code="fa")
    assert seen[0]["path"] == "/v1/text-to-speech/v1/with-timestamps"
    assert seen[0]["language_code"] == "fa" and seen[0]["model_id"] == "eleven_v3"
    assert result.audio == b"ID3audio"
    assert result.alignment["characters"] == list("سلام")
    voices = await client.list_voices()
    assert voices[0].name == "Fereidoun FA"


@pytest.mark.asyncio
async def test_elevenlabs_errors_are_readable() -> None:
    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": {"message": "invalid key"}})

    client = ElevenLabsClient("k", transport=httpx.MockTransport(denied))
    with pytest.raises(VoiceProviderError, match="API-Key abgelehnt"):
        await client.synthesize("x", voice_id="v")
    with pytest.raises(VoiceProviderError, match="EMTEDAD_ELEVENLABS_API_KEY"):
        ElevenLabsClient("")


def test_blocks_keep_whole_sentences() -> None:
    text = "جملهٔ اول است. جملهٔ دوم است.\nجملهٔ سوم است."
    blocks = split_blocks(text, 20)
    assert all(b.endswith("است.") for b in blocks)
    assert " ".join(blocks).count("است.") == 3


def test_judge_compares_vowels() -> None:
    assert judge("molk", ["m", "o", "l", "k"])["ok"] is True
    assert judge("molk", ["m", "a", "l", "a", "k"])["ok"] is False
    assert find_word("در مُلک خدا", "ملک") == (3, 7)


class _KeyEditor:
    async def annotate(self, text: str) -> PronunciationKey:
        key = PronunciationKey(sentences=[text])
        if "ملک" in text:
            key.words[0] = [
                {"w": "ملک", "read": "molk", "vowelled": "مُلک", "full": "مُلْک"}
            ]
        return key


class _Listener:
    """Hears 'malak' until the full harakat form is used."""

    def __init__(self) -> None:
        self.calls = 0
        self.texts: list[str] = []

    def frames(self, path: str) -> list[tuple[str, float, float]]:
        self.calls += 1
        heard = ["m", "o", "l", "k"] if self.calls >= 2 else ["m", "a", "l", "a", "k"]
        return [(tok, 0.0, 100.0) for tok in heard]


class _Database:
    pass


@pytest.mark.asyncio
async def test_misread_word_is_fixed_and_block_recorded_again(tmp_path: Path) -> None:
    seen: list[dict[str, object]] = []
    listener = _Listener()
    service = VoiceRenderService(
        _Database(),  # type: ignore[arg-type]
        ElevenLabsClient("k", transport=_tts_transport(seen)),
        VoiceConfig(voice_ids={"fa": "v1"}, max_rounds=3),
        tmp_path,
        key_editor=_KeyEditor(),  # type: ignore[arg-type]
        listener_factory=lambda: listener,
    )

    async def text(brief_id: object, language: str) -> str:
        return "او در ملک خدا سیر می‌کرد."

    service.source_text = text  # type: ignore[method-assign]
    brief_id = uuid4()
    manifest = await service.render(brief_id, "fa")
    sent = [str(s["text"]) for s in seen]
    assert "مُلک" in sent[0]  # first take already carries minimal harakat
    assert "مُلْک" in sent[1]  # misread → full harakat, recorded again
    assert len(sent) == 2
    block = manifest["blocks"][0]
    assert block["rounds"] == 2 and block["unresolved"] == []
    out = tmp_path / "voice" / str(brief_id) / "fa"
    assert (out / "full.mp3").exists() and (out / "manifest.json").exists()


@pytest.mark.asyncio
async def test_other_languages_never_load_the_listener(tmp_path: Path) -> None:
    seen: list[dict[str, object]] = []

    def explode() -> None:
        raise AssertionError("listener must not load for German")

    service = VoiceRenderService(
        _Database(),  # type: ignore[arg-type]
        ElevenLabsClient("k", transport=_tts_transport(seen)),
        VoiceConfig(voice_ids={"de": "v2"}),
        tmp_path,
        key_editor=_KeyEditor(),  # type: ignore[arg-type]
        listener_factory=explode,
    )

    async def text(brief_id: object, language: str) -> str:
        return "Ein Satz. Noch ein Satz."

    service.source_text = text  # type: ignore[method-assign]
    manifest = await service.render(uuid4(), "de")
    assert len(seen) == 1 and seen[0]["language_code"] == "de"
    assert manifest["blocks"][0]["checked"] is False


def test_api_key_is_read_from_plain_elevenlabs_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-from-env")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.elevenlabs_api_key is not None
    assert settings.elevenlabs_api_key.get_secret_value() == "sk-from-env"
