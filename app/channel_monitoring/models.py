"""Typed persistence for monitored channels and discovered videos."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from app.channel_monitoring.domain import CandidateStatus
from app.db.base import Base, PostgresSchema
from app.ops.assets.models import utc_now

KNOWLEDGE = PostgresSchema.KNOWLEDGE.value


def _enum(enum_type: type[object], name: str) -> ENUM:
    return ENUM(
        enum_type,
        name=name,
        schema=KNOWLEDGE,
        values_callable=lambda members: [member.value for member in members],
    )


class MonitoredChannel(Base):
    __tablename__ = "monitored_channels"
    __table_args__ = (
        UniqueConstraint("platform", "external_channel_id"),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    platform: Mapped[str] = mapped_column(String(32), default="YOUTUBE")
    external_channel_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(512))
    channel_url: Mapped[str] = mapped_column(Text)
    handle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_successful_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ChannelVideoCandidate(Base):
    __tablename__ = "channel_video_candidates"
    __table_args__ = (
        UniqueConstraint("channel_id", "youtube_video_id"),
        {"schema": KNOWLEDGE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    channel_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.monitored_channels.id", ondelete="CASCADE"), index=True
    )
    youtube_video_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(1024))
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    status: Mapped[CandidateStatus] = mapped_column(
        _enum(CandidateStatus, "channel_candidate_status"), default=CandidateStatus.NEW
    )
    imported_source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{KNOWLEDGE}.sources.id", ondelete="SET NULL"), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
