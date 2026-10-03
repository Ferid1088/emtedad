"""Typed persistence for editorial channels, strategies, and resource links."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PostgresSchema
from app.editorial_channels.domain import (
    ChannelResourceRole,
    EditorialChannelStatus,
    StrategyStatus,
)
from app.ops.assets.models import utc_now

CONTENT = PostgresSchema.CONTENT.value
KNOWLEDGE = PostgresSchema.KNOWLEDGE.value


def _enum(enum_type: type[object], name: str) -> ENUM:
    return ENUM(
        enum_type,
        name=name,
        schema=CONTENT,
        values_callable=lambda members: [member.value for member in members],
    )


class EditorialChannel(Base):
    """One editorial vertical; distinct from imported knowledge.Channel."""

    __tablename__ = "editorial_channels"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[EditorialChannelStatus] = mapped_column(
        _enum(EditorialChannelStatus, "editorial_channel_status"),
        default=EditorialChannelStatus.ACTIVE,
    )
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class ChannelStrategyVersion(Base):
    """Versioned editorial strategy; policies only, never predefined topics."""

    __tablename__ = "channel_strategy_versions"
    __table_args__ = (
        UniqueConstraint("editorial_channel_id", "version_number"),
        Index(
            "uq_channel_strategy_one_active",
            "editorial_channel_id",
            unique=True,
            postgresql_where=text(f"status = '{StrategyStatus.ACTIVE.value}'"),
        ),
        {"schema": CONTENT},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    editorial_channel_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.editorial_channels.id", ondelete="RESTRICT"),
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer)

    core_question: Mapped[str] = mapped_column(Text)

    audience_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    audience_problems_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict
    )

    domains_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    preferred_angles_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict
    )
    forbidden_angles_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict
    )

    source_policy_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    evidence_policy_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)

    topic_scoring_policy_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict
    )
    narrative_policy_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict
    )
    style_policy_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    hook_policy_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    ending_policy_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)

    agent_profile_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)

    status: Mapped[StrategyStatus] = mapped_column(
        _enum(StrategyStatus, "channel_strategy_status"),
        default=StrategyStatus.DRAFT,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class EditorialChannelResource(Base):
    """Assignment of one shared source to one editorial channel.

    The Source row itself is never duplicated; this typed link only records
    that a channel draws on it.
    """

    __tablename__ = "editorial_channel_resources"
    __table_args__ = {"schema": CONTENT}

    editorial_channel_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.editorial_channels.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.sources.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    relevance: Mapped[float] = mapped_column(Float, default=1.0)
    role: Mapped[ChannelResourceRole] = mapped_column(
        _enum(ChannelResourceRole, "channel_resource_role"),
        default=ChannelResourceRole.SUPPORTING,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
