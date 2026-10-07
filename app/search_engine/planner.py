"""Query planner agent: writes native search queries per language.

The LLM only proposes queries; results always come from the real search
backend. One planner call per language, run in parallel.
"""

import json

from pydantic import BaseModel, Field

from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.knowledge.llm.context import guard_payload
from app.knowledge.llm.roles import AgentRole

PROMPT_VERSION = "search_query_planner_v1"

_INSTRUCTIONS = (
    "You plan web searches for researching a topic. Write search queries in "
    "the requested language, phrased the way a native speaker or scholar "
    "would search (for Persian: Persian script, common Persian terminology "
    "and spelling variants; for English: established English terms and "
    "transliterations). Cover different angles: definitions and core "
    "concepts, primary texts and their authors, scholarly analysis, history "
    "and context, criticism and opposing views, and every listed evidence "
    "gap. Prefer queries that find academic papers, encyclopedias and "
    "primary texts. Do not repeat previous queries. Return only queries — "
    "never answers or URLs."
)


class PlannedQueries(BaseModel):
    queries: list[str] = Field(default_factory=list)


class QueryPlanner:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def plan(
        self,
        *,
        topic: str,
        thesis: str,
        gaps: list[str],
        language: str,
        max_queries: int,
        previous: list[str],
    ) -> list[str]:
        payload = {
            "brief": topic,
            "thesis": thesis,
            "evidence_gaps": gaps[:15],
            "language": language,
            "source_policy": {
                "max_queries": max_queries,
                "previous_queries": previous[-30:],
            },
        }
        guard_payload(AgentRole.SEARCH_PLANNER, payload)
        result = await self.provider.extract(
            StructuredExtractionRequest(
                task="search_query_planning",
                prompt_version=PROMPT_VERSION,
                model="configured-default",
                instructions=_INSTRUCTIONS,
                input_text=json.dumps(payload, ensure_ascii=False),
                output_model=PlannedQueries,
                timeout_seconds=120,
            )
        )
        planned = PlannedQueries.model_validate(result.model_dump())
        seen = {q.strip().lower() for q in previous}
        queries: list[str] = []
        for query in planned.queries:
            text = query.strip()
            if text and text.lower() not in seen:
                seen.add(text.lower())
                queries.append(text)
        return queries[:max_queries]
