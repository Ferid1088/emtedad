"""LLM call telemetry persistence.

``LLMCallEvent`` records provider-reported truth per call — tokens, cost,
latency, upstream provider — never estimates. APIMaster exposes no batch
API, so there is no batch-job persistence in this schema.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PostgresSchema
from app.ops.assets.models import utc_now

OPS = PostgresSchema.OPS.value


class LLMCallEvent(Base):
    """One provider call's observed telemetry — actuals only, or NULL."""

    __tablename__ = "llm_call_events"
    __table_args__ = ({"schema": OPS},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128), default="")
    upstream_provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    agent_role: Mapped[str] = mapped_column(String(64), default="")
    task: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(64), default="")
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    content_brief_id: Mapped[UUID | None] = mapped_column(nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    schema_repairs: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(default=False)
    error_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Protocol truth (§38): what the caller asked for vs what the
    # provider actually spoke — a Responses→Chat fallback is recorded,
    # never hidden.
    requested_protocol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actual_protocol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(default=False)
    fallback_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # "production" for owner-visible work, "dry_run"/"canary" for isolated
    # benchmark namespaces — telemetry rows are audit data, not content.
    run_scope: Mapped[str] = mapped_column(String(32), default="production")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
