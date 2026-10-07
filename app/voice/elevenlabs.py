"""ElevenLabs text-to-speech with character timing.

POST /v1/text-to-speech/{voice_id}/with-timestamps returns the audio and
the start/end time of every character — the pronunciation check uses it
to find each risky word in the audio.
"""

import asyncio
import base64
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_MODEL = "eleven_v3"
# Models that accept an explicit language_code.
_LANGUAGE_CODE_MODELS = {"eleven_v3", "eleven_turbo_v2_5", "eleven_flash_v2_5"}


class VoiceProviderError(RuntimeError):
    """ElevenLabs refused or failed a request (message is owner-readable)."""


@dataclass(frozen=True)
class Synthesis:
    audio: bytes
    alignment: dict[str, list[Any]]  # characters, starts, ends
    characters_billed: int


@dataclass(frozen=True)
class VoiceInfo:
    voice_id: str
    name: str
    category: str
    labels: dict[str, str]


class ElevenLabsClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.elevenlabs.io",
        output_format: str = "mp3_44100_128",
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise VoiceProviderError(
                "Kein ElevenLabs-API-Key: EMTEDAD_ELEVENLABS_API_KEY in .env eintragen."
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.output_format = output_format
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout,
            transport=self.transport,
            headers={"xi-api-key": self.api_key},
        )

    async def list_voices(self) -> list[VoiceInfo]:
        async with self._client() as client:
            response = await client.get(f"{self.base_url}/v1/voices")
        if response.status_code != 200:
            raise _error(response)
        voices = []
        for item in response.json().get("voices") or []:
            voices.append(
                VoiceInfo(
                    voice_id=str(item.get("voice_id") or ""),
                    name=str(item.get("name") or ""),
                    category=str(item.get("category") or ""),
                    labels={
                        str(k): str(v) for k, v in (item.get("labels") or {}).items()
                    },
                )
            )
        return voices

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str,
        model_id: str = DEFAULT_MODEL,
        language_code: str | None = None,
    ) -> Synthesis:
        body: dict[str, Any] = {"text": text, "model_id": model_id}
        if language_code and model_id in _LANGUAGE_CODE_MODELS:
            body["language_code"] = language_code
        url = f"{self.base_url}/v1/text-to-speech/{voice_id}/with-timestamps"
        last: VoiceProviderError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with self._client() as client:
                    response = await client.post(
                        url, params={"output_format": self.output_format}, json=body
                    )
            except httpx.HTTPError as exc:
                last = VoiceProviderError(f"ElevenLabs nicht erreichbar ({exc})")
            else:
                if response.status_code == 200:
                    return _parse(response.json(), text)
                last = _error(response)
                if response.status_code not in (429, 500, 502, 503, 504):
                    raise last
            if attempt < self.max_retries:
                await asyncio.sleep(2.0 * (attempt + 1))
        assert last is not None
        raise last


def _parse(data: dict[str, Any], text: str) -> Synthesis:
    try:
        audio = base64.b64decode(data["audio_base64"])
        alignment = data.get("alignment") or data.get("normalized_alignment") or {}
        chars = list(alignment["characters"])
        starts = [float(x) for x in alignment["character_start_times_seconds"]]
        ends = [float(x) for x in alignment["character_end_times_seconds"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise VoiceProviderError(f"ElevenLabs-Antwort unvollständig: {exc}") from exc
    if not audio or not (len(chars) == len(starts) == len(ends)):
        raise VoiceProviderError(
            "ElevenLabs lieferte leeres Audio oder kaputtes Timing"
        )
    return Synthesis(
        audio=audio,
        alignment={"characters": chars, "starts": starts, "ends": ends},
        characters_billed=len(text),
    )


def _error(response: httpx.Response) -> VoiceProviderError:
    detail = ""
    try:
        payload = response.json().get("detail")
        detail = (
            payload.get("message", "") if isinstance(payload, dict) else str(payload)
        )
    except ValueError:
        detail = response.text[:200]
    messages = {
        401: "ElevenLabs hat den API-Key abgelehnt.",
        402: "ElevenLabs: Guthaben/Abo reicht nicht.",
        404: "ElevenLabs: Stimme nicht gefunden — Voice-ID in den Settings prüfen.",
        422: "ElevenLabs hat die Anfrage abgelehnt (Text/Modell).",
        429: "ElevenLabs: zu viele gleichzeitige Anfragen — wird wiederholt.",
    }
    base = messages.get(
        response.status_code, f"ElevenLabs-Fehler {response.status_code}"
    )
    return VoiceProviderError(f"{base} {detail}".strip())
