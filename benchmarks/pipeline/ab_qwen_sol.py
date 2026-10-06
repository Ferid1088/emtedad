"""Real role-level A/B: qwen3.8-flash vs gpt-6.1-sol (APIMaster).

Runs four production roles against real Emtedad data on BOTH models with
identical inputs, schemas and instructions:

    TOPIC_MINER      — real channel units via the production TopicMiner
    SEARCH_PLANNER   — real ContentBriefs → retrieval plan
    SEARCH_QUERY     — real ContentBriefs → concrete search queries
    COUNTERARGUMENT  — real briefs + claims → steel-manned objections

Every call is recorded to ``ops.llm_call_events`` (run_scope='ab_test').
Outputs + an Astra judge pass are written to
``benchmarks/pipeline/artifacts/ab_qwen_sol_<loop>_<ts>.json``.

    uv run python -m benchmarks.pipeline.ab_qwen_sol --loop 1
    uv run python -m benchmarks.pipeline.ab_qwen_sol --loop 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

# Register FK-target tables used below.
from app.briefs import models as _brief_models  # noqa: F401
from app.briefs.models import ContentBrief
from app.content_engine import models as _ce_models  # noqa: F401
from app.content_strategy import models as _cs_models  # noqa: F401
from app.core.config import get_settings
from app.db.session import Database
from app.editorial_channels import models as _ec_models  # noqa: F401
from app.editorial_channels.models import EditorialChannel
from app.knowledge import models as _k_models  # noqa: F401
from app.knowledge.llm import models as _llm_models  # noqa: F401
from app.knowledge.llm.apimaster import APIMasterConfig, APIMasterProvider
from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.llm.telemetry import DatabaseLLMRecorder
from app.knowledge.units import models as _ku_models  # noqa: F401
from app.knowledge.units.models import KnowledgeUnit
from app.ops.settings import models as _set_models  # noqa: F401
from app.topics import models as _topic_models  # noqa: F401
from app.topics.miner import TopicMiner

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
MODELS = ("qwen3.8-flash", "gpt-6.1-sol")
JUDGE_MODEL = "gpt-6-astra"
CASES_PER_ROLE = 5
AB_PROMPT_VERSION = "ab-qwen-sol.v1"


# --- Role output schemas (same for both models) ----------------------------


class SearchPlanOutput(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=12)
    rationale: str
    counterevidence_query: str
    priority_order: list[int]


class SearchQueryOutput(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=10)
    counterevidence_queries: list[str] = Field(min_length=1, max_length=4)
    language: str


class CounterargumentOutput(BaseModel):
    counterarguments: list[str] = Field(min_length=1, max_length=6)
    weakest_claim: str
    evidence_gap: str


class JudgeOutput(BaseModel):
    content_quality: float = Field(ge=0, le=10)
    persian_quality: float = Field(ge=0, le=10)
    evidence_discipline: float = Field(ge=0, le=10)
    notes: str


# --- Instructions ----------------------------------------------------------

PLANNER_INSTRUCTIONS = """You plan external web research for an evidence-grounded lecture.
Given the brief (question, thesis) and known evidence gaps, return a retrieval plan:
- queries: concrete web search strings (mixed language ok, prefer the brief's language)
- rationale: why these queries cover the gaps
- counterevidence_query: one query explicitly hunting disconfirming evidence
- priority_order: indexes of queries by importance
Do not invent sources. Queries must be real-world searchable.""".strip()

QUERY_INSTRUCTIONS = """You generate concrete search queries for an evidence-grounded lecture.
Given the brief, thesis and evidence gaps, return:
- queries: specific, real-world search strings (prefer the brief's language)
- counterevidence_queries: queries hunting disconfirming evidence
- language: dominant language of the queries (BCP-47)
Be specific — named studies, populations, mechanisms — not generic terms.""".strip()

COUNTERARG_INSTRUCTIONS = """You steel-man objections against a lecture's thesis and claims.
Given the brief, thesis, claims and supporting evidence, return:
- counterarguments: the strongest honest objections a critical viewer could raise
- weakest_claim: which stated claim is least supported and why
- evidence_gap: what evidence is missing that a skeptic would demand
Do not strawman. Objections must be ones a fair expert could hold.""".strip()

JUDGE_INSTRUCTIONS = """You judge role-level LLM output quality for a Persian-first lecture platform.
Score the MODEL OUTPUT against the TASK and INPUT on three 0-10 axes:
- content_quality: usefulness, specificity, completeness for the role's job
- persian_quality: natural, fluent Persian where Persian was requested (10 if no Persian required and output is clean)
- evidence_discipline: no invented sources/claims; grounding respected; honest gaps
Return notes briefly naming strengths/defects.""".strip()


# --- Case builders ---------------------------------------------------------


async def _topic_cases(db: Database, loop: int) -> list[dict[str, Any]]:
    """Five real unit windows: different channels/offsets per loop."""

    async with db.transaction() as session:
        channels = (
            (
                await session.execute(
                    select(EditorialChannel).order_by(EditorialChannel.slug)
                )
            )
            .scalars()
            .all()
        )
        cases: list[dict[str, Any]] = []
        offset_base = 0 if loop == 1 else 60
        for channel in channels[:CASES_PER_ROLE]:
            units = (
                (
                    await session.execute(
                        select(KnowledgeUnit)
                        .order_by(KnowledgeUnit.created_at)
                        .offset(offset_base + 30 * len(cases))
                        .limit(30)
                    )
                )
                .scalars()
                .all()
            )
            if not units:
                continue
            session.expunge_all()
            cases.append(
                {
                    "case_id": f"topic_{channel.slug}",
                    "channel_slug": channel.slug,
                    "units": units,
                }
            )
        return cases


async def _brief_cases(db: Database, loop: int) -> list[ContentBrief]:
    async with db.transaction() as session:
        rows = (
            (
                await session.execute(
                    select(ContentBrief)
                    .order_by(ContentBrief.created_at.desc())
                    .offset(0 if loop == 1 else CASES_PER_ROLE)
                    .limit(CASES_PER_ROLE)
                )
            )
            .scalars()
            .all()
        )
        session.expunge_all()
        return list(rows)


# --- Call runner -----------------------------------------------------------


def _provider(settings: Any, model: str, db: Database, role: str) -> APIMasterProvider:
    return APIMasterProvider(
        APIMasterConfig(
            api_key=settings.apimaster_api_key.get_secret_value()
            if settings.apimaster_api_key
            else None,
            model=model,
            max_retries=1,
        ),
        recorder=DatabaseLLMRecorder(db, run_scope="ab_test"),
        agent_role=role,
    )


async def _call(
    provider: APIMasterProvider,
    *,
    task: str,
    instructions: str,
    payload: dict[str, Any],
    output_model: type[BaseModel],
) -> tuple[BaseModel | None, str]:
    try:
        result = await provider.extract(
            StructuredExtractionRequest(
                task=task,
                prompt_version=AB_PROMPT_VERSION,
                model=provider.config.model,
                instructions=instructions,
                input_text=json.dumps(payload, ensure_ascii=False),
                output_model=output_model,
            )
        )
        return result, ""
    except Exception as exc:  # noqa: BLE001 — record failure honestly
        return None, f"{type(exc).__name__}: {exc}"[:300]


async def _judge(
    judge: APIMasterProvider,
    *,
    role: str,
    task_input: dict[str, Any],
    output: BaseModel | None,
) -> dict[str, Any] | None:
    if output is None:
        return None
    result, error = await _call(
        judge,
        task=f"ab_judge_{role.lower()}",
        instructions=JUDGE_INSTRUCTIONS,
        payload={
            "role": role,
            "task_input": task_input,
            "model_output": output.model_dump(),
        },
        output_model=JudgeOutput,
    )
    return result.model_dump() if result else {"judge_error": error}


async def run_loop(db: Database, loop: int) -> dict[str, Any]:
    settings = get_settings()
    providers = {model: _provider(settings, model, db, "AB_TEST") for model in MODELS}
    judge = _provider(settings, JUDGE_MODEL, db, "AB_JUDGE")
    artifact: dict[str, Any] = {
        "loop": loop,
        "models": list(MODELS),
        "cases": [],
    }
    strategy_payload: dict[str, object] = {
        "core_question": "evidence-grounded lecture topics",
        "preferred_angles": ["mechanism", "human story"],
        "forbidden_angles": [],
    }

    # --- TOPIC_MINER — real production TopicMiner ----------------------------
    for case in await _topic_cases(db, loop):
        row: dict[str, Any] = {
            "role": "TOPIC_MINER",
            "case_id": case["case_id"],
            "results": {},
        }
        for model, provider in providers.items():
            miner = TopicMiner(provider, model=model)
            started = time.monotonic()
            try:
                batch, _labels = await miner.propose(
                    strategy_payload=strategy_payload,
                    units=case["units"],
                    published_signatures=[],
                    editorial_language="fa",
                )
                output: BaseModel | None = batch
                error = ""
            except Exception as exc:  # noqa: BLE001
                output, error = None, f"{type(exc).__name__}: {exc}"[:300]
            judge_result = await _judge(
                judge,
                role="TOPIC_MINER",
                task_input={
                    "strategy": strategy_payload,
                    "unit_count": len(case["units"]),
                },
                output=output,
            )
            row["results"][model] = {
                "latency_s": round(time.monotonic() - started, 2),
                "error": error,
                "output": output.model_dump() if output else None,
                "judge": judge_result,
            }
            print(
                f"TOPIC_MINER {case['case_id']} {model}: "
                f"{'OK' if output else error[:60]}"
            )
        artifact["cases"].append(row)

    # --- SEARCH_PLANNER / SEARCH_QUERY / COUNTERARGUMENT — real briefs -------
    briefs = await _brief_cases(db, loop)
    for brief in briefs:
        brief_payload = {
            "question": brief.question,
            "thesis": brief.thesis,
            "angle": brief.angle,
            "target_audience": brief.target_audience,
        }
        roles: list[
            tuple[str, str, dict[str, object], type[BaseModel]]
        ] = [
            (
                "SEARCH_PLANNER",
                PLANNER_INSTRUCTIONS,
                {
                    "brief": brief_payload,
                    "thesis": brief.thesis,
                    "evidence_gaps": [
                        "external empirical support",
                        "counterevidence scan",
                    ],
                    "source_policy": "prefer primary/academic, then reputable secondary",
                    "language": "fa",
                },
                SearchPlanOutput,
            ),
            (
                "SEARCH_QUERY",
                QUERY_INSTRUCTIONS,
                {
                    "brief": brief_payload,
                    "thesis": brief.thesis,
                    "evidence_gaps": ["named studies", "mechanisms", "critiques"],
                    "source_policy": "searchable strings only",
                    "language": "fa",
                },
                SearchQueryOutput,
            ),
            (
                "COUNTERARGUMENT",
                COUNTERARG_INSTRUCTIONS,
                {
                    "brief": brief_payload,
                    "thesis": brief.thesis,
                    "claims": [brief.thesis],
                    "evidence": ["channel knowledge units (labels only)"],
                    "language": "fa",
                },
                CounterargumentOutput,
            ),
        ]
        for role, instructions, payload, output_model in roles:
            row = {
                "role": role,
                "case_id": f"brief_{brief.id}",
                "results": {},
            }
            for model, provider in providers.items():
                started = time.monotonic()
                output, error = await _call(
                    provider,
                    task=role.lower(),
                    instructions=instructions,
                    payload=payload,
                    output_model=output_model,
                )
                judge_result = await _judge(
                    judge, role=role, task_input=payload, output=output
                )
                row["results"][model] = {
                    "latency_s": round(time.monotonic() - started, 2),
                    "error": error,
                    "output": output.model_dump() if output else None,
                    "judge": judge_result,
                }
                print(
                    f"{role} brief={str(brief.id)[:8]} {model}: "
                    f"{'OK' if output else error[:60]}"
                )
            artifact["cases"].append(row)
    return artifact


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", type=int, required=True, choices=(1, 2))
    args = parser.parse_args()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    db = Database(get_settings().database_url.get_secret_value())
    try:
        artifact = await run_loop(db, args.loop)
        out = ARTIFACT_DIR / f"ab_qwen_sol_loop{args.loop}_{int(time.time())}.json"
        out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2))
        print(f"\nwrote {out}")
        return 0
    finally:
        await db.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
