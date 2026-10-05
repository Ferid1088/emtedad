"""Persisted web-research runs.

Every research call — automatic gap fill or the manual owner action — leaves
one row here so the studio can show what was queried, which provider/model
answered, how long it took, and which sources were ingested. Without this
table the "Im Internet recherchieren" button was transient and unauditable.
"""

import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PostgresSchema


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


class WebResearchRun(Base):
    __tablename__ = "web_research_runs"
    __table_args__ = ({"schema": PostgresSchema.OPS.value},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    content_brief_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("content.content_briefs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    trigger: Mapped[str] = mapped_column(String(32), default="manual")
    query: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(32), default="OK")
    error: Mapped[str] = mapped_column(Text, default="")
    findings_count: Mapped[int] = mapped_column(Integer, default=0)
    ingested_count: Mapped[int] = mapped_column(Integer, default=0)
    new_source_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    result_json: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
