"""Deterministic scoring: coverage + strategy-weighted total."""

from app.topics.domain import DEFAULT_COVERAGE_THRESHOLD, SCORE_KEYS
from app.topics.schemas import TopicCandidateProposal


def coverage_score(claimed: list[str], resolved: set[str]) -> float:
    """Share of the proposal's unit refs that resolve to real units."""

    if not claimed:
        return 0.0
    return round(len(set(claimed) & resolved) / len(set(claimed)), 4)


def total_score(scores: dict[str, float], weights: dict[str, object]) -> float:
    """Weighted mean; missing weights fall back to 1.0 per dimension."""

    total = 0.0
    weight_sum = 0.0
    for key in SCORE_KEYS:
        weight = weights.get(key, 1.0)
        try:
            weight_value = float(weight)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            weight_value = 1.0
        if weight_value <= 0:
            continue
        total += scores.get(key, 0.0) * weight_value
        weight_sum += weight_value
    return round(total / weight_sum, 4) if weight_sum else 0.0


def component_scores(
    proposal: TopicCandidateProposal,
    *,
    coverage: float,
    novelty: float,
) -> dict[str, float]:
    return {
        "channel_fit": proposal.channel_fit,
        "knowledge_coverage": coverage,
        "novelty": novelty,
        "curiosity": proposal.curiosity,
        "emotional_relevance": proposal.emotional_relevance,
        "practical_value": proposal.practical_value,
    }


def is_ready(coverage: float, threshold: float = DEFAULT_COVERAGE_THRESHOLD) -> bool:
    return coverage >= threshold
