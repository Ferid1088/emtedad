"""Publication targets per channel. Never auto-publishes."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PostgresSchema
from app.ops.assets.models import utc_now

CONTENT = PostgresSchema.CONTENT.value

PublicationTargetStatus = ENUM(
    "ACTIVE",
    "PAUSED",
    "RETIRED",
    name="publication_target_status",
    schema=CONTENT,
)


class PublicationTarget(Base):
    """A named, channel-scoped destination (YouTube channel, feed, ...).

    Scheduling and publishing stay manual: owner approval is required and
    this model performs no outbound calls.
    """

    __tablename__ = "publication_targets"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    editorial_channel_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.editorial_channels.id", ondelete="RESTRICT"),
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(64), default="youtube")
    language: Mapped[str] = mapped_column(String(16), default="fa")
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(PublicationTargetStatus, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
