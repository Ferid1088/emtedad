"""Independent scoring of short-form cases via the production critic provider.

Usage: uv run python -m benchmarks.qwen.run_critic_short 1|2

Sends all twelve case outputs of one loop in a single structured-extraction
call through the configured production provider (Devin) — the same critic
architecture that reviews production drafts — so Qwen never scores itself.
Merges results into ``short_loop{N}_scores.json``.
"""

import asyncio
import json
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.llm.factory import resolve_llm_provider

ARTIFACT_DIR = Path("docs/audits/qwen_benchmark")

DIMENSIONS = (
    "naturalness, spoken_fluency, grammar, idiomatic_vocabulary, "
    "semantic_correctness, terminology, nuance, epistemic_honesty, "
    "instruction_following, repetition_freedom, native_not_translated, "
    "attribution_discipline"
)


class CaseScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    naturalness: int = Field(ge=1, le=10)
    spoken_fluency: int = Field(ge=1, le=10)
    grammar: int = Field(ge=1, le=10)
    idiomatic_vocabulary: int = Field(ge=1, le=10)
    semantic_correctness: int = Field(ge=1, le=10)
    terminology: int = Field(ge=1, le=10)
    nuance: int = Field(ge=1, le=10)
    epistemic_honesty: int = Field(ge=1, le=10)
    instruction_following: int = Field(ge=1, le=10)
    repetition_freedom: int = Field(ge=1, le=10)
    native_not_translated: int = Field(ge=1, le=10)
    attribution_discipline: int = Field(ge=1, le=10)
    flags: list[str] = Field(default_factory=list)
    notes: str = ""


class ShortScorecard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scores: list[CaseScore]


async def main(loop: int) -> None:
    data = json.loads((ARTIFACT_DIR / f"short_loop{loop}.json").read_text("utf-8"))
    cases = [
        {
            "case_id": r["case_id"],
            "category": r["category"],
            "prompt": r["prompt"],
            "output": r["text"],
        }
        for r in data
    ]
    provider = resolve_llm_provider()
    result = await provider.extract(
        StructuredExtractionRequest(
            task="short_form_persian_benchmark_review",
            prompt_version="qwen_benchmark_critic_v1",
            model="configured-default",
            instructions=(
                "You are an independent Persian-language editorial critic "
                "evaluating LLM benchmark outputs for a spoken Persian "
                "educational program. For each case, score every dimension "
                "1-10 (integers): "
                + DIMENSIONS
                + ". native_not_translated: 10 means the text reads like it "
                "was conceived in Persian, not translated. Score honestly and "
                "harshly: look for overly literary register, English-like "
                "sentence structure, unnatural verbs, over-Arabicized "
                "vocabulary, awkward word order, repeated phrasing, "
                "motivational clichés, false certainty, wrong terminology, "
                "stereotypes, invented book claims, invented direct quotes, "
                "markdown/formatting leakage in spoken text. List concrete "
                "flags per case."
            ),
            input_text=json.dumps({"cases": cases}, ensure_ascii=False),
            output_model=ShortScorecard,
        )
    )
    card = ShortScorecard.model_validate(result.model_dump())
    out = ARTIFACT_DIR / f"short_loop{loop}_scores.json"
    out.write_text(
        json.dumps([s.model_dump() for s in card.scores], ensure_ascii=False, indent=1),
        "utf-8",
    )
    print("wrote", out)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1])))
