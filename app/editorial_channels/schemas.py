"""Read-boundary schemas for editorial channels and their strategies."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.editorial_channels.domain import (
    ChannelResourceRole,
    EditorialChannelStatus,
    StrategyStatus,
)


class OrmRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EditorialChannelRead(OrmRead):
    id: UUID
    slug: str
    name: str
    description: str
    status: EditorialChannelStatus
    icon: str | None
    created_at: datetime


class ChannelStrategyRead(OrmRead):
    id: UUID
    editorial_channel_id: UUID
    version_number: int
    core_question: str
    audience_json: dict[str, object]
    audience_problems_json: dict[str, object]
    domains_json: dict[str, object]
    preferred_angles_json: dict[str, object]
    forbidden_angles_json: dict[str, object]
    source_policy_json: dict[str, object]
    evidence_policy_json: dict[str, object]
    topic_scoring_policy_json: dict[str, object]
    narrative_policy_json: dict[str, object]
    style_policy_json: dict[str, object]
    hook_policy_json: dict[str, object]
    ending_policy_json: dict[str, object]
    agent_profile_json: dict[str, object]
    status: StrategyStatus
    created_at: datetime
    activated_at: datetime | None


class ChannelResourceRead(OrmRead):
    editorial_channel_id: UUID
    source_id: UUID
    relevance: float
    role: ChannelResourceRole
    assigned_at: datetime


class ChannelSummary(OrmRead):
    """Channel card data for the Studio switcher; counts are real queries."""

    id: UUID
    slug: str
    name: str
    description: str
    status: EditorialChannelStatus
    resource_count: int
    topic_count: int
    active_production_count: int
    published_count: int
