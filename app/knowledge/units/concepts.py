"""Concept mapping: link Knowledge Units to shared ExternalConcepts.

Source structure answers "what did this source say, in what order"; the
concept graph answers "how does this knowledge relate across sources". The
two hierarchies stay separate.

Concepts are reusable semantic entities (``fear_of_abandonment``), never
sentence fragments. Reuse-first: normalize → exact canonical match →
alias-label match → only then create a new concept with its labels.
"""

import logging
import re
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.domain import LabelKind
from app.knowledge.models import EntityLabel, ExternalConcept
from app.knowledge.normalization import normalize_external_text
from app.retrieval.normalization import normalize_search_text

logger = logging.getLogger(__name__)

CONCEPT_ROLES = frozenset({"PRIMARY", "SECONDARY", "CONTEXT", "CONTRAST"})

_ROLE_ALIASES = {
    "PRIMARY_TOPIC": "PRIMARY",
    "MAIN": "PRIMARY",
    "MENTIONED": "CONTEXT",
    "SUPPORTING": "SECONDARY",
    "SECONDARY_TOPIC": "SECONDARY",
    "CONTRASTING": "CONTRAST",
    "EXAMPLE": "CONTEXT",
}

# Generic noise that carries no cross-source semantic value.
_NOISE_CONCEPTS = frozenset(
    {
        "people",
        "person",
        "human",
        "humans",
        "thing",
        "things",
        "stuff",
        "important",
        "example",
        "general",
        "other",
        "misc",
        "topic",
        "content",
        "text",
        "information",
        "idea",
        "concept",
        "point",
        "fact",
        "question",
        "answer",
        "انسان",
        "چیز",
        "مردم",
    }
)

_MAX_CONCEPT_WORDS = 6
_MIN_CONFIDENCE = 0.3
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


class ConceptProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_name: str = Field(
        min_length=1,
        max_length=512,
        validation_alias=AliasChoices("canonical_name", "name", "concept"),
    )
    relation_role: str = Field(default="CONTEXT", max_length=32)
    confidence: float = Field(default=0.5, ge=0, le=1)
    labels: dict[str, str] = Field(default_factory=dict)


class UnitConceptMapping(BaseModel):
    """Concepts proposed for one unit (echoed by its ``unit_ref`` label)."""

    model_config = ConfigDict(extra="forbid")

    unit_ref: str = Field(min_length=1)
    concepts: list[ConceptProposal] = Field(default_factory=list)


class UnitsConceptBatch(BaseModel):
    """One LLM call covers a batch of units."""

    model_config = ConfigDict(extra="forbid")

    mappings: list[UnitConceptMapping] = Field(default_factory=list)


class UnitsConceptBatchRaw(BaseModel):
    """Lenient wire shape — per-item strict validation, like unit metadata."""

    model_config = ConfigDict(extra="forbid")

    mappings: list[dict[str, object]] = Field(default_factory=list)


# Kept for backwards compatibility with older call sites.
class UnitConceptBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concepts: list[ConceptProposal] = Field(default_factory=list)


def normalize_concept_name(name: str) -> str:
    """Canonical lookup form: variant/diacritic/ZWNJ-insensitive.

    Reuses the retrieval normalizer so 'fear of abandonment', 'Fear of
    Abandonment!', and orthographic variants of Persian names converge.
    """

    return " ".join(normalize_search_text(_PUNCT.sub(" ", name)).split())


def normalize_role(role: str) -> str:
    value = role.strip().upper()
    value = _ROLE_ALIASES.get(value, value)
    return value if value in CONCEPT_ROLES else "CONTEXT"


def validate_concept_proposal(proposal: ConceptProposal) -> str | None:
    """Return a rejection reason, or ``None`` when the proposal is usable."""

    normalized = normalize_concept_name(proposal.canonical_name)
    if not normalized:
        return "empty"
    if len(normalized.split()) > _MAX_CONCEPT_WORDS:
        return "sentence_length"
    if normalized in _NOISE_CONCEPTS:
        return "noise"
    if proposal.confidence < _MIN_CONFIDENCE:
        return "low_confidence"
    return None


def _name_forms(name: str) -> set[str]:
    """Match forms covering both normalization conventions in the corpus."""

    return {
        form
        for form in (
            normalize_concept_name(name),
            normalize_external_text(name).casefold(),
        )
        if form
    }


async def resolve_concept(
    session: AsyncSession, canonical_name: str, labels: dict[str, str] | None = None
) -> ExternalConcept:
    """Find-or-create a shared concept: exact name → alias label → create."""

    forms = _name_forms(canonical_name)
    existing = await session.scalar(
        select(ExternalConcept).where(
            func.lower(ExternalConcept.normalized_name).in_(forms)
        )
    )
    if existing is not None:
        return existing
    # Alias reuse: a multilingual label already points at a concept.
    alias = await session.scalar(
        select(EntityLabel.concept_id)
        .where(
            EntityLabel.concept_id.is_not(None),
            func.lower(EntityLabel.normalized_label).in_(forms),
        )
        .limit(1)
    )
    if alias is not None:
        concept = await session.get(ExternalConcept, alias)
        if concept is not None:
            return concept
    concept = ExternalConcept(
        canonical_name=canonical_name.strip(),
        normalized_name=normalize_external_text(canonical_name).casefold(),
    )
    session.add(concept)
    await session.flush()
    await add_concept_label(
        session, concept.id, "und", canonical_name, LabelKind.CANONICAL
    )
    for language, label in (labels or {}).items():
        kind = LabelKind.ALIAS if language[:2] == "en" else LabelKind.TRANSLATION
        await add_concept_label(session, concept.id, language, label, kind)
    return concept


async def add_concept_label(
    session: AsyncSession,
    concept_id: UUID,
    language: str,
    label: str,
    kind: LabelKind = LabelKind.ALIAS,
) -> None:
    """Persist a multilingual alias; idempotent per (label, language, id)."""

    normalized = normalize_external_text(label).casefold()
    if not normalized or not language:
        return
    existing = await session.scalar(
        select(EntityLabel).where(
            EntityLabel.concept_id == concept_id,
            EntityLabel.normalized_label == normalized,
            EntityLabel.language == language[:16],
        )
    )
    if existing is None:
        session.add(
            EntityLabel(
                concept_id=concept_id,
                label=label.strip(),
                normalized_label=normalized,
                language=language[:16],
                kind=kind,
            )
        )
        await session.flush()


CONCEPT_PROMPT_VERSION = "unit_concept_mapping_v2"

CONCEPT_INSTRUCTIONS = """You map Knowledge Units to the reusable concepts \
they express.

For each unit return its unit_ref (echo the label) and 0-5 concepts. Each \
concept is a canonical, reusable semantic entity — a noun phrase like \
"attachment", "fear of abandonment", "testosterone", "tribal identity" — \
NEVER a sentence, question, or one-off phrasing.

Rules:
- Prefer established, general concept names in English; add a "labels" map \
with the source-language term when natural (e.g. {"fa": "..."}).
- relation_role: PRIMARY (the unit is mainly about it), SECONDARY \
(important but not central), CONTEXT (background), CONTRAST (the unit \
argues against or contrasts it).
- Confidence 0-1; omit concepts you are unsure about.
- Do not invent concepts absent from the text.
- Fewer precise concepts beat many vague ones; generic words like \
"people", "thing", "important" are useless — omit them.
""".strip()
