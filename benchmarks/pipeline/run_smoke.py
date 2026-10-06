"""Live APIMaster canary — real calls, dry-run telemetry namespace.

Two structured calls per routed model role (Qwen, Sol, Gemini, Astra —
all synchronous; APIMaster exposes no batch API). Every call writes an
``ops.llm_call_events`` row with ``run_scope='canary'`` — audit data,
never content.

Run:  uv run python -m benchmarks.pipeline.run_smoke
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.db.session import Database
from app.knowledge.llm.apimaster import (
    APIMasterConfig,
    APIMasterProvider,
    CallTelemetry,
)
from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.llm.telemetry import DatabaseLLMRecorder
from app.lecture.domain import PublicationLanguage
from app.localization.native_quality import validate_target_script

ARTIFACT_DIR = Path(__file__).parent / "artifacts"


class MiniOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    ok: bool


class SentenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)


async def _call(
    model: str,
    task: str,
    instructions: str,
    input_text: str,
    output_model: type[BaseModel],
    recorder: DatabaseLLMRecorder,
    sink: list[dict[str, Any]],
) -> BaseModel:
    provider = APIMasterProvider(
        APIMasterConfig(
            api_key=_key(),
            model=model,
            max_retries=2,
        ),
        recorder=recorder,
        agent_role=f"canary:{task}",
    )
    events: list[CallTelemetry] = []

    class _Tap:
        async def record(self, event: CallTelemetry) -> None:
            events.append(event)
            await recorder.record(event)

    provider.recorder = _Tap()
    started = time.monotonic()
    result = await provider.extract(
        StructuredExtractionRequest(
            task=task,
            prompt_version="canary-v1",
            model=model,
            instructions=instructions,
            input_text=input_text,
            output_model=output_model,
            timeout_seconds=120,
        )
    )
    elapsed = time.monotonic() - started
    ev = events[-1]
    sink.append(
        {
            "task": task,
            "model": model,
            "ok": ev.ok,
            "latency_ms": ev.latency_ms,
            "wall_s": round(elapsed, 1),
            "prompt_tokens": ev.prompt_tokens,
            "completion_tokens": ev.completion_tokens,
            "cached_tokens": ev.cached_tokens,
            "reasoning_tokens": ev.reasoning_tokens,
            "cost_usd": ev.cost_usd,
            "retries": ev.retries,
            "schema_repairs": ev.schema_repairs,
            "request_id": ev.request_id,
        }
    )
    print(f"  [{task}] ok={ev.ok} {ev.latency_ms}ms cost={ev.cost_usd}")
    return result


def _key() -> str | None:
    settings = get_settings()
    if settings.apimaster_api_key is not None:
        return settings.apimaster_api_key.get_secret_value()
    return None


async def main() -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    database = Database(settings.database_url.get_secret_value())
    recorder = DatabaseLLMRecorder(database, run_scope="canary")
    results: list[dict[str, Any]] = []
    try:
        # --- 1. Model-role smoke ×2 each ----------------------------------
        roles = {
            "qwen": settings.model_role_high_volume,
            "sol": settings.model_role_reasoning,
            "gemini": settings.model_role_editorial,
            "astra": settings.model_role_premium,
        }
        for label, model in roles.items():
            for iteration in (1, 2):
                await _call(
                    model,
                    f"smoke_{label}_{iteration}",
                    "Summarize the supplied claim in one sentence and set ok=true.",
                    json.dumps({"claim": "Skepticism requires evidence."}),
                    MiniOutput,
                    recorder,
                    results,
                )

        # --- 2. Native-language quality ×2 per language (Gemini) ----------
        lang_cases = [
            (PublicationLanguage.DE, "German", 130),
            (PublicationLanguage.EN, "English", 140),
            (PublicationLanguage.AR, "Arabic", 120),
            (PublicationLanguage.FA, "Persian", 110),
        ]
        for lang, name, wpm in lang_cases:
            for iteration in (1, 2):
                out = await _call(
                    settings.model_role_editorial,
                    f"native_{lang.value}_{iteration}",
                    (
                        f"Write exactly one natural spoken-{name} sentence "
                        "about intellectual humility. Native phrasing only."
                    ),
                    json.dumps({"topic": "intellectual humility"}),
                    SentenceOutput,
                    recorder,
                    results,
                )
                text = SentenceOutput.model_validate(out.model_dump()).text
                findings, words, _ = validate_target_script(
                    text, lang, min_minutes=0.0, max_minutes=60.0, wpm=wpm
                )
                results[-1]["native_words"] = words
                results[-1]["native_findings"] = [
                    {"code": f.code, "blocking": f.blocking} for f in findings
                ]
                if findings:
                    print(f"    findings: {[f.code for f in findings]}")

        # --- 3. Batch capability: verified absent -------------------------
        # Live probe 2026-10-05: POST /v1/batches → 404 "Invalid URL".
        # Recorded as a capability fact, not exercised.
        results.append({"task": "batch_capability", "status": "NOT_AVAILABLE"})

        out_path = ARTIFACT_DIR / f"smoke_{int(time.time())}.json"
        out_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2)
        )
        print(f"wrote {out_path}")
        return 0 if all(r.get("ok", True) for r in results) else 1
    finally:
        await database.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
