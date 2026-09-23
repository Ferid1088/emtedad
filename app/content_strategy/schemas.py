from uuid import UUID

from pydantic import BaseModel, Field

from app.content_strategy.domain import LectureAngle, LifeDomain


class TopicCreate(BaseModel):
    stable_key: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=512)
    human_question: str = Field(min_length=1)
    primary_concept_key: str = Field(min_length=1, max_length=255)
    life_domain: LifeDomain
    lecture_angle: LectureAngle


class LectureStrategyLinkCreate(BaseModel):
    lecture_master_version_id: UUID
    series_key: str = Field(min_length=1, max_length=255)
    series_title: str = Field(min_length=1, max_length=512)
    pathway_key: str | None = None
    pathway_title: str | None = None
    topic: TopicCreate
    ordinal: int = Field(ge=1)
