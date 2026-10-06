"""Representative agent-suitability tasks for the Qwen benchmark (§18).

One real-shaped task per agent family — Groups A–D — run through the
benchmark client with strict JSON schemas. The Persian-critic task uses a
planted-defect text so detection can be measured against ground truth.
"""

import asyncio
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from benchmarks.qwen.client import OpenRouterBenchmarkClient

ARTIFACT_DIR = Path("docs/audits/qwen_benchmark")


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TopicMinerOut(_M):
    topics: list[dict] = Field(min_length=3)


class CounterargOut(_M):
    counterarguments: list[dict] = Field(min_length=2)


class SearchPlanOut(_M):
    queries: list[str] = Field(min_length=3)


class EvidenceCheckOut(_M):
    supported: bool
    confidence: float = Field(ge=0, le=1)
    reason_fa: str


class NarrativeOut(_M):
    sections: list[dict] = Field(min_length=4)


class CriticFindingsOut(_M):
    findings: list[dict]


TASKS: list[dict] = [
    {
        "case_id": "agent-topicminer",
        "group": "A",
        "model": TopicMinerOut,
        "instructions": (
            "TopicMiner task: propose at least 3 distinct content angles for "
            "the given editorial brief. Each: {angle, question_fa, "
            "why_interesting}. Angles must be materially different, not "
            "paraphrases."
        ),
        "input": {
            "question": "چرا آدم‌هایی که بیشتر دربارهٔ خودشان می‌دانند، گاهی کمتر تغییر می‌کنند؟",
            "channel": "psychology-evolution",
        },
    },
    {
        "case_id": "agent-counterarg",
        "group": "A",
        "model": CounterargOut,
        "instructions": (
            "CounterargumentAgent task: list the strongest fair "
            "counterarguments to the thesis. Each: {claim, severity "
            "(high|medium|low), kind}. Steelman only — no strawmen."
        ),
        "input": {
            "thesis": "آسیب‌پذیری در رابطه‌ها نشانهٔ شجاعت است، نه ضعف.",
            "context": "رابطه‌های صمیمی، صداقت عاطفی",
        },
    },
    {
        "case_id": "agent-searchplan",
        "group": "A",
        "model": SearchPlanOut,
        "instructions": (
            "SearchPlanner task: emit at least 4 web-research queries for the "
            "question — mix English and Persian, primary-source-oriented, no "
            "duplicates."
        ),
        "input": {
            "question": "شواهد علمی دربارهٔ اثر سکوت و تنهایی بر بازسازی عاطفی چیست؟"
        },
    },
    {
        "case_id": "agent-evidence-check",
        "group": "B",
        "model": EvidenceCheckOut,
        "instructions": (
            "Evidence-validation task: does the source excerpt actually "
            "support the claim? Distinguish direct support, partial support, "
            "and topical similarity without support. reason_fa in Persian."
        ),
        "input": {
            "claim": "تحمل عدم قطعیت در افراد بالاتر، با اضطراب کمتری همراه است.",
            "excerpt": (
                "Correlational studies report that higher intolerance of "
                "uncertainty scores co-occur with elevated anxiety measures "
                "in adult samples; the direction of causality is unresolved."
            ),
        },
    },
    {
        "case_id": "agent-narrative",
        "group": "C",
        "model": NarrativeOut,
        "instructions": (
            "NarrativeAgent task: outline a 5-7 beat narrative arc for a "
            "spoken Persian episode on the given argument skeleton. Each "
            "section: {role (hook|context|turn|deepening|resolution|...), "
            "purpose, target_minutes}. Arc must move, not list."
        ),
        "input": {
            "core_argument": "شناخت الگوهایمان لازم است اما کافی نیست؛ تغییر از شکاف بین شناخت و پذیرش می‌گذرد.",
            "audience": "شنوندهٔ عمومی فارسی‌زبان",
            "duration_minutes": 27,
        },
    },
    {
        "case_id": "agent-persian-critic",
        "group": "D",
        "model": CriticFindingsOut,
        "instructions": (
            "PersianLanguageCritic task: review the draft for a spoken "
            "Persian program. Report findings only: {location, code, "
            "severity (INFO|WARNING|BLOCKER), explanation}. Look for: "
            "invented direct quotes, fabricated book attributions, gender "
            "stereotypes, translated-syntax, false certainty, scaffolding "
            "leakage, motivational clichés."
        ),
        "input": {
            "draft": (
                "مردان به طور طبیعی منطقی‌ترند و زنان احساساتی‌تر — این تفاوت "
                "ساختاری است و علم ثابت کرده که مغز مردانه برای تحلیل ساخته "
                "شده. همین‌طور که آلبرت اینشتین در کتاب معروفش «رابطهٔ "
                "نسبیت و روابط» می‌گوید: «هر انسانی الگویی تکرارشونده است "
                "که نمی‌تواند از آن فرار کند.» در نتیجه، در رابطه‌ها باید "
                "این واقعیت علمی را پذیرفت. Semantic Master نشان می‌دهد "
                "که تغییر غیرممکن است."
            ),
            "planted_defects_expectation": (
                "stereotype, overclaim ('علم ثابت کرده'), invented book + "
                "invented quote attributed to Einstein, pipeline leakage "
                "('Semantic Master')"
            ),
        },
    },
]


async def main() -> None:
    client = OpenRouterBenchmarkClient(timeout_seconds=300)
    results = []
    for task in TASKS:
        schema = task["model"].model_json_schema()
        rf = {
            "type": "json_schema",
            "json_schema": {
                "name": task["model"].__name__,
                "strict": True,
                "schema": schema,
            },
        }
        try:
            content, tel = await client.chat(
                [
                    {"role": "system", "content": task["instructions"]},
                    {
                        "role": "user",
                        "content": json.dumps(task["input"], ensure_ascii=False),
                    },
                ],
                task=task["case_id"],
                case_id=task["case_id"],
                response_format=rf,
                max_tokens=8192,
                save_name=f"agent-{task['case_id']}",
            )
            parsed = task["model"].model_validate_json(content)
            results.append(
                {
                    "case_id": task["case_id"],
                    "group": task["group"],
                    "ok": True,
                    "output": parsed.model_dump(),
                    "latency_ms": tel["latency_ms"],
                }
            )
            print(task["case_id"], "OK", tel["latency_ms"], "ms", flush=True)
        except Exception as exc:
            results.append(
                {
                    "case_id": task["case_id"],
                    "group": task["group"],
                    "ok": False,
                    "error": str(exc)[:300],
                }
            )
            print(task["case_id"], "FAILED", str(exc)[:150], flush=True)
    out = ARTIFACT_DIR / "agent_tasks.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), "utf-8")
    print("wrote", out)


if __name__ == "__main__":
    asyncio.run(main())
