"""Concept mapping: link Knowledge Units to shared ExternalConcepts.

Source structure answers "what did this source say, in what order"; the
concept graph answers "how does this knowledge relate across sources". The
two hierarchies stay separate.
"""

import logging

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.models import ExternalConcept

logger = logging.getLogger(__name__)


class ConceptProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_name: str = Field(min_length=1, max_length=512)
    relation_role: str = Field(default="MENTIONED", max_length=32)
    confidence: float = Field(default=0.5, ge=0, le=1)


class UnitConceptBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concepts: list[ConceptProposal] = Field(default_factory=list)


def normalize_concept_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


async def resolve_concept(
    session: AsyncSession, canonical_name: str
) -> ExternalConcept:
    normalized = normalize_concept_name(canonical_name)
    existing = await session.scalar(
        select(ExternalConcept).where(
            func.lower(ExternalConcept.normalized_name) == normalized
        )
    )
    if existing is not None:
        return existing
    concept = ExternalConcept(
        canonical_name=canonical_name.strip(), normalized_name=normalized
    )
    session.add(concept)
    await session.flush()
    return concept


CONCEPT_PROMPT_VERSION = "unit_concept_mapping_v1"

CONCEPT_INSTRUCTIONS = """You map a Knowledge Unit to the concepts it \
expresses.

Return canonical concept names (not translations of the unit title), a \
relation role (PRIMARY_TOPIC, MENTIONED, SUPPORTING, CONTRASTING), and a \
confidence.

Rules:
- Do not invent concepts absent from the text.
- Reuse established, general concept names; avoid one-off phrasings.
- Prefer 0-5 precise concepts over many vague ones.
""".strip()
