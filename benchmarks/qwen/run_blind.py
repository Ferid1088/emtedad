"""Blind A/B comparison: Qwen benchmark draft vs production baseline.

Usage:
  uv run python -m benchmarks.qwen.run_blind <fileA> <fileB> <tag>

Texts are anonymized (no model identity) and randomly assigned to
slots A/B before the independent production critic compares them.
"""

import asyncio
import json
import random
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.llm.factory import resolve_llm_provider

ARTIFACT_DIR = Path("docs/audits/qwen_benchmark")


class BlindVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    naturalness: Literal["A", "B", "TIE"]
    spoken_rhythm: Literal["A", "B", "TIE"]
    narrative_quality: Literal["A", "B", "TIE"]
    factual_discipline: Literal["A", "B", "TIE"]
    epistemic_honesty: Literal["A", "B", "TIE"]
    book_reference_quality: Literal["A", "B", "TIE"]
    publishability: Literal["A", "B", "TIE"]
    justification: str = Field(min_length=1)


async def main(path_a: str, path_b: str, tag: str) -> None:
    texts = [Path(path_a).read_text("utf-8"), Path(path_b).read_text("utf-8")]
    order = [0, 1]
    random.Random(7).shuffle(order)  # deterministic anonymization
    slot_a, slot_b = texts[order[0]], texts[order[1]]
    # map: order[0]==0 → slot A is the Qwen text when path_a was qwen
    provider = resolve_llm_provider()
    result = await provider.extract(
        StructuredExtractionRequest(
            task="blind_script_comparison",
            prompt_version="qwen_benchmark_blind_v1",
            model="configured-default",
            instructions=(
                "You are an independent Persian editorial judge comparing two "
                "spoken-Persian script drafts, labeled A and B, for the same "
                "production brief. You do not know which system wrote which. "
                "For each axis pick A, B, or TIE: naturalness (sounds written "
                "by a native for the ear, not translated), spoken_rhythm, "
                "narrative_quality (movement, beats, ending), "
                "factual_discipline (no invented claims/details), "
                "epistemic_honesty (uncertainty preserved), "
                "book_reference_quality (safe, real, non-fabricated "
                "attributions), publishability (ready to voice as-is). "
                "Judge harshly; justify briefly."
            ),
            input_text=json.dumps(
                {"draft_A": slot_a, "draft_B": slot_b}, ensure_ascii=False
            ),
            output_model=BlindVerdict,
        )
    )
    verdict = BlindVerdict.model_validate(result.model_dump())
    out = {
        "tag": tag,
        "slot_A_is": Path(path_a).name if order[0] == 0 else Path(path_b).name,
        "slot_B_is": Path(path_b).name if order[0] == 0 else Path(path_a).name,
        "verdict": verdict.model_dump(),
    }
    (ARTIFACT_DIR / f"blind_{tag}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), "utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
