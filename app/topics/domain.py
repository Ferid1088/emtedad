"""Topic candidate vocabulary and scoring constants."""

from enum import StrEnum


class TopicStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    SHORTLISTED = "SHORTLISTED"
    SELECTED = "SELECTED"
    IN_RESEARCH = "IN_RESEARCH"
    READY_FOR_PRODUCTION = "READY_FOR_PRODUCTION"
    IN_PRODUCTION = "IN_PRODUCTION"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"
    NEEDS_RESEARCH = "NEEDS_RESEARCH"


SCORE_KEYS = (
    "channel_fit",
    "knowledge_coverage",
    "novelty",
    "curiosity",
    "emotional_relevance",
    "practical_value",
)

DEFAULT_COVERAGE_THRESHOLD = 0.4

TOPIC_MINING_TASK = "topic_mining"
TOPIC_PROMPT_VERSION = "topic_mining_v1"
