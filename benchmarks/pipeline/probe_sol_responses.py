"""Sol Chat-vs-Responses protocol certification probe (§35–37).

Runs IDENTICAL production-shaped inputs through both wire protocols on
``gpt-6.1-sol`` and compares schema compliance, latency, and token counts
side by side. The Responses route is undocumented — it becomes the
production default only if quality and reliability match Chat across two
loops and the token reduction repeats.

    uv run python -m benchmarks.pipeline.probe_sol_responses [--loop N]

Writes ``artifacts/sol_protocol_probe_<loop>.json``.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.content_engine.models import ScriptDraft
from app.core.config import get_settings
from app.db.session import Database
from app.knowledge.llm.apimaster import (
    APIMasterConfig,
    APIMasterProvider,
    CallTelemetry,
)
from app.knowledge.llm.base import StructuredExtractionRequest
from app.lecture.domain import PublicationLanguage
from app.localization.models import LocalizationSemanticPackage
from app.localization.native_prompts import fidelity_critic_instructions

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
CERT_PACKAGE = UUID("eba81c94-f335-49f1-85c4-4be172f89edc")
MODEL = "gpt-6.1-sol"


class FindingOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str
    code: str
    severity: str
    explanation: str


class FindingsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[FindingOut]


class ClaimCheckOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supported: bool
    claim_id: str
    evidence_level: str
    rationale: str


class Collector:
    def __init__(self) -> None:
        self.events: list[CallTelemetry] = []

    async def record(self, event: CallTelemetry) -> None:
        self.events.append(event)


def _provider(protocol: str, key: str, sink: Collector) -> APIMasterProvider:
    return APIMasterProvider(
        APIMasterConfig(
            api_key=key,
            model=MODEL,
            protocol=protocol,  # type: ignore[arg-type]
            max_retries=1,
        ),
        recorder=sink,
        agent_role="protocol_probe",
    )


async def _cases(database: Database) -> list[dict[str, Any]]:
    """Three real production-shaped Sol inputs from the cert package."""

    async with database.transaction() as session:
        package = await session.get(LocalizationSemanticPackage, CERT_PACKAGE)
        drafts = (
            await session.scalars(
                select(ScriptDraft)
                .where(ScriptDraft.lineage == "localized")
                .order_by(ScriptDraft.created_at.desc())
                .limit(4)
            )
        ).all()
        package_payload = dict(package.payload) if package else {}
        texts = [d.text for d in drafts]
    instructions = fidelity_critic_instructions(PublicationLanguage.DE)
    cases: list[dict[str, Any]] = []
    for i, text in enumerate(texts[:3]):
        cases.append(
            {
                "name": f"fidelity_critic_case_{i + 1}",
                "task": "localization_fidelity_critic",
                "instructions": instructions,
                "input_text": json.dumps(
                    {
                        "package": package_payload,
                        "target_script": text[:12000],
                        "language": "de",
                    },
                    ensure_ascii=False,
                ),
                "output_model": FindingsOut,
            }
        )
    claims = list(package_payload.get("causal_constraints") or []) + list(
        package_payload.get("counterarguments") or []
    )
    thesis = package_payload.get("thesis")
    for i, claim in enumerate(claims[:3]):
        cases.append(
            {
                "name": f"claim_check_case_{i + 1}",
                "task": "evidence_claim_check",
                "instructions": (
                    "Judge whether the claim is supported by the supplied "
                    "evidence summary. Output the schema exactly."
                ),
                "input_text": json.dumps(
                    {"claim": claim, "thesis": thesis, "language": "fa"},
                    ensure_ascii=False,
                ),
                "output_model": ClaimCheckOut,
            }
        )
    return cases


async def main() -> int:
    loop = 1
    if "--loop" in sys.argv:
        loop = int(sys.argv[sys.argv.index("--loop") + 1])
    settings = get_settings()
    key = (
        settings.apimaster_api_key.get_secret_value()
        if settings.apimaster_api_key
        else None
    )
    if not key:
        raise SystemExit("apimaster_api_key not configured")
    database = Database(settings.database_url.get_secret_value())
    try:
        cases = await _cases(database)
        results: list[dict[str, Any]] = []
        for case in cases:
            for protocol in ("chat", "responses"):
                sink = Collector()
                provider = _provider(protocol, key, sink)
                started = time.monotonic()
                outcome: dict[str, Any] = {
                    "case": case["name"],
                    "protocol": protocol,
                }
                try:
                    result = await provider.extract(
                        StructuredExtractionRequest(
                            task=case["task"],
                            prompt_version="sol_protocol_probe",
                            model=MODEL,
                            instructions=case["instructions"],
                            input_text=case["input_text"],
                            output_model=case["output_model"],
                            timeout_seconds=300,
                        )
                    )
                    outcome["ok"] = True
                    outcome["output"] = result.model_dump(mode="json")
                except Exception as exc:  # noqa: BLE001 — honest probe
                    outcome["ok"] = False
                    outcome["error"] = f"{type(exc).__name__}: {exc}"[:300]
                outcome["latency_s"] = round(time.monotonic() - started, 2)
                if sink.events:
                    ev = sink.events[-1]
                    outcome["prompt_tokens"] = ev.prompt_tokens
                    outcome["completion_tokens"] = ev.completion_tokens
                    outcome["schema_repairs"] = ev.schema_repairs
                    outcome["fallback_used"] = ev.fallback_used
                    outcome["error_kind"] = ev.error_kind
                results.append(outcome)
                print(
                    f"{case['name']:>26} {protocol:>9}: "
                    f"ok={outcome['ok']} prompt_tokens={outcome.get('prompt_tokens')} "
                    f"latency={outcome['latency_s']}s"
                )
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        out = ARTIFACT_DIR / f"sol_protocol_probe_loop{loop}.json"
        out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"wrote {out}")
        return 0
    finally:
        await database.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
