"""NarrativeArchitectAgent: narrative plan over an ArgumentPlan."""

import json

from app.briefs.models import ContentBrief
from app.content_engine.domain import NARRATIVE_PROMPT_VERSION
from app.content_engine.models import ArgumentPlanSection
from app.content_engine.schemas import NarrativePlanOutput
from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest

NARRATIVE_INSTRUCTIONS = """You are the Narrative Architect for one \
editorial channel production.

Input: a ContentBrief, an ArgumentPlan whose sections are labeled a1, a2, \
..., and story units labeled s1, s2, ... plus the channel narrative/style \
policies.

Produce an ordered narrative plan. Each section has ordinal, narrative_role \
(COLD_OPEN, SETUP, TURN, DEEPENING, CLIMAX, RESOLUTION, OUTRO), purpose, \
target_seconds, argument section refs, story unit refs, emotional_function, \
transition_in/out, and opening/ending methods.

Hard rules:
- Sum of target_seconds should approximate the brief's target duration.
- Every story unit ref must exist in the input.
- No final script — structure only.
""".strip()


class NarrativeArchitectAgent:
    def __init__(self, provider: LLMProvider, *, model: str) -> None:
        self.provider = provider
        self.model = model

    async def plan(
        self,
        *,
        brief: ContentBrief,
        argument_sections: list[ArgumentPlanSection],
        story_units: list[tuple[str, str]],
        strategy_payload: dict[str, object],
    ) -> tuple[NarrativePlanOutput, dict[str, str]]:
        arg_labels = {
            f"a{i}": str(section.id) for i, section in enumerate(argument_sections, 1)
        }
        story_labels = {
            f"s{i}": unit_id for i, (unit_id, _title) in enumerate(story_units, 1)
        }
        payload = {
            "brief": {
                "question": brief.question,
                "thesis": brief.thesis,
                "angle": brief.angle,
                "target_duration_minutes": brief.target_duration_minutes,
            },
            "argument_sections": [
                {"ref": ref, "role": section.role, "purpose": section.purpose}
                for ref, section in zip(
                    arg_labels.keys(), argument_sections, strict=True
                )
            ],
            "story_units": [
                {"ref": ref, "title": title}
                for ref, (_uid, title) in zip(
                    story_labels.keys(), story_units, strict=True
                )
            ],
            "strategy": strategy_payload,
        }
        request = StructuredExtractionRequest(
            task="narrative_plan",
            prompt_version=NARRATIVE_PROMPT_VERSION,
            model=self.model,
            instructions=NARRATIVE_INSTRUCTIONS,
            input_text=json.dumps(payload, ensure_ascii=False),
            output_model=NarrativePlanOutput,
        )
        result = await self.provider.extract(request)
        labels = {**arg_labels, **story_labels}
        return NarrativePlanOutput.model_validate(result.model_dump()), labels
