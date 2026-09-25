"""Structured Codex CLI provider using non-interactive ``codex exec``."""

import asyncio
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.knowledge.llm.base import StructuredExtractionRequest


class CodexProviderError(RuntimeError):
    """Raised for timeout, process, JSON, or schema failures."""


class CodexCliProvider:
    name = "codex-cli"

    def __init__(self, *, executable: str = "codex") -> None:
        self._executable = executable

    async def extract(self, request: StructuredExtractionRequest) -> BaseModel:
        return await asyncio.to_thread(self._extract_sync, request)

    def _extract_sync(self, request: StructuredExtractionRequest) -> BaseModel:
        executable = shutil.which(self._executable)
        if executable is None:
            raise CodexProviderError(
                "Codex CLI wurde nicht gefunden. Starte die App aus einer Shell, "
                "in der 'codex --version' funktioniert."
            )
        with tempfile.TemporaryDirectory(prefix="emtedad-codex-") as directory:
            root = Path(directory)
            schema_path = root / "schema.json"
            schema_path.write_text(
                json.dumps(
                    request.output_model.model_json_schema(), ensure_ascii=False
                ),
                encoding="utf-8",
            )
            output_path = root / "final.json"
            prompt = (
                "Do not use shell commands or tools. Analyze only the source material "
                "included in this prompt and return exactly the requested structured "
                "response.\n"
                f"Task: {request.task}\nPrompt version: {request.prompt_version}\n"
                f"{request.instructions}\n\nSource window:\n{request.input_text}"
            )
            command = [
                executable,
                "exec",
                "-",
                "--ephemeral",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--color",
                "never",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "--cd",
                str(root),
            ]
            if request.model != "configured-default":
                command.extend(["--model", request.model])
            try:
                result = subprocess.run(
                    command,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=request.timeout_seconds,
                    check=False,
                    shell=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise CodexProviderError(type(exc).__name__) from exc
        if result.returncode != 0:
            diagnostic = _safe_diagnostic(result.stderr)
            raise CodexProviderError(
                f"codex exec failed (exit {result.returncode}): {diagnostic}"
            )
        raw_output = ""
        try:
            if output_path.exists():
                raw_output = output_path.read_text(encoding="utf-8").strip()
        except OSError:
            raw_output = ""
        if not raw_output:
            raw_output = result.stdout.strip()
        try:
            payload = json.loads(raw_output)
            return request.output_model.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise CodexProviderError(
                f"invalid structured output: {type(exc).__name__}"
            ) from exc


def _safe_diagnostic(value: str) -> str:
    """Bound subprocess diagnostics; environment and command are never included."""

    return value.strip()[-2000:] or "codex exec failed without diagnostics"
