"""§35 — Sol Chat Completions vs Responses API comparison probe.

Runs two representative difficult Sol tasks against both endpoints and
records latency, tokens, schema reliability, and output quality signals.
Chat Completions is the production path; Responses is evaluated only for
material advantage. Read-only probe — no DB writes, no telemetry rows.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
MODEL = "gpt-6.1-sol"

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "objections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "objection": {"type": "string"},
                    "strongest_form": {"type": "string"},
                    "evidence_basis": {"type": "string"},
                    "severity": {"type": "string"},
                },
                "required": [
                    "objection",
                    "strongest_form",
                    "evidence_basis",
                    "severity",
                ],
                "additionalProperties": False,
            },
        },
        "overall_assessment": {"type": "string"},
    },
    "required": ["objections", "overall_assessment"],
    "additionalProperties": False,
}

TASK_A_INPUT = (
    "Thesis: chronic sleep restriction below 6 hours measurably degrades "
    "emotional regulation and long-term memory consolidation, and the effect "
    "is not fully reversible by weekend recovery sleep. Evidence: (1) Walker "
    "lab studies on amygdala reactivity after sleep deprivation; (2) "
    "Van Dongen 2003 dose-response showing cumulative cognitive deficits; "
    "(3) meta-analyses linking short sleep to dementia risk markers. "
    "Generate the three strongest steel-manned counterarguments a critical "
    "neuroscientist would raise."
)

TASK_B_INPUT = (
    "Claim ledger: [c1] loneliness predicts premature mortality with effect "
    "size comparable to smoking (epistemic: contested, two large cohort "
    "studies vs one null replication); [c2] social rejection activates "
    "dorsal anterior cingulate similarly to physical pain (epistemic: "
    "established but interpretation debated); [c3] vulnerability disclosures "
    "increase perceived closeness in strangers (epistemic: established, "
    "Aron 1997 36-questions paradigm). Draft claim: 'Science has proven that "
    "loneliness kills faster than cigarettes and that our brains literally "
    "cannot distinguish social pain from physical injury.' Identify every "
    "epistemic drift, overclaim, and conflation against the ledger."
)


async def _chat(settings: Any, task: str, input_text: str) -> dict[str, Any]:
    body = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Produce exactly one JSON object matching the required "
                    f"schema. No commentary.\n\nTask: {task}"
                ),
            },
            {"role": "user", "content": input_text},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "result",
                "schema": SCHEMA,
                "strict": True,
            },
        },
        "usage": {"include": True},
    }
    return await _post(settings, "/chat/completions", body)


async def _responses(settings: Any, task: str, input_text: str) -> dict[str, Any]:
    body = {
        "model": MODEL,
        "instructions": (
            "Produce exactly one JSON object matching the required schema. "
            f"No commentary.\n\nTask: {task}"
        ),
        "input": input_text,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "result",
                "schema": SCHEMA,
                "strict": True,
            }
        },
    }
    return await _post(settings, "/responses", body)


async def _post(settings: Any, path: str, body: dict[str, Any]) -> dict[str, Any]:
    key = settings.apimaster_api_key.get_secret_value()
    base = settings.apimaster_base_url.rstrip("/")
    t0 = time.monotonic()
    async with httpx.AsyncClient(
        base_url=base,
        headers={"Authorization": f"Bearer {key}"},
        timeout=httpx.Timeout(300),
    ) as client:
        resp = await client.post(path, json=body)
    latency = time.monotonic() - t0
    try:
        payload = resp.json()
    except ValueError:
        payload = {"_raw": resp.text[:400]}
    return {
        "status": resp.status_code,
        "latency_s": round(latency, 1),
        "payload": payload,
    }


def _summarise(result: dict[str, Any]) -> dict[str, Any]:
    payload = result["payload"]
    usage = payload.get("usage") or {}
    summary: dict[str, Any] = {
        "status": result["status"],
        "latency_s": result["latency_s"],
        "prompt_tokens": usage.get("prompt_tokens") or usage.get("input_tokens"),
        "completion_tokens": usage.get("completion_tokens")
        or usage.get("output_tokens"),
        "cost": usage.get("cost"),
    }
    text = ""
    if "choices" in payload:
        text = payload["choices"][0]["message"].get("content") or ""
    elif "output_text" in payload:
        text = payload["output_text"] or ""
    elif "output" in payload:
        for item in payload["output"]:
            for part in item.get("content", []):
                if part.get("type") in ("output_text", "text"):
                    text += part.get("text", "")
    summary["raw_text_len"] = len(text)
    try:
        parsed = json.loads(text)
        summary["schema_ok"] = isinstance(parsed.get("objections"), list) and bool(
            parsed.get("overall_assessment")
        )
        summary["objection_count"] = len(parsed.get("objections") or [])
    except (ValueError, AttributeError):
        summary["schema_ok"] = False
        summary["objection_count"] = 0
    return summary


async def run() -> dict[str, Any]:
    settings = get_settings()
    tasks = [
        ("counterargument_steelman", TASK_A_INPUT),
        ("epistemic_drift_audit", TASK_B_INPUT),
    ]
    out: dict[str, Any] = {"model": MODEL, "tasks": {}}
    for task_name, text in tasks:
        out["tasks"][task_name] = {}
        for endpoint, fn in (("chat", _chat), ("responses", _responses)):
            try:
                raw = await fn(settings, task_name, text)
                summary = _summarise(raw)
                summary["error"] = None
                if raw["status"] != 200:
                    body = raw["payload"]
                    summary["error"] = str(
                        (body.get("error") or {}).get("code") or body
                    )[:200]
            except Exception as exc:  # probe must record, not crash
                summary = {"status": -1, "error": type(exc).__name__}
            out["tasks"][task_name][endpoint] = summary
            print(f"  {task_name} / {endpoint}: {summary}")
    return out


async def amain() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    result = await run()
    path = ARTIFACT_DIR / f"sol_chat_vs_responses_{int(time.time())}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
