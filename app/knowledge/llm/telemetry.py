"""Telemetry recorder that persists provider-reported call truth.

Events carry only what the provider actually returned: token counts,
cached tokens, reasoning tokens, and the provider's own cost field. When
the provider omits cost the row stores NULL — estimates are never
persisted as actuals.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.db.session import Database
from app.knowledge.llm.apimaster import CallTelemetry
from app.knowledge.llm.models import LLMCallEvent

log = logging.getLogger(__name__)


class DatabaseLLMRecorder:
    """Persist each call event in its own short transaction.

    Telemetry must never break the production call it describes — a
    recorder failure is logged and swallowed by design (the alternative
    is observability code failing owner-facing work).
    """

    def __init__(
        self,
        database: Database,
        *,
        run_scope: str = "production",
        content_brief_id: UUID | None = None,
        language: str | None = None,
    ) -> None:
        self.database = database
        self.run_scope = run_scope
        self.content_brief_id = content_brief_id
        self.language = language

    async def record(self, event: CallTelemetry) -> None:
        try:
            async with self.database.transaction() as session:
                session.add(
                    LLMCallEvent(
                        provider=event.provider,
                        model=event.model,
                        upstream_provider=event.upstream_provider,
                        agent_role=event.agent_role,
                        task=event.task,
                        prompt_version=event.prompt_version,
                        language=self.language,
                        content_brief_id=self.content_brief_id,
                        request_id=event.request_id,
                        prompt_tokens=event.prompt_tokens,
                        completion_tokens=event.completion_tokens,
                        cached_tokens=event.cached_tokens,
                        reasoning_tokens=event.reasoning_tokens,
                        cost_usd=event.cost_usd,
                        latency_ms=event.latency_ms,
                        retries=event.retries,
                        schema_repairs=event.schema_repairs,
                        ok=event.ok,
                        error_kind=event.error_kind,
                        requested_protocol=event.requested_protocol,
                        actual_protocol=event.actual_protocol,
                        fallback_used=event.fallback_used,
                        fallback_reason=event.fallback_reason,
                        run_scope=self.run_scope,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "llm_telemetry_record_failed",
                extra={"error": f"{type(exc).__name__}: {exc}"[:300]},
            )
