"""Closed vocabularies for content planning and publication packages."""

from enum import StrEnum


class ContentStatus(StrEnum):
    PLANNED = "PLANNED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY = "READY"
    ARCHIVED = "ARCHIVED"


class TopicOrigin(StrEnum):
    """How an owner topic entered the content strategy graph."""

    AI_SUGGESTED = "AI_SUGGESTED"
    USER_CREATED = "USER_CREATED"
    LEGACY = "LEGACY"


class TopicWorkspaceStatus(StrEnum):
    NEW = "NEW"
    LATER = "LATER"
    IN_PROGRESS = "IN_PROGRESS"
    ARCHIVED = "ARCHIVED"
    COMPLETED = "COMPLETED"


class LifeDomain(StrEnum):
    SELF = "self"
    FAMILY = "family"
    RELATIONSHIPS = "relationships"
    PARENTING = "parenting"
    WORK = "work"
    MIGRATION = "migration"
    SUFFERING = "suffering"
    GRIEF = "grief"
    SOCIETY = "society"
    TECHNOLOGY = "technology"
    AI = "AI"
    CREATIVITY = "creativity"
    DEATH = "death"
    COMMUNITY = "community"


class LectureAngle(StrEnum):
    FOUNDATION = "foundation"
    DISTINCTION = "distinction"
    HUMAN_QUESTION = "human_question"
    APPLICATION = "application"
    DIALOGUE = "dialogue"
    CRITIQUE = "critique"
    OPEN_QUESTION = "open_question"
    REFERENCE_DEEP_DIVE = "reference_deep_dive"


class TopicRelationType(StrEnum):
    PRECEDES = "PRECEDES"
    FOLLOWS = "FOLLOWS"
    RELATED = "RELATED"
    DEEPENS = "DEEPENS"
    CONTRASTS = "CONTRASTS"


class RepetitionDecision(StrEnum):
    ALLOW_DEEPENING = "ALLOW_DEEPENING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCK_DUPLICATE = "BLOCK_DUPLICATE"


class PublicationPackageStatus(StrEnum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"
