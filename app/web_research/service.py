"""Web research orchestration: search → fetch pages → ingest as sources."""

import contextlib
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from uuid import UUID

import httpx

from app.db.session import Database
from app.knowledge.file_import import FileImportError, import_web_resource
from app.ops.settings.service import StudioSettingsService
from app.web_research.classify import classify_web_page
from app.web_research.domain import IngestedWebSource, WebResearchReport
from app.web_research.models import WebResearchRun
from app.web_research.providers import (
    ResearchConfig,
    WebResearchError,
    build_provider,
)


class WebResearchDisabledError(WebResearchError):
    """Raised when research is triggered while the feature is off."""


class _TextExtractor(HTMLParser):
    """Minimal HTML→text: drop script/style/noscript, keep block breaks."""

    _SKIP = {"script", "style", "noscript", "svg", "canvas", "template"}
    _BLOCK = {
        "p",
        "div",
        "br",
        "li",
        "ul",
        "ol",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
        "blockquote",
        "tr",
        "table",
        "header",
        "footer",
        "main",
        "aside",
        "figure",
        "figcaption",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n\s*", "\n\n", text)
        return text.strip()


def html_to_text(html: str) -> str:
    """Extract readable text from an HTML document."""

    parser = _TextExtractor()
    with contextlib.suppress(Exception):
        # malformed HTML — keep whatever was collected
        parser.feed(html)
    return parser.text()


@dataclass
class GapResearchOutcome:
    report: WebResearchReport | None = None
    ingested: list[IngestedWebSource] = field(default_factory=list)
    error: str = ""

    @property
    def new_source_ids(self) -> list[UUID]:
        return [
            UUID(item.source_id)
            for item in self.ingested
            if item.source_id and item.status == "ingested"
        ]


class WebResearchService:
    """Search the web, fetch the discovered pages, ingest them as sources."""

    def __init__(
        self,
        database: Database,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        effective_overrides: dict[str, object] | None = None,
    ) -> None:
        self.database = database
        self.transport = transport
        self.effective_overrides = effective_overrides

    async def enabled(self) -> bool:
        return bool((await self._effective()).get("web_research_enabled"))

    async def research_and_ingest(
        self,
        query: str,
        *,
        context: str = "",
        channel_ids: tuple[UUID, ...] = (),
        language: str = "en",
        schedule: bool = True,
        content_brief_id: UUID | None = None,
        trigger: str = "manual",
        round_number: int | None = None,
        query_kind: str = "",
    ) -> GapResearchOutcome:
        """Run one research query and ingest the discovered pages.

        ``schedule=False`` leaves processing to the caller (e.g. when gap
        filling drives the pipeline inline) instead of the background queue.
        Every call is persisted as a ``WebResearchRun`` for provenance.
        """

        started = time.monotonic()
        outcome = GapResearchOutcome()
        effective = await self._effective()
        if not effective.get("web_research_enabled"):
            outcome.error = "web_research_disabled"
            await self._record_run(
                outcome,
                query,
                "",
                "",
                started,
                content_brief_id,
                trigger,
                round_number,
                query_kind,
            )
            return outcome
        config = ResearchConfig(effective)
        try:
            report = await build_provider(config, transport=self.transport).research(
                query, context
            )
        except WebResearchError as exc:
            outcome.error = str(exc)
            await self._record_run(
                outcome,
                query,
                config.provider,
                config.model,
                started,
                content_brief_id,
                trigger,
                round_number,
                query_kind,
            )
            return outcome
        outcome.report = report
        for finding in report.findings:
            outcome.ingested.append(
                await self._fetch_and_ingest(
                    config,
                    finding.url,
                    finding.title,
                    report,
                    channel_ids=channel_ids,
                    language=language,
                    schedule=schedule,
                )
            )
        await self._record_run(
            outcome,
            query,
            config.provider,
            config.model,
            started,
            content_brief_id,
            trigger,
            round_number,
            query_kind,
        )
        return outcome

    async def _record_run(
        self,
        outcome: GapResearchOutcome,
        query: str,
        provider: str,
        model: str,
        started: float,
        content_brief_id: UUID | None,
        trigger: str,
        round_number: int | None = None,
        query_kind: str = "",
    ) -> None:
        """Persist one auditable row per research call."""

        report = outcome.report
        rejected = [
            {"url": item.url, "status": item.status, "reason": item.detail}
            for item in outcome.ingested
            if item.status != "ingested"
        ]
        run = WebResearchRun(
            content_brief_id=content_brief_id,
            trigger=trigger,
            query=query,
            provider=provider,
            model=model,
            status="ERROR" if outcome.error else "OK",
            error=outcome.error[:2000],
            findings_count=len(report.findings) if report else 0,
            ingested_count=sum(
                1 for item in outcome.ingested if item.status == "ingested"
            ),
            new_source_ids=[str(sid) for sid in outcome.new_source_ids],
            result_json={
                "ingested": [item.model_dump() for item in outcome.ingested],
                "answer_chars": len(report.answer_text) if report else 0,
                "round_number": round_number,
                "query_kind": query_kind,
                "rejected": rejected,
                "rejected_count": len(rejected),
            },
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        async with self.database.transaction() as session:
            session.add(run)

    async def _fetch_and_ingest(
        self,
        config: ResearchConfig,
        url: str,
        title: str,
        report: WebResearchReport,
        *,
        channel_ids: tuple[UUID, ...],
        language: str,
        schedule: bool,
    ) -> IngestedWebSource:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(config.timeout_seconds),
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = await client.get(
                    url,
                    headers={
                        "Accept": "text/html,application/xhtml+xml",
                        # Wikimedia and many sites reject default UAs.
                        "User-Agent": "EmtedadApp/1.0 (research; httpx)",
                    },
                )
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "html" in content_type or not content_type:
                    text = html_to_text(
                        response.content[: config.max_page_bytes].decode(
                            response.encoding or "utf-8", errors="replace"
                        )
                    )
                elif "text/plain" in content_type:
                    text = response.content[: config.max_page_bytes].decode(
                        response.encoding or "utf-8", errors="replace"
                    )
                else:
                    return IngestedWebSource(
                        url=url,
                        status="failed",
                        detail=f"unsupported content type {content_type}",
                    )
        except httpx.HTTPError as exc:
            return IngestedWebSource(url=url, status="failed", detail=str(exc)[:200])
        if len(text) < 200:
            return IngestedWebSource(
                url=url, status="failed", detail="page has no readable text"
            )
        assessment = classify_web_page(url, title, text)
        try:
            source_id, created = await import_web_resource(
                self.database,
                url=url,
                title=title,
                text=text,
                provider=report.provider,
                query=report.query,
                answer_text=report.answer_text,
                channel_ids=channel_ids,
                language=language,
                schedule=schedule,
                publication_type=assessment.publication_type,
                retrieval_weight=assessment.retrieval_weight,
                quality_notes=assessment.review_notes,
            )
        except FileImportError as exc:
            return IngestedWebSource(url=url, status="failed", detail=str(exc)[:200])
        return IngestedWebSource(
            url=url,
            source_id=str(source_id),
            status="ingested" if created else "existing",
            publication_type=assessment.publication_type,
            retrieval_weight=assessment.retrieval_weight,
        )

    async def _effective(self) -> dict[str, object]:
        effective = await StudioSettingsService(self.database).effective()
        if self.effective_overrides:
            effective.update(self.effective_overrides)
        return effective
