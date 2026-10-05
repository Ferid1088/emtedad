"""Owner-editable settings persisted in the database.

Runtime ``Settings`` are environment-level defaults; owner overrides stored
here win at read time so the owner can toggle features and rotate API keys
without redeploying. Values are JSON so each setting keeps its type.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PostgresSchema


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


class OwnerSetting(Base):
    __tablename__ = "owner_settings"
    __table_args__ = ({"schema": PostgresSchema.OPS.value},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(128), unique=True)
    value: Mapped[object] = mapped_column(JSONB)
    updated_by: Mapped[str] = mapped_column(String(255), default="owner")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
