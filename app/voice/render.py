"""Voice recording of an approved script (fa) or a finished translation.

The text is split into blocks of whole sentences; blocks are recorded in
parallel with ElevenLabs. For Persian (pronunciation_languages), every
block first gets a pronunciation key; after each take a wav2vec2 phoneme
listener checks every risky word at its place in the audio. A misread
word is fixed in the voice text — harakat, full harakat, unambiguous
spelling, synonym — and the block is recorded again (max_rounds). Words
still wrong are listed for the owner. Subtitles keep the plain text.
"""

import asyncio
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.content_engine.domain import DraftStatus
from app.content_engine.models import ScriptDraft
from app.content_engine.service import GateBlockedError
from app.db.session import Database
from app.localization.domain import LocalizationPipelineStage
from app.localization.models import (
    LocalizationPipelineRun,
    LocalizationSemanticPackage,
)
from app.voice.elevenlabs import DEFAULT_MODEL, ElevenLabsClient
from app.voice.listener import ListenerUnavailable, PhonemeListener, window
from app.voice.phonetics import find_word, judge, span_times
from app.voice.pronunciation_key import (
    PronunciationKey,
    PronunciationKeyEditor,
    split_sentences,
)

FIX_ORDER = ("vowelled", "full", "respell", "synonym")
VOICE_LANGUAGES = ("fa", "de", "en", "ar")


@dataclass
class VoiceConfig:
    voice_ids: dict[str, str]
    model_id: str = DEFAULT_MODEL
    concurrency: int = 3
    block_chars: int = 1200
    check_languages: tuple[str, ...] = ("fa",)
    max_rounds: int = 3
    pad_seconds: float = 0.12
    max_vowel_distance: float = 0.6


@dataclass
class BlockResult:
    index: int
    text: str
    voice_text: str
    audio: bytes
    rounds: int = 1
    checked: bool = False
    words: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    note: str = ""


def split_blocks(text: str, max_chars: int) -> list[str]:
    """Whole sentences, each block at most ~max_chars."""

    blocks: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in [p for p in text.split("\n") if p.strip()]:
        for sentence in split_sentences(paragraph):
            if current and size + len(sentence) > max_chars:
                blocks.append(" ".join(current))
                current, size = [], 0
            current.append(sentence)
            size += len(sentence) + 1
    if current:
        blocks.append(" ".join(current))
    return blocks


def _voice_text(key: PronunciationKey, levels: dict[tuple[int, int], int]) -> str:
    import re

    from app.voice.pronunciation_key import _WORD_CH

    out: list[str] = []
    for s_index, sentence in enumerate(key.sentences):
        text = sentence
        for w_index, entry in enumerate(key.words.get(s_index, [])):
            level = levels.get((s_index, w_index), 0)
            form = ""
            for name in FIX_ORDER[level:]:
                if entry.get(name):
                    form = entry[name]
                    break
            if form:
                text = re.sub(
                    rf"(?<![{_WORD_CH}]){re.escape(entry['w'])}(?![{_WORD_CH}])",
                    form,
                    text,
                    count=1,
                )
        out.append(text)
    return " ".join(out)


def _next_level(entry: dict[str, str], level: int) -> int | None:
    for candidate in range(level + 1, len(FIX_ORDER)):
        if entry.get(FIX_ORDER[candidate]):
            return candidate
    return None


class VoiceRenderService:
    def __init__(
        self,
        database: Database,
        client: ElevenLabsClient,
        config: VoiceConfig,
        storage_root: Path,
        *,
        key_editor: PronunciationKeyEditor | None = None,
        listener_factory: Any = None,
    ) -> None:
        self.database = database
        self.client = client
        self.config = config
        self.storage_root = storage_root
        self.key_editor = key_editor
        self.listener_factory = listener_factory

    def output_dir(self, brief_id: UUID, language: str) -> Path:
        return self.storage_root / "voice" / str(brief_id) / language

    async def source_text(self, brief_id: UUID, language: str) -> str:
        async with self.database.transaction() as session:
            if language == "fa":
                draft = await session.scalar(
                    select(ScriptDraft)
                    .where(
                        ScriptDraft.content_brief_id == brief_id,
                        ScriptDraft.lineage == "primary",
                        ScriptDraft.status == DraftStatus.APPROVED,
                    )
                    .order_by(ScriptDraft.version_number.desc())
                    .limit(1)
                )
                if draft is None:
                    raise GateBlockedError(
                        "Vertonung braucht ein freigegebenes persisches Skript."
                    )
                return draft.text
            run = await session.scalar(
                select(LocalizationPipelineRun)
                .join(
                    LocalizationSemanticPackage,
                    LocalizationSemanticPackage.id
                    == LocalizationPipelineRun.semantic_package_id,
                )
                .where(
                    LocalizationSemanticPackage.content_brief_id == brief_id,
                    LocalizationPipelineRun.language == language,
                    LocalizationPipelineRun.stage
                    == LocalizationPipelineStage.READY_FOR_VOICE,
                )
                .order_by(LocalizationPipelineRun.updated_at.desc())
                .limit(1)
            )
            if run is None or run.script_draft_id is None:
                raise GateBlockedError(
                    f"Vertonung ({language.upper()}) braucht eine Übersetzung im "
                    "Status „fertig für Voice“."
                )
            draft = await session.get(ScriptDraft, run.script_draft_id)
            if draft is None:
                raise GateBlockedError("Übersetzter Text nicht gefunden.")
            return draft.text

    async def render(self, brief_id: UUID, language: str) -> dict[str, Any]:
        if language not in VOICE_LANGUAGES:
            raise GateBlockedError(f"Unbekannte Sprache {language}")
        voice_id = self.config.voice_ids.get(language, "")
        if not voice_id:
            raise GateBlockedError(
                f"Keine ElevenLabs-Stimme für {language.upper()} eingestellt "
                "(Settings → Voice)."
            )
        text = await self.source_text(brief_id, language)
        blocks = split_blocks(text, self.config.block_chars)
        check = language in self.config.check_languages
        listener: PhonemeListener | None = None
        note = ""
        if check:
            try:
                factory = self.listener_factory
                if factory is None:
                    from app.voice.listener import get_listener

                    factory = get_listener
                listener = await asyncio.to_thread(factory)
            except ListenerUnavailable as exc:
                note = f"Hinhör-Check übersprungen: {exc}"
        semaphore = asyncio.Semaphore(max(1, self.config.concurrency))

        async def one(index: int, block: str) -> BlockResult:
            async with semaphore:
                return await self._render_block(
                    index, block, language, voice_id, check, listener
                )

        results = await asyncio.gather(*(one(i, b) for i, b in enumerate(blocks)))
        return self._store(brief_id, language, results, note)

    async def _render_block(
        self,
        index: int,
        text: str,
        language: str,
        voice_id: str,
        check: bool,
        listener: PhonemeListener | None,
    ) -> BlockResult:
        key: PronunciationKey | None = None
        if check and self.key_editor is not None:
            key = await self.key_editor.annotate(text)
        levels: dict[tuple[int, int], int] = {}
        if key is not None:
            for s_index, entries in key.words.items():
                for w_index, entry in enumerate(entries):
                    first = next(
                        (i for i, n in enumerate(FIX_ORDER) if entry.get(n)), 0
                    )
                    levels[(s_index, w_index)] = first
        result = BlockResult(index=index, text=text, voice_text=text, audio=b"")
        for round_number in range(1, self.config.max_rounds + 1):
            voice_text = _voice_text(key, levels) if key is not None else text
            synthesis = await self.client.synthesize(
                voice_text,
                voice_id=voice_id,
                model_id=self.config.model_id,
                language_code=language,
            )
            result.audio, result.voice_text = synthesis.audio, voice_text
            result.rounds = round_number
            if key is None or listener is None or not key.words:
                break
            result.checked = True
            frames = await asyncio.to_thread(self._frames, listener, synthesis.audio)
            wrong: list[tuple[int, int]] = []
            result.words = []
            cursor = 0
            for s_index in sorted(key.words):
                for w_index, entry in enumerate(key.words[s_index]):
                    level = levels[(s_index, w_index)]
                    if FIX_ORDER[level] == "synonym":
                        result.words.append(
                            {"w": entry["w"], "ok": None, "fix": "synonym"}
                        )
                        continue
                    span = find_word(voice_text, entry["w"], cursor)
                    if span is None:
                        continue
                    cursor = span[1]
                    times = span_times(synthesis.alignment, voice_text, span, 0.0)
                    if times is None:
                        result.words.append(
                            {"w": entry["w"], "ok": None, "reason": "no_timing"}
                        )
                        continue
                    heard = window(frames, times[0], times[1], self.config.pad_seconds)
                    verdict = judge(
                        entry["read"], heard, self.config.max_vowel_distance
                    )
                    result.words.append(
                        {
                            "w": entry["w"],
                            "read": entry["read"],
                            "fix": FIX_ORDER[level],
                            **verdict,
                        }
                    )
                    if verdict["ok"] is False:
                        wrong.append((s_index, w_index))
            if not wrong:
                result.unresolved = []
                break
            escalated = False
            result.unresolved = []
            for position in wrong:
                entry = key.words[position[0]][position[1]]
                nxt = _next_level(entry, levels[position])
                if nxt is None:
                    result.unresolved.append(entry["w"])
                else:
                    levels[position] = nxt
                    escalated = True
            if not escalated or round_number == self.config.max_rounds:
                result.unresolved = sorted({key.words[s][w]["w"] for s, w in wrong})
                break
        return result

    @staticmethod
    def _frames(
        listener: PhonemeListener, audio: bytes
    ) -> list[tuple[str, float, float]]:
        with tempfile.NamedTemporaryFile(suffix=".mp3") as handle:
            handle.write(audio)
            handle.flush()
            return listener.frames(handle.name)

    def _store(
        self,
        brief_id: UUID,
        language: str,
        results: list[BlockResult],
        note: str,
    ) -> dict[str, Any]:
        directory = self.output_dir(brief_id, language)
        directory.mkdir(parents=True, exist_ok=True)
        for old in directory.glob("block_*.mp3"):
            old.unlink()
        paths: list[Path] = []
        for result in sorted(results, key=lambda r: r.index):
            path = directory / f"block_{result.index:03d}.mp3"
            path.write_bytes(result.audio)
            paths.append(path)
        full = directory / "full.mp3"
        _concat(paths, full)
        manifest = {
            "brief_id": str(brief_id),
            "language": language,
            "created_at": datetime.now(UTC).isoformat(),
            "note": note,
            "blocks": [
                {
                    "index": r.index,
                    "file": f"block_{r.index:03d}.mp3",
                    "text": r.text,
                    "voice_text": r.voice_text,
                    "rounds": r.rounds,
                    "checked": r.checked,
                    "words": r.words,
                    "unresolved": r.unresolved,
                }
                for r in sorted(results, key=lambda r: r.index)
            ],
            "unresolved": sorted({w for r in results for w in r.unresolved}),
            "characters": sum(len(r.voice_text) for r in results),
        }
        (directory / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return manifest


def _concat(paths: list[Path], target: Path) -> None:
    if shutil.which("ffmpeg") and paths:
        listing = target.with_suffix(".txt")
        listing.write_text(
            "".join(f"file '{p.name}'\n" for p in paths), encoding="utf-8"
        )
        completed = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-c",
                "copy",
                str(target),
            ],
            capture_output=True,
            check=False,
            cwd=target.parent,
        )
        listing.unlink(missing_ok=True)
        if completed.returncode == 0:
            return
    # MP3 frames concatenate safely enough as a fallback.
    target.write_bytes(b"".join(p.read_bytes() for p in paths))


def read_manifest(
    storage_root: Path, brief_id: UUID, language: str
) -> dict[str, Any] | None:
    path = storage_root / "voice" / str(brief_id) / language / "manifest.json"
    if not path.exists():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data
