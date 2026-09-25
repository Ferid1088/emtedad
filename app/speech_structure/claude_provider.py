"""Claude Code provider that fails over between two isolated subscription profiles."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.knowledge.llm.base import StructuredExtractionRequest

_FAILOVER_MARKERS: Final[tuple[str, ...]] = (
    "usage limit",
    "rate limit",
    "rate_limit",
    "overloaded",
    "temporarily unavailable",
    "service unavailable",
    "connection",
    "network",
    "timed out",
    "timeout",
    "login expired",
    "please run /login",
    "invalid authentication credentials",
    "invalid bearer token",
    "failed to authenticate",
    "authentication_error",
    "401",
)


class ClaudeCodeFailoverError(RuntimeError):
    """Raised when neither configured Claude subscription profile can answer."""


@dataclass(frozen=True, slots=True)
class _Profile:
    name: str
    oauth_token: str


class ClaudeCodeFailoverProvider:
    """Try the primary Claude Code profile, then the secondary profile on availability errors."""

    name = "claude-code-failover"

    def __init__(
        self,
        *,
        work_oauth_token: str | None,
        personal_oauth_token: str | None,
        executable: str = "claude",
    ) -> None:
        self._executable = executable
        self._profiles = tuple(
            profile
            for profile in (
                _Profile("work", work_oauth_token or ""),
                _Profile("personal", personal_oauth_token or ""),
            )
            if profile.oauth_token
        )
        self._disabled: set[str] = set()

    @classmethod
    def from_settings(cls) -> "ClaudeCodeFailoverProvider":
        settings = get_settings()
        work = (
            settings.claude_oauth_token_work.get_secret_value()
            if settings.claude_oauth_token_work is not None
            else None
        )
        personal = (
            settings.claude_oauth_token_personal.get_secret_value()
            if settings.claude_oauth_token_personal is not None
            else None
        )
        return cls(
            work_oauth_token=work,
            personal_oauth_token=personal,
        )

    async def extract(self, request: StructuredExtractionRequest) -> BaseModel:
        return await asyncio.to_thread(self._extract_sync, request)

    def _extract_sync(self, request: StructuredExtractionRequest) -> BaseModel:
        executable = shutil.which(self._executable)
        if executable is None:
            raise ClaudeCodeFailoverError(
                "Claude Code CLI wurde nicht gefunden. Prüfe 'claude --version'."
            )
        if not self._profiles:
            raise ClaudeCodeFailoverError(
                "Keine Claude-Code-OAuth-Tokens konfiguriert. "
                "Setze EMTEDAD_CLAUDE_OAUTH_TOKEN_WORK und/oder "
                "EMTEDAD_CLAUDE_OAUTH_TOKEN_PERSONAL in .env."
            )

        failures: list[str] = []
        for profile in self._profiles:
            if profile.name in self._disabled:
                continue
            try:
                return self._run_profile(executable, profile, request)
            except ClaudeCodeFailoverError as exc:
                message = str(exc)
                failures.append(message)
                if self._should_failover(message):
                    self._disabled.add(profile.name)
                    continue
                raise

        detail = " | ".join(failures) or "kein verfügbares Profil"
        raise ClaudeCodeFailoverError(
            "Beide Claude-Code-Abos sind derzeit nicht verfügbar: " + detail
        )

    def _run_profile(
        self,
        executable: str,
        profile: _Profile,
        request: StructuredExtractionRequest,
    ) -> BaseModel:
        schema = json.dumps(
            request.output_model.model_json_schema(),
            ensure_ascii=False,
        )
        prompt = (
            "Return exactly one JSON object matching the JSON schema below. "
            "Do not use markdown fences and do not add commentary.\n\n"
            f"JSON schema:\n{schema}\n\n"
            f"Task: {request.task}\n"
            f"Prompt version: {request.prompt_version}\n"
            f"Instructions:\n{request.instructions}\n\n"
            f"Source material:\n{request.input_text}"
        )

        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        env["CLAUDE_CODE_OAUTH_TOKEN"] = profile.oauth_token

        command = [
            executable,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--max-turns",
            "1",
        ]
        if request.model != "configured-default":
            command.extend(["--model", request.model])

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                check=False,
                shell=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise ClaudeCodeFailoverError(
                f"{profile.name}: timeout after {request.timeout_seconds}s"
            ) from exc
        except OSError as exc:
            raise ClaudeCodeFailoverError(
                f"{profile.name}: Claude konnte nicht gestartet werden "
                f"({type(exc).__name__})"
            ) from exc

        combined = "\n".join(
            part for part in (result.stdout, result.stderr) if part
        ).strip()
        if result.returncode != 0:
            raise ClaudeCodeFailoverError(
                f"{profile.name}: {_diagnostic(combined)}"
            )

        try:
            envelope = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ClaudeCodeFailoverError(
                f"{profile.name}: ungültige Claude-CLI-JSON-Antwort"
            ) from exc

        if bool(envelope.get("is_error")):
            detail = str(envelope.get("result") or combined or "Claude Code error")
            raise ClaudeCodeFailoverError(
                f"{profile.name}: {_diagnostic(detail)}"
            )

        raw_result = envelope.get("result")
        if not isinstance(raw_result, str) or not raw_result.strip():
            raise ClaudeCodeFailoverError(
                f"{profile.name}: Claude Code lieferte kein Ergebnis"
            )

        try:
            payload = json.loads(_strip_fence(raw_result.strip()))
            return request.output_model.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ClaudeCodeFailoverError(
                f"{profile.name}: strukturierte Antwort war ungültig "
                f"({type(exc).__name__})"
            ) from exc

    @staticmethod
    def _should_failover(message: str) -> bool:
        lowered = message.lower()
        return any(marker in lowered for marker in _FAILOVER_MARKERS)


def _strip_fence(value: str) -> str:
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _diagnostic(value: str) -> str:
    cleaned = value.strip()
    return cleaned[-1800:] if cleaned else "Claude Code failed without diagnostics"
