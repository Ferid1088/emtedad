"""Deterministic quality flags and span metrics for Knowledge Units.

Soft signals only — they mark review-worthy granularity and retrieval
roles, never rewrite the unit's span or content. Atomic STORY/CASE_STUDY
units are exempt: their completeness is a hard architectural guarantee.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.retrieval.normalization import token_count

SUMMARY_ROLE = "SUMMARY"
DEFAULT_ROLE = "UNIT"


def unit_quality_flags(
    *,
    full_text: str,
    duration_seconds: float,
    atomic: bool,
    has_unit_children: bool,
) -> dict[str, object]:
    """Soft size warnings + summary role for oversized parent units.

    A non-atomic unit that is oversized AND whose structure children carry
    their own units is marked ``retrieval_role=SUMMARY``: it stays
    persisted for provenance and remains reachable as structural context,
    but retrieval demotes it so the more specific children win.
    """

    settings = get_settings()
    words = token_count(full_text)
    oversized = (
        duration_seconds > float(settings.unit_soft_max_duration_seconds)
        or words > settings.unit_soft_max_words
    )
    flags: dict[str, object] = {}
    if oversized:
        flags["size_warning"] = {
            "duration_seconds": round(duration_seconds, 1),
            "words": words,
        }
        if has_unit_children and not atomic:
            flags["retrieval_role"] = SUMMARY_ROLE
    return flags


def unit_retrieval_role(metadata: dict[str, object] | None) -> str:
    role = (metadata or {}).get("retrieval_role")
    return str(role) if role else DEFAULT_ROLE


def span_overlap_ratio(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Span overlap: intersection / smaller span (0..1).

    Works on any monotonic coordinates — segment sequences or seconds —
    as long as both spans share the same space.
    """

    a_start, a_end = a
    b_start, b_end = b
    intersection = min(a_end, b_end) - max(a_start, b_start) + 1
    if intersection <= 0:
        return 0.0
    smaller = min(a_end - a_start + 1, b_end - b_start + 1)
    return intersection / smaller if smaller > 0 else 0.0


@dataclass(frozen=True)
class ConceptLinkSample:
    """One persisted unit→concept link, rendered for precision review."""

    unit_id: UUID
    unit_type: str
    unit_title: str
    unit_summary: str
    concept_name: str
    relation_role: str
    confidence: float


async def sample_concept_links(
    session: AsyncSession,
    source_version_ids: Sequence[UUID],
    *,
    per_type: int = 9,
) -> list[ConceptLinkSample]:
    """Deterministically sample concept links across unit types.

    Ordered by (unit_type, unit id, concept id) and capped per type —
    no randomness, so precision evaluations are reproducible across
    runs and reviewers.
    """

    from app.knowledge.models import ExternalConcept
    from app.knowledge.units.models import KnowledgeUnit, KnowledgeUnitConcept

    rows = (
        await session.execute(
            select(
                KnowledgeUnit.id,
                KnowledgeUnit.unit_type,
                KnowledgeUnit.title,
                KnowledgeUnit.summary,
                ExternalConcept.canonical_name,
                KnowledgeUnitConcept.relation_role,
                KnowledgeUnitConcept.confidence,
                KnowledgeUnitConcept.concept_id,
            )
            .join(
                KnowledgeUnitConcept,
                KnowledgeUnitConcept.knowledge_unit_id == KnowledgeUnit.id,
            )
            .join(
                ExternalConcept,
                ExternalConcept.id == KnowledgeUnitConcept.concept_id,
            )
            .where(KnowledgeUnit.source_version_id.in_(source_version_ids))
            .order_by(
                KnowledgeUnit.unit_type,
                KnowledgeUnit.id,
                KnowledgeUnitConcept.concept_id,
            )
        )
    ).all()

    sampled: list[ConceptLinkSample] = []
    per_type_count: dict[str, int] = {}
    for row in rows:
        unit_type = str(row.unit_type)
        if per_type_count.get(unit_type, 0) >= per_type:
            continue
        per_type_count[unit_type] = per_type_count.get(unit_type, 0) + 1
        sampled.append(
            ConceptLinkSample(
                unit_id=row.id,
                unit_type=unit_type,
                unit_title=row.title,
                unit_summary=row.summary,
                concept_name=row.canonical_name,
                relation_role=row.relation_role,
                confidence=row.confidence,
            )
        )
    return sampled
