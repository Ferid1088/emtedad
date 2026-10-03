"""Typed states and seed definitions for editorial channels.

EditorialChannels are content verticals. They are deliberately separate from
``knowledge.Channel``, which models imported *source* channels such as YouTube
channels, and from ``PublicationTarget``, which models platform/language
targets for approved content.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class EditorialChannelStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class StrategyStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ChannelResourceRole(StrEnum):
    """Why a shared source matters to one editorial channel."""

    FOUNDATIONAL = "FOUNDATIONAL"
    PRIMARY = "PRIMARY"
    SUPPORTING = "SUPPORTING"
    REFERENCE = "REFERENCE"


@dataclass(frozen=True, slots=True)
class ChannelSeed:
    """Static definition of one editorial vertical and its first strategy."""

    slug: str
    name: str
    description: str
    core_question: str
    domains: tuple[str, ...]
    preferred_angles: tuple[str, ...]
    forbidden_angles: tuple[str, ...]
    special_roles: tuple[str, ...]
    policy_overrides: dict[str, object] = field(default_factory=dict)


EDITORIAL_CHANNEL_SEEDS: tuple[ChannelSeed, ...] = (
    ChannelSeed(
        slug="emtedad",
        name="Emtedad",
        description=(
            "Human patterns, continuity, relationships, identity, awareness, "
            "meaning, change, and the philosophy of lived experience."
        ),
        core_question="What pattern of lived experience does this reveal?",
        domains=(
            "human patterns",
            "continuity",
            "relationships",
            "identity",
            "awareness",
            "meaning",
            "change",
            "philosophy of lived experience",
        ),
        preferred_angles=(
            "lived-experience pattern",
            "continuity through change",
            "meaning and interpretation",
        ),
        forbidden_angles=("clinical diagnosis", "productivity hacking"),
        special_roles=(
            "HumanProblemAgent",
            "PatternAgent",
            "PhilosophyAgent",
            "CounterargumentAgent",
            "MeaningAgent",
            "EmtedadBoundaryReviewer",
        ),
        policy_overrides={
            "review_checks": (
                "conceptual continuity",
                "meaning/interpretation boundary",
                "Ayin source fidelity when Ayin is explicitly used",
            ),
        },
    ),
    ChannelSeed(
        slug="science-mystery",
        name="Science & Mystery",
        description=(
            "Cosmology, consciousness, time, origin, reality, information, "
            "physics, mathematics, origin of life, and the science/philosophy "
            "boundary."
        ),
        core_question="What is actually known, and what remains open?",
        domains=(
            "cosmology",
            "consciousness",
            "time",
            "origin",
            "reality",
            "information",
            "physics",
            "mathematics",
            "origin of life",
            "science/philosophy boundary",
        ),
        preferred_angles=(
            "open question with real evidence",
            "boundary between established science and interpretation",
        ),
        forbidden_angles=("philosophy presented as science", "pseudo-physics"),
        special_roles=(
            "ScientificEvidenceAgent",
            "EpistemicStatusAgent",
            "AlternativeExplanationAgent",
            "PhilosophyBridgeAgent",
            "OverclaimGate",
        ),
        policy_overrides={
            "epistemic_statuses": (
                "ESTABLISHED_SCIENCE",
                "STRONG_EVIDENCE",
                "HYPOTHESIS",
                "OPEN_QUESTION",
                "SPECULATION",
                "PHILOSOPHICAL_INTERPRETATION",
            ),
            "review_checks": (
                "epistemic status check",
                "overclaim check",
                "alternative explanation check",
                "science/philosophy boundary check",
            ),
        },
    ),
    ChannelSeed(
        slug="history-human-stories",
        name="History & Human Stories",
        description=(
            "Historical events and human lives told with accurate timelines, "
            "causal care, context, and honest source-conflict handling."
        ),
        core_question="What actually happened, and what made it unfold this way?",
        domains=(
            "historical events",
            "biography",
            "causality",
            "historical context",
            "human conflict",
        ),
        preferred_angles=(
            "character-driven narrative",
            "turning point with contested causes",
        ),
        forbidden_angles=("anachronistic moralizing", "single-cause mythology"),
        special_roles=(
            "TimelineAgent",
            "CausalityAgent",
            "HistoricalContextAgent",
            "CharacterAgent",
            "ConflictAgent",
            "SourceConflictAgent",
            "HistoricalAccuracyAgent",
        ),
        policy_overrides={
            "review_checks": (
                "timeline consistency",
                "source conflict",
                "causal overclaim",
                "anachronism check",
            ),
        },
    ),
    ChannelSeed(
        slug="pop-psychology-relationships",
        name="Pop Psychology & Relationships",
        description=(
            "Relatable psychology and relationship questions answered with "
            "evidence-aware, practical, non-generalizing content."
        ),
        core_question="Why do people do this, and what actually helps?",
        domains=(
            "relationships",
            "everyday psychology",
            "communication",
            "emotions",
            "practical advice",
        ),
        preferred_angles=(
            "viral everyday question",
            "evidence-aware practical advice",
        ),
        forbidden_angles=(
            "unsupported gender generalizations",
            "pseudoscientific claims",
            "explicit sexual content",
        ),
        special_roles=(
            "ViralQuestionAgent",
            "PsychologyEvidenceAgent",
            "RelatabilityAgent",
            "PracticalAdviceAgent",
            "HookAgent",
            "EmotionalRelevanceAgent",
            "OvergeneralizationGate",
        ),
        policy_overrides={
            "content_rules": (
                "no unsupported gender generalizations",
                "no pseudoscientific claims",
                "sexual topics remain educational/non-explicit",
                "practical advice must be evidence-aware",
            ),
            "review_checks": (
                "evidence strength",
                "overgeneralization",
                "practical advice safety",
                "gender stereotype check",
            ),
        },
    ),
    ChannelSeed(
        slug="psychology-evolution",
        name="Psychology & Evolution",
        description=(
            "Evolutionary perspectives on human behavior that always weigh "
            "biology against culture, environment, development, and individual "
            "differences."
        ),
        core_question=(
            "Is this adaptation, culture, or mismatch — and how would we know?"
        ),
        domains=(
            "evolutionary psychology",
            "human behavior",
            "culture vs biology",
            "modern mismatch",
            "individual differences",
        ),
        preferred_angles=(
            "hypothesis with alternatives",
            "mismatch between evolved tendencies and modern life",
        ),
        forbidden_angles=(
            "adaptationist just-so stories",
            "biological determinism",
        ),
        special_roles=(
            "EvolutionHypothesisAgent",
            "EvidenceAgent",
            "AlternativeExplanationAgent",
            "CultureVsBiologyAgent",
            "ModernMismatchAgent",
            "OvergeneralizationGate",
        ),
        policy_overrides={
            "always_consider": (
                "biology",
                "culture",
                "environment",
                "development",
                "individual differences",
            ),
            "review_checks": (
                "adaptationism check",
                "culture/biology alternative",
                "individual-differences check",
            ),
        },
    ),
)

CHANNEL_SEED_BY_SLUG: dict[str, ChannelSeed] = {
    seed.slug: seed for seed in EDITORIAL_CHANNEL_SEEDS
}
