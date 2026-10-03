"""Topic mining: LLM proposals grounded in labeled Knowledge Units."""

import json
from uuid import UUID

from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.knowledge.units.models import KnowledgeUnit
from app.topics.domain import TOPIC_PROMPT_VERSION
from app.topics.schemas import TopicMiningBatch

MINER_INSTRUCTIONS = """You mine video topic candidates for one editorial \
channel from its assigned knowledge base.

You receive: the channel strategy (core question, preferred/forbidden \
angles), a labeled list of Knowledge Units (u1, u2, ...) with their concepts, \
and published topic signatures for novelty awareness.

Return topic candidates with:
- video_question: the driving question the video answers
- tentative_thesis: the current best answer the evidence supports
- angle: the channel-specific framing
- supporting_unit_refs: the u-labels of units this topic rests on
- supporting_concepts: canonical concept names involved
- knowledge_gaps: what the sources do NOT answer
- channel_fit_reason and 0-1 scores for curiosity, emotional_relevance, \
practical_value, channel_fit

Rules:
- Do not invent evidence. Every candidate must cite real unit refs.
- High curiosity with weak unit grounding is fine — mark the gap honestly.
- Respect forbidden angles.
""".strip()

_LANGUAGE_NAMES = {
    "fa": "Persian (Farsi)",
    "en": "English",
    "de": "German",
    "ar": "Arabic",
}


class TopicMiner:
    def __init__(self, provider: LLMProvider, *, model: str) -> None:
        self.provider = provider
        self.model = model

    async def propose(
        self,
        *,
        strategy_payload: dict[str, object],
        units: list[KnowledgeUnit],
        published_signatures: list[str],
        owner_instruction: str | None = None,
        editorial_language: str = "fa",
        language_correction: bool = False,
    ) -> tuple[TopicMiningBatch, dict[str, UUID]]:
        labels = {f"u{index}": unit.id for index, unit in enumerate(units, 1)}
        payload = {
            "strategy": strategy_payload,
            "knowledge_units": [
                {
                    "ref": ref,
                    "unit_id_label": ref,
                    "title": unit.title,
                    "summary": unit.summary,
                    "unit_type": unit.unit_type.value,
                }
                for ref, unit in zip(labels.keys(), units, strict=True)
            ],
            "published_signatures": published_signatures,
            "owner_instruction": owner_instruction,
        }
        language_name = _LANGUAGE_NAMES.get(editorial_language, editorial_language)
        instructions = (
            MINER_INSTRUCTIONS
            + f"\n- Write title, video_question, tentative_thesis, angle, "
            f"channel_fit_reason and knowledge_gaps entirely in {language_name}. "
            "The source units may be in another language; the channel's "
            "editorial language always wins."
        )
        if language_correction:
            instructions += (
                f"\n- CORRECTION: your previous answer was in the wrong "
                f"language. Every text field must be {language_name}."
            )
        request = StructuredExtractionRequest(
            task="topic_mining",
            prompt_version=TOPIC_PROMPT_VERSION,
            model=self.model,
            instructions=instructions,
            input_text=json.dumps(payload, ensure_ascii=False),
            output_model=TopicMiningBatch,
        )
        result = await self.provider.extract(request)
        return TopicMiningBatch.model_validate(result.model_dump()), labels
