"""Section-parallel script writing (TrueCrime act-writer pattern).

The Semantic Master is the director's plan: every section already has a
narrative role, purpose, target word budget and transition intent. One
writer agent per section works in parallel, seeing only its own section,
its own claims and short notes about its neighbours. A transition editor
then smooths the joins; its result is kept only if it does not change the
length materially (otherwise the joined sections are used).
"""

import asyncio
import json
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest

SECTION_PROMPT_VERSION = "section_writer_v1"
EDITOR_PROMPT_VERSION = "transition_editor_v1"

SECTION_ADDENDUM = """
You write ONLY ONE SECTION of the script — the one in "section". Other \
writers write the other sections at the same time. Rules:
- Realize this section's purpose and narrative role and land close to its \
target_words (±10%).
- Use only this section's claims (plus general framing); never anticipate \
or repeat what the neighbouring sections cover (see "previous_section" and \
"next_section" — purposes only).
- Open with a short natural link from the previous section's purpose and \
end so the next section can follow (its transition_intent), unless this is \
the first or last section.
- No headings, no section labels, no lists — continuous spoken prose.
Return only this section's text and its duration estimate.
"""

EDITOR_INSTRUCTIONS = """You are the transition editor of a spoken script \
whose sections were written in parallel by different writers. Smooth ONLY \
the joins between sections and remove accidental repetitions across \
sections, so the whole reads as one voice. Do not change facts, claims, \
quotations, qualifiers, structure or order; do not shorten or lengthen \
the script (stay within ±3% of its length). Return the full script text."""


class _SectionText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    estimated_duration_seconds: int = Field(default=0, ge=0)


class _EditedText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)


async def write_sections_parallel(
    *,
    provider: LLMProvider,
    model: str,
    base_instructions: str,
    base_payload: dict[str, object],
    sections: Sequence[dict[str, object]],
    claims_by_section: dict[int, list[dict[str, object]]],
    general_claims: list[dict[str, object]],
    concurrency: int = 6,
) -> list[str]:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    count = len(sections)

    async def write(index: int) -> str:
        section = sections[index]
        ordinal = int(str(section.get("ordinal", index)))
        payload = {
            **base_payload,
            "section": section,
            "section_position": f"{index + 1} of {count}",
            "previous_section": (
                {k: sections[index - 1].get(k) for k in ("purpose", "narrative_role")}
                if index > 0
                else None
            ),
            "next_section": (
                {
                    k: sections[index + 1].get(k)
                    for k in ("purpose", "narrative_role", "transition_intent")
                }
                if index + 1 < count
                else None
            ),
            "claims": claims_by_section.get(ordinal, []) + general_claims,
        }
        async with semaphore:
            result = await provider.extract(
                StructuredExtractionRequest(
                    task="script_section",
                    prompt_version=SECTION_PROMPT_VERSION,
                    model=model,
                    instructions=base_instructions + "\n\n" + SECTION_ADDENDUM,
                    input_text=json.dumps(payload, ensure_ascii=False),
                    output_model=_SectionText,
                )
            )
        return _SectionText.model_validate(result.model_dump()).text.strip()

    return list(await asyncio.gather(*(write(i) for i in range(count))))


async def smooth_transitions(
    *, provider: LLMProvider, model: str, text: str, language: str
) -> str:
    """Editor pass; falls back to the joined text if it changes the length
    by more than 8% or fails."""

    try:
        result = await provider.extract(
            StructuredExtractionRequest(
                task="script_transition_edit",
                prompt_version=EDITOR_PROMPT_VERSION,
                model=model,
                instructions=EDITOR_INSTRUCTIONS,
                input_text=json.dumps(
                    {"script": text, "language": language}, ensure_ascii=False
                ),
                output_model=_EditedText,
            )
        )
        edited = _EditedText.model_validate(result.model_dump()).text.strip()
    except Exception:  # noqa: BLE001 — the joined sections are still valid
        return text
    before, after = len(text.split()), len(edited.split())
    if before and abs(after - before) / before > 0.08:
        return text
    return edited
