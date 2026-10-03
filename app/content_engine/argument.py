"""ArgumentArchitectAgent: structured argument plan from brief + matrix."""

import json

from app.briefs.models import ContentBrief
from app.content_engine.domain import ARGUMENT_PROMPT_VERSION
from app.content_engine.schemas import ArgumentPlanOutput
from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.research.models import EvidenceMatrixItem

ARGUMENT_INSTRUCTIONS = """You are the Argument Architect for one editorial \
channel production.

Input: a ContentBrief (question, thesis, angle, forbidden claims) and an \
EvidenceMatrix whose items are labeled e1, e2, ... plus story units s1, s2, ...

Produce an ordered argument plan. Each section has an ordinal, a role \
(HOOK, CLAIM, EVIDENCE, COUNTERARGUMENT, RESOLUTION, CONTEXT, EXAMPLE, \
STORY), a purpose, references to evidence item labels, story unit labels, \
and counterargument labels; plus transition_intent, must_include, and \
must_not_claim lists.

Hard rules:
- Reference only labels you were given; never invent evidence.
- must_not_claim must include every brief forbidden claim.
- No final prose — structure only.
""".strip()


class ArgumentArchitectAgent:
    def __init__(self, provider: LLMProvider, *, model: str) -> None:
        self.provider = provider
        self.model = model

    async def plan(
        self,
        *,
        brief: ContentBrief,
        items: list[EvidenceMatrixItem],
        story_units: list[tuple[str, str]],
        strategy_payload: dict[str, object],
    ) -> tuple[ArgumentPlanOutput, dict[str, str]]:
        item_labels = {f"e{i}": str(item.id) for i, item in enumerate(items, 1)}
        story_labels = {ref: uid for ref, (uid, _t) in enumerate_pairs(story_units)}
        payload = {
            "brief": {
                "question": brief.question,
                "thesis": brief.thesis,
                "angle": brief.angle,
                "forbidden_claims": brief.forbidden_claims_json,
                "required_counterargument": brief.required_counterargument,
                "required_evidence_roles": brief.required_evidence_roles_json,
            },
            "evidence_items": [
                {
                    "ref": ref,
                    "claim_text": item.claim_text,
                    "role": item.role.value,
                    "epistemic_status": item.epistemic_status,
                    "allowed_wording": item.allowed_wording,
                    "forbidden_wording": item.forbidden_wording,
                }
                for ref, item in zip(item_labels.keys(), items, strict=True)
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
            task="argument_plan",
            prompt_version=ARGUMENT_PROMPT_VERSION,
            model=self.model,
            instructions=ARGUMENT_INSTRUCTIONS,
            input_text=json.dumps(payload, ensure_ascii=False),
            output_model=ArgumentPlanOutput,
        )
        result = await self.provider.extract(request)
        labels = {**item_labels, **story_labels}
        return ArgumentPlanOutput.model_validate(result.model_dump()), labels


def enumerate_pairs(
    story_units: list[tuple[str, str]],
) -> list[tuple[str, tuple[str, str]]]:
    """Pair s-labels with (unit_id, title) tuples."""

    return [(f"s{index}", unit) for index, unit in enumerate(story_units, 1)]
