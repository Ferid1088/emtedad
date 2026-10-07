"""wav2vec2 phoneme listener (IPA) — Persian only, optional dependency.

torch/transformers are imported lazily, only when a Persian voice is
checked. Machines that only voice de/en/ar never load them.
Install with: uv sync --extra voice-check  (needs ffmpeg for decoding).
"""

import json
import shutil
import subprocess
import threading
from functools import lru_cache
from typing import Any

DEFAULT_PHONEME_MODEL = "facebook/wav2vec2-xlsr-53-espeak-cv-ft"


class ListenerUnavailable(RuntimeError):
    """The optional listening check cannot run on this machine."""


class PhonemeListener:
    FRAME = 0.02  # seconds per wav2vec2 output frame

    def __init__(self, model_name: str) -> None:
        if shutil.which("ffmpeg") is None:
            raise ListenerUnavailable(
                "ffmpeg fehlt (zum Dekodieren der Aufnahme): brew install ffmpeg"
            )
        try:
            import torch  # noqa: F401
            from huggingface_hub import hf_hub_download
            from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForCTC
        except ImportError as exc:
            raise ListenerUnavailable(
                "Hinhör-Check braucht torch + transformers: uv sync --extra voice-check"
            ) from exc
        self.fe: Any = Wav2Vec2FeatureExtractor.from_pretrained(model_name)
        model: Any = Wav2Vec2ForCTC.from_pretrained(model_name)
        self.model: Any = model.eval()
        with open(hf_hub_download(model_name, "vocab.json"), encoding="utf-8") as fh:
            vocab = json.load(fh)
        self.inv = {v: k for k, v in vocab.items()}
        self.lock = threading.Lock()

    def frames(self, audio_path: str) -> list[tuple[str, float, float]]:
        """Phonemes of a whole recording: [(ipa, start, end)]."""

        import numpy as np
        import torch

        raw = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                audio_path,
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "f32le",
                "-",
            ],
            capture_output=True,
            check=True,
        ).stdout
        audio = np.frombuffer(raw, np.float32)
        with self.lock, torch.no_grad():
            values = self.fe(audio, sampling_rate=16000, return_tensors="pt")
            logits = self.model(values.input_values).logits
        ids = torch.argmax(logits, -1)[0].tolist()
        out: list[tuple[str, float, float]] = []
        prev = None
        for k, i in enumerate(ids):
            tok = self.inv.get(int(i), "")
            if i != prev and tok not in ("<pad>", "<s>", "</s>", "<unk>", "|", ""):
                out.append((tok, k * self.FRAME, (k + 1) * self.FRAME))
            elif i == prev and out and tok == out[-1][0]:
                out[-1] = (tok, out[-1][1], (k + 1) * self.FRAME)
            prev = i
        return out


_lock = threading.Lock()


@lru_cache(maxsize=2)
def _load(model_name: str) -> PhonemeListener:
    return PhonemeListener(model_name)


def get_listener(model_name: str = DEFAULT_PHONEME_MODEL) -> PhonemeListener:
    with _lock:
        return _load(model_name)


def window(
    frames: list[tuple[str, float, float]], start: float, end: float, pad: float
) -> list[str]:
    return [tok for tok, s, e in frames if e >= start - pad and s <= end + pad]
