"""Run one short-form Persian benchmark loop against Qwen.

Usage: uv run python -m benchmarks.qwen.run_short 1|2

Writes ``docs/audits/qwen_benchmark/short_loop{N}.json`` with the raw
text, sha256, telemetry summary, and deterministic-check findings per
case. Qualitative critic scoring is merged separately (see report).
"""

import asyncio
import hashlib
import json
import sys
import unicodedata
from pathlib import Path

from app.content_engine.writing.native import PersianNativeReviewer
from app.content_engine.writing.quality import (
    PersianDraftQualityValidator,
    word_count,
)
from benchmarks.qwen.cases import LOOP1, LOOP2, SYSTEM_FA
from benchmarks.qwen.client import OpenRouterBenchmarkClient

ARTIFACT_DIR = Path("docs/audits/qwen_benchmark")


def _deterministic(text: str) -> dict:
    quality = PersianDraftQualityValidator().validate(text, [])
    native = PersianNativeReviewer().review(text)
    cf_chars = sum(1 for c in text if unicodedata.category(c) == "Cf" and c != "‌")
    return {
        "ufffd_count": text.count("\ufffd"),
        "cf_control_chars": cf_chars,
        "word_count": word_count(text),
        "quality_findings": [
            {"code": f.code, "blocking": f.blocking, "message": f.message}
            for f in quality.findings
        ],
        "repetition_ratio": round(quality.repetition_ratio, 3),
        "native_findings": [
            {"code": f.code, "severity": f.severity, "message": f.message}
            for f in native
        ],
    }


async def main(loop: int) -> None:
    cases = LOOP1 if loop == 1 else LOOP2
    client = OpenRouterBenchmarkClient(timeout_seconds=180)
    if not client.has_key:
        raise SystemExit("OpenRouter API key missing")
    results = []
    for case in cases:
        try:
            content, telemetry = await client.chat(
                [
                    {"role": "system", "content": SYSTEM_FA},
                    {"role": "user", "content": case["prompt"]},
                ],
                task="short_form",
                case_id=case["case_id"],
                max_tokens=4096,
                save_name=f"short-{case['case_id']}",
            )
            error = ""
        except Exception as exc:  # record, don't abort the loop
            content, telemetry, error = "", {}, str(exc)[:300]
        results.append(
            {
                "case_id": case["case_id"],
                "category": case["category"],
                "prompt": case["prompt"],
                "text": content,
                "text_sha256": hashlib.sha256(content.encode()).hexdigest()
                if content
                else "",
                "telemetry": {
                    "latency_ms": telemetry.get("latency_ms"),
                    "prompt_tokens": telemetry.get("prompt_tokens"),
                    "completion_tokens": telemetry.get("completion_tokens"),
                    "cost": telemetry.get("cost"),
                    "provider": telemetry.get("provider"),
                },
                "error": error,
                "deterministic": _deterministic(content) if content else {},
            }
        )
        print(case["case_id"], "done" if content else f"FAILED: {error}")
    out = ARTIFACT_DIR / f"short_loop{loop}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), "utf-8")
    print("wrote", out)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1])))
