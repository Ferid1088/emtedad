"""Studio shell routes: channel workspaces, resource library, production."""

import contextlib
import json
from pathlib import Path
from typing import Any, TypedDict, cast
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.datastructures import UploadFile

from app.briefs.models import ContentBrief
from app.briefs.service import BriefInput, BriefService
from app.channel_monitoring.domain import CandidateStatus
from app.channel_monitoring.models import (
    ChannelVideoCandidate,
    MonitoredChannel,
)
from app.channel_monitoring.service import ChannelDiscoveryService
from app.content_engine.domain import (
    DraftStatus,
    ProductionStage,
    ReviewRunStatus,
)
from app.content_engine.models import (
    ArgumentPlan,
    NarrativePlan,
    ReviewFinding,
    ReviewRun,
    ScriptDraft,
)
from app.content_engine.review import ScriptService
from app.content_engine.service import (
    ContentEngineService,
    GateBlockedError,
)
from app.content_engine.writing.books import BookReference, reference_usage
from app.core.config import get_settings
from app.core.exceptions import ApplicationError
from app.db.session import Database
from app.editorial_channels.domain import ChannelResourceRole, StrategyStatus
from app.editorial_channels.models import (
    ChannelStrategyVersion,
    EditorialChannel,
    EditorialChannelResource,
)
from app.editorial_channels.service import (
    EDITORIAL_LANGUAGES,
    SCORING_WEIGHT_KEYS,
    ChannelNotFoundError,
    EditorialChannelService,
    StrategyValidationError,
    compare_strategies,
)
from app.knowledge.domain import SourceType
from app.knowledge.file_import import FileImportError, import_file_resource
from app.knowledge.llm.capacity import get_capacity
from app.knowledge.llm.models import LLMCallEvent
from app.knowledge.models import (
    EntityLabel,
    ExternalConcept,
    Person,
    Source,
    SourceSegment,
    SourceVersion,
    Work,
)
from app.knowledge.structure.domain import (
    FailureClass,
    SourceProcessingStatus,
    classify_failure,
)
from app.knowledge.structure.models import SourceProcessingState, SourceStructureNode
from app.knowledge.structure.scheduler import get_scheduler
from app.knowledge.structure.service import SourceStructureService
from app.knowledge.units.domain import ClaimType, KnowledgeUnitType
from app.knowledge.units.mapping_service import ConceptMappingService
from app.knowledge.units.models import KnowledgeUnit, KnowledgeUnitConcept
from app.knowledge.units.quality import unit_retrieval_role
from app.knowledge.units.service import KnowledgeUnitService
from app.lecture.domain import (
    MasterOriginType,
    PublicationLanguage,
)
from app.lecture.generic_service import GenericMasterService
from app.lecture.models import (
    LectureClaim,
    LectureMasterVersion,
    LectureSection,
)
from app.localization.domain import LocalizationPipelineStage
from app.localization.models import (
    LocalizationPipelineRun,
    LocalizationSemanticPackage,
)
from app.localization.runner import NativeLocalizationRunner
from app.ops.settings.service import StudioSettingsService
from app.production.models import PublicationTarget
from app.production.service import ProductionService, ProductionState
from app.research.domain import ResearchPlanStatus
from app.research.epistemic import classify_epistemic
from app.research.generic import GenericResearchService
from app.research.models import (
    EvidenceMatrix,
    EvidenceMatrixItem,
    ResearchPackage,
    ResearchPlan,
    ResearchPlanQuestion,
)
from app.retrieval.unit_retrieval import (
    ExpansionMode,
    KnowledgeUnitSearchService,
)
from app.topics.distinctiveness import DistinctivenessPlanner
from app.topics.domain import TopicStatus
from app.topics.models import (
    ScriptSignature,
    TopicCandidate,
    TopicCandidateConcept,
)
from app.topics.service import TopicService
from app.web.jobs import jobs
from app.web.service import import_youtube_resource
from app.web_research.gap_fill import GapFillService
from app.web_research.models import WebResearchRun

router = APIRouter(tags=["studio"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


class ChannelContext(TypedDict):
    channel: EditorialChannel
    active_strategy: ChannelStrategyVersion | None
    strategies: list[ChannelStrategyVersion]
    resources: list[EditorialChannelResource]
    resource_count: int


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def _service(request: Request) -> EditorialChannelService:
    return EditorialChannelService(_database(request))


async def _render(request: Request, name: str, **context: object) -> HTMLResponse:
    context.setdefault("attention_count", await _attention_count(request))
    return templates.TemplateResponse(request=request, name=name, context=context)


async def _attention_count(request: Request) -> int:
    """Topbar badge: open candidates + sources needing attention."""

    database = _database(request)
    try:
        async with database.transaction() as session:
            new_videos = int(
                await session.scalar(
                    select(func.count(ChannelVideoCandidate.id)).where(
                        ChannelVideoCandidate.status == CandidateStatus.NEW
                    )
                )
                or 0
            )
            flagged = int(
                await session.scalar(
                    select(func.count(SourceProcessingState.source_id)).where(
                        SourceProcessingState.status.in_(
                            [
                                SourceProcessingStatus.STRUCTURE_REVIEW_REQUIRED,
                                SourceProcessingStatus.UNIT_REVIEW_REQUIRED,
                                SourceProcessingStatus.FAILED,
                            ]
                        )
                    )
                )
                or 0
            )
    except Exception:  # noqa: BLE001 - badge must never break a page render
        return 0
    return new_videos + flagged


def human_error(raw: str | None) -> str:
    """Map provider/internal error codes to owner-readable German text."""

    if not raw:
        return "Verarbeitung fehlgeschlagen."
    lowered = raw.lower()
    if "quota" in lowered or "rate_limit" in lowered or "429" in lowered:
        return (
            "Provider-Kapazität erreicht. Die Verarbeitung konnte nicht "
            "fortgesetzt werden; deine Ressource wurde gespeichert."
        )
    if "timeout" in lowered or "timed out" in lowered:
        return "Verarbeitung vorübergehend nicht möglich (Zeitüberschreitung)."
    if "channel not found" in lowered or "not found" in lowered:
        return "Nicht gefunden."
    if "unauthorized" in lowered or "forbidden" in lowered or "401" in lowered:
        return "Zugriff verweigert — bitte Anmeldedaten prüfen."
    return "Verarbeitung fehlgeschlagen — siehe technische Details."


templates.env.globals["human_error"] = human_error


async def _channel_context(request: Request, slug: str) -> ChannelContext | None:
    service = _service(request)
    try:
        channel = await service.get_channel(slug)
    except ChannelNotFoundError:
        return None
    resources = await service.list_channel_resources(channel.id)
    strategies = await service.list_strategies(channel.id)
    active = next((item for item in strategies if item.status.value == "ACTIVE"), None)
    return {
        "channel": channel,
        "active_strategy": active,
        "strategies": strategies,
        "resources": resources,
        "resource_count": len(resources),
    }


async def _brief_states(
    request: Request, channel_id: UUID | None = None, limit: int = 50
) -> list[ProductionState]:
    """Derived production state for each brief — one service call per brief."""

    database = _database(request)
    async with database.transaction() as session:
        statement = select(ContentBrief).order_by(ContentBrief.created_at.desc())
        if channel_id is not None:
            statement = statement.where(ContentBrief.editorial_channel_id == channel_id)
        brief_ids = list((await session.scalars(statement.limit(limit))).all())
    service = ProductionService(database)
    states: list[ProductionState] = []
    for brief_id in brief_ids:
        states.append(await service.state_for_brief(brief_id.id))
    return states


@router.get("/studio", response_class=HTMLResponse)
async def studio_home(request: Request) -> HTMLResponse:
    service = _service(request)
    summaries = await service.channel_summaries()
    if not summaries:
        # First access on a migrated database: run the idempotent seed.
        await service.seed_channels()
        summaries = await service.channel_summaries()
    async with _database(request).transaction() as session:
        source_count = int(await session.scalar(select(func.count(Source.id))) or 0)
        failed_sources = int(
            await session.scalar(
                select(func.count(SourceProcessingState.source_id)).where(
                    SourceProcessingState.status == SourceProcessingStatus.FAILED
                )
            )
            or 0
        )
        review_sources = int(
            await session.scalar(
                select(func.count(SourceProcessingState.source_id)).where(
                    SourceProcessingState.status.in_(
                        [
                            SourceProcessingStatus.STRUCTURE_REVIEW_REQUIRED,
                            SourceProcessingStatus.UNIT_REVIEW_REQUIRED,
                        ]
                    )
                )
            )
            or 0
        )
        attention_rows = (
            await session.execute(
                select(Source, SourceProcessingState)
                .join(
                    SourceProcessingState,
                    SourceProcessingState.source_id == Source.id,
                )
                .where(
                    SourceProcessingState.status.in_(
                        [
                            SourceProcessingStatus.STRUCTURE_REVIEW_REQUIRED,
                            SourceProcessingStatus.UNIT_REVIEW_REQUIRED,
                            SourceProcessingStatus.FAILED,
                        ]
                    )
                )
                .order_by(SourceProcessingState.updated_at.desc())
                .limit(5)
            )
        ).all()
        attention_items = [
            {
                "source": source,
                "status": state.status.value,
                "error": state.last_error,
            }
            for source, state in attention_rows
        ]
        new_candidates = list(
            await session.scalars(
                select(ChannelVideoCandidate)
                .where(ChannelVideoCandidate.status == CandidateStatus.NEW)
                .order_by(ChannelVideoCandidate.discovered_at.desc())
                .limit(6)
            )
        )
        candidate_channels = {
            channel_id: chan
            for channel_id, chan in (
                await session.execute(
                    select(MonitoredChannel.id, MonitoredChannel).where(
                        MonitoredChannel.id.in_([c.channel_id for c in new_candidates])
                    )
                )
            ).all()
        }
        monitored = list(
            await session.scalars(
                select(MonitoredChannel)
                .where(MonitoredChannel.active.is_(True))
                .order_by(MonitoredChannel.name)
                .limit(5)
            )
        )
        pending_counts = {
            cid: int(count)
            for cid, count in (
                await session.execute(
                    select(
                        ChannelVideoCandidate.channel_id,
                        func.count(ChannelVideoCandidate.id),
                    )
                    .where(ChannelVideoCandidate.status == CandidateStatus.NEW)
                    .group_by(ChannelVideoCandidate.channel_id)
                )
            ).all()
        }
        draft_strategies = int(
            await session.scalar(
                select(func.count(ChannelStrategyVersion.id)).where(
                    ChannelStrategyVersion.status == StrategyStatus.DRAFT
                )
            )
            or 0
        )
        topic_rows = (
            await session.execute(
                select(TopicCandidate.status, func.count(TopicCandidate.id)).group_by(
                    TopicCandidate.status
                )
            )
        ).all()
        topic_counts = {str(status): int(count) for status, count in topic_rows}
        recent_topics = list(
            await session.scalars(
                select(TopicCandidate)
                .order_by(TopicCandidate.created_at.desc())
                .limit(5)
            )
        )
        topic_channels = {
            channel_id: chan
            for channel_id, chan in (
                await session.execute(
                    select(EditorialChannel.id, EditorialChannel).where(
                        EditorialChannel.id.in_(
                            [t.editorial_channel_id for t in recent_topics]
                        )
                    )
                )
            ).all()
        }
        localization_total = int(
            await session.scalar(select(func.count(LocalizationPipelineRun.id))) or 0
        )
        localization_open = int(
            await session.scalar(
                select(func.count(LocalizationPipelineRun.id)).where(
                    LocalizationPipelineRun.stage
                    != LocalizationPipelineStage.READY_FOR_VOICE
                )
            )
            or 0
        )
        recent_signatures = list(
            await session.scalars(
                select(ScriptSignature)
                .order_by(ScriptSignature.created_at.desc())
                .limit(5)
            )
        )
    productions = await _brief_states(request, limit=6)
    blocked_productions = sum(1 for s in productions if s.open_blockers)
    return await _render(
        request,
        "studio/home.html",
        title="Dashboard",
        channels=summaries,
        source_count=source_count,
        productions=productions,
        production_count=len(productions),
        blocked_productions=blocked_productions,
        monitored=monitored,
        pending_counts=pending_counts,
        new_candidates=new_candidates,
        candidate_channels=candidate_channels,
        failed_sources=failed_sources,
        review_sources=review_sources,
        draft_strategies=draft_strategies,
        attention_items=attention_items,
        topic_counts=topic_counts,
        recent_topics=recent_topics,
        topic_channels=topic_channels,
        localization_total=localization_total,
        localization_open=localization_open,
        recent_signatures=recent_signatures,
    )


@router.get("/studio/channels", response_class=HTMLResponse)
async def studio_channels(request: Request) -> HTMLResponse:
    summaries = await _service(request).channel_summaries()
    return await _render(
        request, "studio/channels.html", title="Meine Kanäle", channels=summaries
    )


# ---------------------------------------------------------------------------
# YouTube source channels (external monitoring — distinct from editorial channels)
# ---------------------------------------------------------------------------


def _yt_service(request: Request) -> ChannelDiscoveryService:
    adapter = getattr(request.app.state, "channel_adapter", None)
    return ChannelDiscoveryService(_database(request), adapter=adapter)


async def _yt_context(request: Request) -> dict[str, Any]:
    """Monitored channels + pending counts + recent candidates."""

    database = _database(request)
    async with database.transaction() as session:
        channels = list(
            await session.scalars(
                select(MonitoredChannel).order_by(MonitoredChannel.name)
            )
        )
        pending_counts = {
            cid: int(count)
            for cid, count in (
                await session.execute(
                    select(
                        ChannelVideoCandidate.channel_id,
                        func.count(ChannelVideoCandidate.id),
                    )
                    .where(ChannelVideoCandidate.status == CandidateStatus.NEW)
                    .group_by(ChannelVideoCandidate.channel_id)
                )
            ).all()
        }
        imported_counts = {
            cid: int(count)
            for cid, count in (
                await session.execute(
                    select(
                        ChannelVideoCandidate.channel_id,
                        func.count(ChannelVideoCandidate.id),
                    )
                    .where(ChannelVideoCandidate.status == CandidateStatus.IMPORTED)
                    .group_by(ChannelVideoCandidate.channel_id)
                )
            ).all()
        }
        candidates = list(
            await session.scalars(
                select(ChannelVideoCandidate)
                .where(
                    ChannelVideoCandidate.status.in_(
                        [CandidateStatus.NEW, CandidateStatus.FAILED]
                    )
                )
                .order_by(ChannelVideoCandidate.discovered_at.desc())
                .limit(60)
            )
        )
    return {
        "yt_channels": channels,
        "pending_counts": pending_counts,
        "imported_counts": imported_counts,
        "candidates": candidates,
        "channel_map": {c.id: c for c in channels},
    }


@router.get("/studio/youtube", response_class=HTMLResponse)
async def studio_youtube(request: Request) -> HTMLResponse:
    return await _render(
        request,
        "studio/youtube.html",
        title="YouTube-Kanäle",
        notice=str(request.query_params.get("msg") or ""),
        error=str(request.query_params.get("error") or ""),
        **(await _yt_context(request)),
    )


@router.post("/studio/youtube")
async def studio_youtube_add(request: Request) -> Response:
    form = await request.form()
    locator = str(form.get("locator") or "").strip()
    if not locator:
        return RedirectResponse(
            "/studio/youtube?error=Bitte+eine+Kanal-URL+oder+ein+Handle+angeben.",
            status_code=303,
        )
    try:
        await _yt_service(request).register(locator)
    except ValueError as exc:
        return RedirectResponse(
            "/studio/youtube?error=" + str(exc).replace(" ", "+"), status_code=303
        )
    except Exception:  # noqa: BLE001 - owner must see a friendly error, not a trace
        return RedirectResponse(
            "/studio/youtube?error="
            + "Der+YouTube-Kanal+konnte+nicht+aufgel%C3%B6st+werden.",
            status_code=303,
        )
    return RedirectResponse(
        "/studio/youtube?msg=Kanal+hinzugef%C3%BCgt.", status_code=303
    )


@router.post("/studio/youtube/check-all")
async def studio_youtube_check_all(request: Request) -> Response:
    service = _yt_service(request)
    for channel in await service.active_channels():
        with contextlib.suppress(Exception):
            await service.discover(channel.id)
    return RedirectResponse(
        "/studio/youtube?msg=Alle+Kan%C3%A4le+gepr%C3%BCft.", status_code=303
    )


@router.post("/studio/youtube/{channel_id}/check")
async def studio_youtube_check(request: Request, channel_id: UUID) -> Response:
    try:
        await _yt_service(request).discover(channel_id)
    except ValueError:
        return HTMLResponse("Kanal nicht gefunden", status_code=404)
    except Exception:  # noqa: BLE001
        return RedirectResponse(
            f"/studio/youtube/{channel_id}?error="
            "Die+Pr%C3%BCfung+ist+fehlgeschlagen.+Bitte+sp%C3%A4ter+erneut+versuchen.",
            status_code=303,
        )
    return RedirectResponse(
        f"/studio/youtube/{channel_id}?msg=Neue+Videos+gepr%C3%BCft.",
        status_code=303,
    )


@router.post("/studio/youtube/{channel_id}/delete")
async def studio_youtube_delete(request: Request, channel_id: UUID) -> Response:
    with contextlib.suppress(ValueError):
        await _yt_service(request).delete_channel(channel_id)
    return RedirectResponse(
        "/studio/youtube?msg=Kanal+entfernt.+Importierte+Ressourcen+bleiben+erhalten.",
        status_code=303,
    )


@router.get("/studio/youtube/{channel_id}", response_class=HTMLResponse)
async def studio_youtube_detail(request: Request, channel_id: UUID) -> Response:
    service = _yt_service(request)
    database = _database(request)
    async with database.transaction() as session:
        channel = await session.get(MonitoredChannel, channel_id)
        if channel is None:
            return HTMLResponse("Kanal nicht gefunden", status_code=404)
        counts = {
            status: int(count)
            for status, count in (
                await session.execute(
                    select(
                        ChannelVideoCandidate.status,
                        func.count(ChannelVideoCandidate.id),
                    )
                    .where(ChannelVideoCandidate.channel_id == channel_id)
                    .group_by(ChannelVideoCandidate.status)
                )
            ).all()
        }
    candidates = await service.candidates(channel_id)
    return await _render(
        request,
        "studio/youtube_detail.html",
        title=channel.name,
        yt_channel=channel,
        candidates=candidates,
        counts=counts,
        notice=str(request.query_params.get("msg") or ""),
        error=str(request.query_params.get("error") or ""),
    )


@router.post("/studio/youtube/{channel_id}/import")
async def studio_youtube_import(request: Request, channel_id: UUID) -> Response:
    form = await request.form()
    candidate_ids: list[UUID] = []
    for raw in form.getlist("candidate_ids"):
        with contextlib.suppress(ValueError):
            candidate_ids.append(UUID(str(raw)))
    if not candidate_ids:
        return RedirectResponse(
            f"/studio/youtube/{channel_id}?error=Bitte+Videos+ausw%C3%A4hlen.",
            status_code=303,
        )
    results = await _yt_service(request).import_selected(channel_id, candidate_ids)
    imported = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)
    msg = f"{imported}+Video(s)+importiert."
    if failed:
        msg += f"+{failed}+fehlgeschlagen."
    return RedirectResponse(f"/studio/youtube/{channel_id}?msg={msg}", status_code=303)


@router.post("/studio/youtube/{channel_id}/candidates/{candidate_id}/ignore")
async def studio_youtube_ignore(
    request: Request, channel_id: UUID, candidate_id: UUID
) -> Response:
    await _yt_service(request).ignore(channel_id, candidate_id)
    return RedirectResponse(f"/studio/youtube/{channel_id}", status_code=303)


# ---------------------------------------------------------------------------
# Global topics
# ---------------------------------------------------------------------------


@router.get("/studio/topics", response_class=HTMLResponse)
async def studio_topics(request: Request) -> HTMLResponse:
    database = _database(request)
    query = str(request.query_params.get("q") or "").strip()
    channel_slug = str(request.query_params.get("channel") or "").strip()
    status_filter = str(request.query_params.get("status") or "").strip()
    async with database.transaction() as session:
        channels = list(
            await session.scalars(
                select(EditorialChannel).order_by(EditorialChannel.name)
            )
        )
        statement = (
            select(TopicCandidate)
            .order_by(TopicCandidate.total_score.desc())
            .limit(150)
        )
        if channel_slug:
            statement = statement.join(
                EditorialChannel,
                EditorialChannel.id == TopicCandidate.editorial_channel_id,
            ).where(EditorialChannel.slug == channel_slug)
        if status_filter:
            with contextlib.suppress(ValueError):
                statement = statement.where(
                    TopicCandidate.status == TopicStatus(status_filter)
                )
        if query:
            like = f"%{query}%"
            statement = statement.where(
                TopicCandidate.video_question.ilike(like)
                | TopicCandidate.title.ilike(like)
            )
        topics = list(await session.scalars(statement))
    channel_map = {c.id: c for c in channels}
    return await _render(
        request,
        "studio/topics.html",
        title="Themen",
        topics=topics,
        channels=channels,
        channel_map=channel_map,
        query=query,
        channel_slug=channel_slug,
        status_filter=status_filter,
        statuses=list(TopicStatus),
    )


@router.post("/studio/topics")
async def studio_topics_manual(request: Request) -> Response:
    form = await request.form()
    slug = str(form.get("channel_slug") or "").strip()
    question = str(form.get("video_question") or "").strip()
    context = await _channel_context(request, slug)
    strategy = (
        (context["active_strategy"] or context["strategies"][0])
        if context and context["strategies"]
        else None
    )
    if context is None or not question or strategy is None:
        return RedirectResponse(
            "/studio/topics?error=Bitte+Kanal+und+Video-Frage+angeben.",
            status_code=303,
        )
    await TopicService(_database(request)).create_manual(
        context["channel"].id,
        strategy.id,
        question=question,
        title=str(form.get("title") or ""),
        thesis=str(form.get("tentative_thesis") or ""),
        angle=str(form.get("angle") or ""),
    )
    return RedirectResponse(
        f"/studio/topics?msg=Thema+angelegt.&channel={slug}", status_code=303
    )


# ---------------------------------------------------------------------------
# Translations (localization projects over approved semantic masters)
# ---------------------------------------------------------------------------


@router.get("/studio/translations", response_class=HTMLResponse)
async def studio_translations(request: Request) -> HTMLResponse:
    """Every production with an approved Persian script and the status of
    its native translations. Translations are started in the workspace."""

    database = _database(request)
    async with database.transaction() as session:
        approved = list(
            await session.scalars(
                select(ScriptDraft)
                .where(
                    ScriptDraft.lineage == "primary",
                    ScriptDraft.status == DraftStatus.APPROVED,
                )
                .order_by(ScriptDraft.created_at.desc())
            )
        )
        brief_ids = list({draft.content_brief_id for draft in approved})
        briefs = (
            {
                brief.id: brief
                for brief in await session.scalars(
                    select(ContentBrief).where(ContentBrief.id.in_(brief_ids))
                )
            }
            if brief_ids
            else {}
        )
    rows = []
    seen: set[UUID] = set()
    for draft in approved:
        if draft.content_brief_id in seen or draft.content_brief_id not in briefs:
            continue
        seen.add(draft.content_brief_id)
        rows.append(
            {
                "brief": briefs[draft.content_brief_id],
                "draft": draft,
                "runs": await _localization_runs(database, draft.content_brief_id),
            }
        )
    return await _render(
        request,
        "studio/translations.html",
        title="Übersetzungen",
        rows=rows,
    )


@router.get("/studio/publishing", response_class=HTMLResponse)
async def studio_publishing(request: Request) -> HTMLResponse:
    database = _database(request)
    async with database.transaction() as session:
        ready_rows = (
            await session.execute(
                select(LocalizationPipelineRun, LocalizationSemanticPackage)
                .join(
                    LocalizationSemanticPackage,
                    LocalizationSemanticPackage.id
                    == LocalizationPipelineRun.semantic_package_id,
                )
                .where(
                    LocalizationPipelineRun.stage
                    == LocalizationPipelineStage.READY_FOR_VOICE
                )
                .order_by(LocalizationPipelineRun.updated_at.desc())
                .limit(200)
            )
        ).all()
        ready = [
            {"run": run, "brief_id": package.content_brief_id}
            for run, package in ready_rows
        ]
        brief_ids = {row["brief_id"] for row in ready}
        briefs = (
            {
                b.id: b
                for b in (
                    await session.scalars(
                        select(ContentBrief).where(ContentBrief.id.in_(brief_ids))
                    )
                ).all()
            }
            if brief_ids
            else {}
        )
        channel_ids = {b.editorial_channel_id for b in briefs.values()}
        channels = (
            {
                c.id: c
                for c in (
                    await session.scalars(
                        select(EditorialChannel).where(
                            EditorialChannel.id.in_(channel_ids)
                        )
                    )
                ).all()
            }
            if channel_ids
            else {}
        )
        targets = list(await session.scalars(select(PublicationTarget)))
    return await _render(
        request,
        "studio/publishing.html",
        title="Veröffentlichung",
        ready=ready,
        briefs=briefs,
        channels=channels,
        targets=targets,
    )


async def _source_stats(
    request: Request, source_ids: list[UUID]
) -> dict[UUID, dict[str, int | str | None]]:
    """Per-source unit/concept/state stats for list views — batched, no N+1."""

    database = _database(request)
    stats: dict[UUID, dict[str, int | str | None]] = {
        source_id: {"units": 0, "concepts": 0, "status": None, "error": None}
        for source_id in source_ids
    }
    if not source_ids:
        return stats
    async with database.transaction() as session:
        version_rows = (
            await session.execute(
                select(SourceVersion.source_id, SourceVersion.id)
                .where(SourceVersion.source_id.in_(source_ids))
                .order_by(SourceVersion.created_at.desc())
            )
        ).all()
        latest_version: dict[UUID, UUID] = {}
        for source_id, version_id in version_rows:
            latest_version.setdefault(source_id, version_id)
        version_ids = list(latest_version.values())
        unit_rows = (
            (
                await session.execute(
                    select(
                        KnowledgeUnit.source_version_id,
                        func.count(KnowledgeUnit.id),
                    )
                    .where(KnowledgeUnit.source_version_id.in_(version_ids))
                    .group_by(KnowledgeUnit.source_version_id)
                )
            ).all()
            if version_ids
            else []
        )
        unit_counts = {vid: int(count) for vid, count in unit_rows}
        concept_rows = (
            (
                await session.execute(
                    select(
                        KnowledgeUnit.source_version_id,
                        func.count(func.distinct(KnowledgeUnitConcept.concept_id)),
                    )
                    .join(
                        KnowledgeUnitConcept,
                        KnowledgeUnitConcept.knowledge_unit_id == KnowledgeUnit.id,
                    )
                    .where(KnowledgeUnit.source_version_id.in_(version_ids))
                    .group_by(KnowledgeUnit.source_version_id)
                )
            ).all()
            if version_ids
            else []
        )
        concept_counts = {vid: int(count) for vid, count in concept_rows}
        state_rows = (
            await session.scalars(
                select(SourceProcessingState).where(
                    SourceProcessingState.source_id.in_(source_ids)
                )
            )
        ).all()
    for source_id, version_id in latest_version.items():
        stats[source_id]["units"] = unit_counts.get(version_id, 0)
        stats[source_id]["concepts"] = concept_counts.get(version_id, 0)
    for state in state_rows:
        # A persisted FAILED on a quota/rate-limit error is not a dead
        # source: the scheduler retries it after backoff. Show the owner
        # the truth — "retrying" — not a permanent failure badge.
        if state.status is SourceProcessingStatus.FAILED and classify_failure(
            state.last_error
        ) in {FailureClass.QUOTA, FailureClass.RATE_LIMIT}:
            stats[state.source_id]["status"] = "RETRYING"
        else:
            stats[state.source_id]["status"] = state.status.value
        stats[state.source_id]["error"] = state.last_error
    return stats


@router.get("/studio/channels/{slug}", response_class=HTMLResponse)
async def channel_overview(request: Request, slug: str) -> Response:
    context = await _channel_context(request, slug)
    if context is None:
        return HTMLResponse("Channel not found", status_code=404)
    source_ids = [link.source_id for link in context["resources"]]
    async with _database(request).transaction() as session:
        sources = (
            list(
                await session.scalars(
                    select(Source)
                    .where(Source.id.in_(source_ids))
                    .order_by(Source.created_at.desc())
                )
            )
            if source_ids
            else []
        )
        status_rows = (
            await session.execute(
                select(TopicCandidate.status, func.count())
                .where(TopicCandidate.editorial_channel_id == context["channel"].id)
                .group_by(TopicCandidate.status)
            )
        ).all()
        topic_counts = {status.value: int(count) for status, count in status_rows}
    candidates = await TopicService(_database(request)).list_candidates(slug)
    productions = await _brief_states(request, context["channel"].id, limit=8)
    source_stats = await _source_stats(request, source_ids)
    return await _render(
        request,
        "studio/channel_overview.html",
        title=context["channel"].name,
        sources=sources,
        source_stats=source_stats,
        topic_counts=topic_counts,
        top_candidates=candidates[:5],
        productions=productions,
        **context,
    )


@router.get("/studio/channels/{slug}/strategy", response_class=HTMLResponse)
async def channel_strategy(request: Request, slug: str) -> Response:
    context = await _channel_context(request, slug)
    if context is None:
        return HTMLResponse("Channel not found", status_code=404)
    return await _render(
        request,
        "studio/channel_strategy.html",
        title=f"{context['channel'].name} — Strategy",
        **context,
    )


@router.post("/studio/channels/{slug}/strategy/draft")
async def channel_strategy_draft(request: Request, slug: str) -> Response:
    """Create a draft strategy version, cloning the active one by default."""

    service = _service(request)
    try:
        channel = await service.get_channel(slug)
    except ChannelNotFoundError:
        return HTMLResponse("Channel not found", status_code=404)
    form = await request.form()
    core_question = str(form.get("core_question") or "").strip() or None
    await service.create_strategy_draft(channel.id, core_question=core_question)
    return RedirectResponse(f"/studio/channels/{slug}/strategy", status_code=303)


@router.post("/studio/channels/{slug}/strategy/{version_id}/activate")
async def channel_strategy_activate(
    request: Request, slug: str, version_id: UUID
) -> Response:
    service = _service(request)
    try:
        channel = await service.get_channel(slug)
    except ChannelNotFoundError:
        return HTMLResponse("Channel not found", status_code=404)
    async with _database(request).transaction() as session:
        owner = await session.get(ChannelStrategyVersion, version_id)
    if owner is None or owner.editorial_channel_id != channel.id:
        return HTMLResponse("Strategy version not found", status_code=404)
    try:
        await service.activate_strategy(version_id)
    except ApplicationError:
        return RedirectResponse(
            f"/studio/channels/{slug}/strategy?error=invalid", status_code=303
        )
    return RedirectResponse(f"/studio/channels/{slug}/strategy", status_code=303)


async def _strategy_draft(
    request: Request, slug: str, version_id: UUID
) -> tuple[ChannelContext, ChannelStrategyVersion] | Response:
    """Load channel context + a strategy version scoped to that channel."""

    context = await _channel_context(request, slug)
    if context is None:
        return HTMLResponse("Channel not found", status_code=404)
    async with _database(request).transaction() as session:
        version = await session.get(ChannelStrategyVersion, version_id)
    if version is None or version.editorial_channel_id != context["channel"].id:
        return HTMLResponse("Strategy version not found", status_code=404)
    return context, version


def _lines(raw: object) -> list[str]:
    return [line.strip() for line in str(raw or "").splitlines() if line.strip()]


def _strategy_form(
    form: Any,
) -> tuple[str, str, dict[str, dict[str, object]], list[str]]:
    """Parse the structured strategy editor into service-callable payloads."""

    errors: list[str] = []
    core_question = str(form.get("core_question") or "").strip()
    editorial_language = str(form.get("editorial_language") or "fa").strip()
    if editorial_language not in EDITORIAL_LANGUAGES:
        errors.append(f"Editorial language '{editorial_language}' is not supported.")
    weights: dict[str, float] = {}
    for key in SCORING_WEIGHT_KEYS:
        raw = str(form.get(f"w_{key}") or "0").strip()
        try:
            weights[key] = float(raw)
        except ValueError:
            errors.append(f"Scoring weight '{key}' is not a number.")
    policies: dict[str, dict[str, object]] = {
        "audience_json": {
            "description": str(form.get("audience_description") or "").strip()
        },
        "audience_problems_json": {"problems": _lines(form.get("audience_problems"))},
        "domains_json": {"domains": _lines(form.get("domains"))},
        "preferred_angles_json": {"angles": _lines(form.get("preferred_angles"))},
        "forbidden_angles_json": {"angles": _lines(form.get("forbidden_angles"))},
        "source_policy_json": {
            "channel_assigned_resources_only": bool(form.get("sp_channel_only")),
            "shared_knowledge_base": bool(form.get("sp_shared_base")),
        },
        "evidence_policy_json": {
            "require_source_provenance": bool(form.get("ep_provenance")),
            "require_counterevidence_search": bool(form.get("ep_counter")),
        },
        "topic_scoring_policy_json": {"weights": weights},
        "agent_profile_json": {"special_roles": _lines(form.get("special_roles"))},
    }
    for key, field in (
        ("narrative_policy_json", "narrative_policy"),
        ("style_policy_json", "style_policy"),
        ("hook_policy_json", "hook_policy"),
        ("ending_policy_json", "ending_policy"),
    ):
        raw = str(form.get(field) or "").strip()
        if not raw:
            policies[key] = {}
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            errors.append(f"{field.replace('_', ' ').title()} is not valid JSON.")
            continue
        if not isinstance(parsed, dict):
            errors.append(f"{field.replace('_', ' ').title()} must be a JSON object.")
            continue
        policies[key] = parsed
    return core_question, editorial_language, policies, errors


@router.get("/studio/channels/{slug}/strategy/{version_id}/edit")
async def strategy_edit_form(request: Request, slug: str, version_id: UUID) -> Response:
    result = await _strategy_draft(request, slug, version_id)
    if isinstance(result, Response):
        return result
    context, version = result
    if version.status.value != "DRAFT":
        return RedirectResponse(
            f"/studio/channels/{slug}/strategy?error=immutable", status_code=303
        )
    return await _render(
        request,
        "studio/strategy_edit.html",
        title=f"{context['channel'].name} — Edit strategy v{version.version_number}",
        draft=version,
        languages=sorted(EDITORIAL_LANGUAGES),
        weight_keys=SCORING_WEIGHT_KEYS,
        errors=[],
        submitted=None,
        **context,
    )


@router.post("/studio/channels/{slug}/strategy/{version_id}/edit")
async def strategy_edit_save(request: Request, slug: str, version_id: UUID) -> Response:
    result = await _strategy_draft(request, slug, version_id)
    if isinstance(result, Response):
        return result
    context, version = result
    if version.status.value != "DRAFT":
        return RedirectResponse(
            f"/studio/channels/{slug}/strategy?error=immutable", status_code=303
        )
    form = await request.form()
    core_question, editorial_language, policies, form_errors = _strategy_form(form)
    errors = form_errors
    if not errors:
        try:
            await _service(request).update_strategy_draft(
                version_id,
                core_question=core_question,
                editorial_language=editorial_language,
                policies=policies,
            )
        except StrategyValidationError as exc:
            errors = exc.errors
        except ApplicationError as exc:
            errors = [exc.public_message]
    if errors:
        return await _render(
            request,
            "studio/strategy_edit.html",
            title=(
                f"{context['channel'].name} — Edit strategy v{version.version_number}"
            ),
            draft=version,
            languages=sorted(EDITORIAL_LANGUAGES),
            weight_keys=SCORING_WEIGHT_KEYS,
            errors=errors,
            submitted={
                "core_question": core_question,
                "editorial_language": editorial_language,
                "policies": policies,
            },
            **context,
        )
    return RedirectResponse(
        f"/studio/channels/{slug}/strategy/{version_id}/compare", status_code=303
    )


@router.get("/studio/channels/{slug}/strategy/{version_id}/compare")
async def strategy_compare(request: Request, slug: str, version_id: UUID) -> Response:
    result = await _strategy_draft(request, slug, version_id)
    if isinstance(result, Response):
        return result
    context, version = result
    active = context["active_strategy"]
    diffs = compare_strategies(
        active if active is not None and active.id != version.id else None,
        version,
    )
    return await _render(
        request,
        "studio/strategy_compare.html",
        title=f"{context['channel'].name} — Strategy v{version.version_number} diff",
        draft=version,
        active=active,
        diffs=diffs,
        changed_count=sum(1 for diff in diffs if diff["changed"]),
        **context,
    )


@router.get("/studio/channels/{slug}/resources", response_class=HTMLResponse)
async def channel_resources(request: Request, slug: str) -> Response:
    context = await _channel_context(request, slug)
    if context is None:
        return HTMLResponse("Channel not found", status_code=404)
    assigned_ids = {link.source_id for link in context["resources"]}
    async with _database(request).transaction() as session:
        sources = list(
            await session.scalars(select(Source).order_by(Source.created_at.desc()))
        )
    return await _render(
        request,
        "studio/channel_resources.html",
        title=f"{context['channel'].name} — Resources",
        assigned=[s for s in sources if s.id in assigned_ids],
        unassigned=[s for s in sources if s.id not in assigned_ids],
        roles=list(ChannelResourceRole),
        **context,
    )


@router.post("/studio/channels/{slug}/resources")
async def channel_assign_resource(request: Request, slug: str) -> Response:
    service = _service(request)
    try:
        channel = await service.get_channel(slug)
    except ChannelNotFoundError:
        return HTMLResponse("Channel not found", status_code=404)
    form = await request.form()
    try:
        source_id = UUID(str(form.get("source_id", "")))
        role = ChannelResourceRole(str(form.get("role", "SUPPORTING")))
    except ValueError:
        return RedirectResponse(f"/studio/channels/{slug}/resources", status_code=303)
    await service.assign_resource(channel.id, source_id, role=role)
    return RedirectResponse(f"/studio/channels/{slug}/resources", status_code=303)


@router.post("/studio/channels/{slug}/resources/{source_id}/unassign")
async def channel_unassign_resource(
    request: Request, slug: str, source_id: UUID
) -> Response:
    service = _service(request)
    try:
        channel = await service.get_channel(slug)
    except ChannelNotFoundError:
        return HTMLResponse("Channel not found", status_code=404)
    await service.unassign_resource(channel.id, source_id)
    return RedirectResponse(f"/studio/channels/{slug}/resources", status_code=303)


@router.get("/studio/channels/{slug}/topics", response_class=HTMLResponse)
async def channel_topics(
    request: Request, slug: str, status: str | None = None
) -> Response:
    context = await _channel_context(request, slug)
    if context is None:
        return HTMLResponse("Channel not found", status_code=404)
    status_filter: TopicStatus | None = None
    if status:
        with contextlib.suppress(ValueError):
            status_filter = TopicStatus(status)
    candidates = await TopicService(_database(request)).list_candidates(
        slug, status=status_filter
    )
    unit_count = {candidate.id: len(candidate.units) for candidate in candidates}
    concept_names: dict[UUID, list[str]] = {
        candidate.id: sorted(link.concept.canonical_name for link in candidate.concepts)
        for candidate in candidates
    }
    return await _render(
        request,
        "studio/channel_topics.html",
        title=f"{context['channel'].name} — Topics",
        candidates=candidates,
        unit_count=unit_count,
        concept_names=concept_names,
        statuses=list(TopicStatus),
        status_filter=status_filter,
        actionable_statuses=[
            TopicStatus.SHORTLISTED,
            TopicStatus.NEEDS_RESEARCH,
            TopicStatus.REJECTED,
            TopicStatus.ARCHIVED,
        ],
        **context,
    )


@router.get(
    "/studio/channels/{slug}/topics/{candidate_id}", response_class=HTMLResponse
)
async def channel_topic_detail(
    request: Request, slug: str, candidate_id: UUID
) -> Response:
    context = await _channel_context(request, slug)
    if context is None:
        return HTMLResponse("Channel not found", status_code=404)
    database = _database(request)
    async with database.transaction() as session:
        candidate = await session.scalar(
            select(TopicCandidate)
            .where(
                TopicCandidate.id == candidate_id,
                TopicCandidate.editorial_channel_id == context["channel"].id,
            )
            .options(
                selectinload(TopicCandidate.units),
                selectinload(TopicCandidate.concepts).selectinload(
                    TopicCandidateConcept.concept
                ),
            )
        )
        if candidate is None:
            return HTMLResponse("Topic not found", status_code=404)
        unit_ids = [link.knowledge_unit_id for link in candidate.units]
        units = (
            list(
                await session.scalars(
                    select(KnowledgeUnit).where(KnowledgeUnit.id.in_(unit_ids))
                )
            )
            if unit_ids
            else []
        )
        version_ids = {unit.source_version_id for unit in units}
        source_rows = (
            (
                await session.execute(
                    select(Source)
                    .join(SourceVersion, SourceVersion.source_id == Source.id)
                    .where(SourceVersion.id.in_(version_ids))
                )
            ).all()
            if version_ids
            else []
        )
        sources = list({source.id: source for (source,) in source_rows}.values())
        epistemic = {
            unit.id: classify_epistemic(
                unit_type=unit.unit_type,
                claim_type=unit.claim_type,
                evidence_level=unit.evidence_level,
            ).value
            for unit in units
        }
    verdict = None
    report = None
    if context["active_strategy"] is not None:
        verdict, report = await DistinctivenessPlanner(database).assess(
            candidate, context["active_strategy"]
        )
    return await _render(
        request,
        "studio/topic_detail.html",
        title=candidate.title,
        candidate=candidate,
        units=units,
        sources=sources,
        epistemic=epistemic,
        verdict=verdict,
        report=report,
        actionable_statuses=[
            TopicStatus.SHORTLISTED,
            TopicStatus.SELECTED,
            TopicStatus.NEEDS_RESEARCH,
            TopicStatus.REJECTED,
            TopicStatus.ARCHIVED,
        ],
        **context,
    )


@router.post("/studio/channels/{slug}/topics/manual")
async def channel_topic_manual(request: Request, slug: str) -> Response:
    context = await _channel_context(request, slug)
    if context is None:
        return HTMLResponse("Channel not found", status_code=404)
    form = await request.form()
    question = str(form.get("video_question") or "").strip()
    strategy = context["active_strategy"] or (
        context["strategies"][0] if context["strategies"] else None
    )
    if not question or strategy is None:
        return RedirectResponse(f"/studio/channels/{slug}/topics", status_code=303)
    await TopicService(_database(request)).create_manual(
        context["channel"].id,
        strategy.id,
        question=question,
        title=str(form.get("title") or ""),
        thesis=str(form.get("tentative_thesis") or ""),
        angle=str(form.get("angle") or ""),
    )
    return RedirectResponse(f"/studio/channels/{slug}/topics", status_code=303)


@router.post("/studio/channels/{slug}/topics/mine")
async def channel_topics_mine(request: Request, slug: str) -> Response:
    form = await request.form()
    instruction = str(form.get("instruction") or "").strip() or None
    try:
        candidates = await TopicService(_database(request)).mine(
            slug, owner_instruction=instruction
        )
    except (LookupError, ValueError):
        return RedirectResponse(f"/studio/channels/{slug}/topics", status_code=303)
    if not candidates:
        return RedirectResponse(f"/studio/channels/{slug}/resources", status_code=303)
    return RedirectResponse(f"/studio/channels/{slug}/topics", status_code=303)


@router.post("/studio/channels/{slug}/topics/{candidate_id}/status")
async def channel_topic_status(
    request: Request, slug: str, candidate_id: UUID
) -> Response:
    form = await request.form()
    try:
        status = TopicStatus(str(form.get("status") or ""))
    except ValueError:
        return RedirectResponse(f"/studio/channels/{slug}/topics", status_code=303)
    with contextlib.suppress(LookupError, ValueError):
        await TopicService(_database(request)).set_status(candidate_id, status)
    return RedirectResponse(f"/studio/channels/{slug}/topics", status_code=303)


@router.get("/studio/channels/{slug}/production", response_class=HTMLResponse)
async def channel_production(request: Request, slug: str) -> Response:
    context = await _channel_context(request, slug)
    if context is None:
        return HTMLResponse("Channel not found", status_code=404)
    productions = await _brief_states(request, context["channel"].id)
    active = [
        state for state in productions if state.stage is not ProductionStage.APPROVED
    ]
    approved = [
        state for state in productions if state.stage is ProductionStage.APPROVED
    ]
    return await _render(
        request,
        "studio/channel_production.html",
        title=f"{context['channel'].name} — Production",
        productions=active,
        approved=approved,
        **context,
    )


@router.get("/studio/channels/{slug}/published", response_class=HTMLResponse)
async def channel_published(request: Request, slug: str) -> Response:
    context = await _channel_context(request, slug)
    if context is None:
        return HTMLResponse("Channel not found", status_code=404)
    async with _database(request).transaction() as session:
        signatures = list(
            await session.scalars(
                select(ScriptSignature)
                .where(ScriptSignature.editorial_channel_id == context["channel"].id)
                .order_by(ScriptSignature.created_at.desc())
            )
        )
    targets = await ProductionService(_database(request)).list_targets(
        context["channel"].id
    )
    return await _render(
        request,
        "studio/channel_published.html",
        title=f"{context['channel'].name} — Published",
        signatures=signatures,
        targets=targets,
        **context,
    )


# Owner-facing stage tabs in pipeline order.  ProductionStage also contains
# LOCALIZATION/VOICE — post-approval lifecycle, shown inside the Approved tab.
_WORKSPACE_TABS: tuple[ProductionStage, ...] = (
    ProductionStage.BRIEF,
    ProductionStage.THESIS,
    ProductionStage.RESEARCH,
    ProductionStage.EVIDENCE,
    ProductionStage.ARGUMENT,
    ProductionStage.NARRATIVE,
    ProductionStage.MASTER,
    ProductionStage.SCRIPT,
    ProductionStage.REVIEW,
    ProductionStage.APPROVED,
)


_UNCERTAIN_EPISTEMIC = {
    "UNKNOWN",
    "LIMITED_EVIDENCE",
    "HYPOTHESIS",
    "SPECULATION",
    "CONTESTED",
    "OPEN_QUESTION",
    "ANECDOTAL",
}


def _stage_index(stage: ProductionStage) -> int:
    if stage in _WORKSPACE_TABS:
        return _WORKSPACE_TABS.index(stage)
    # Post-approval stages map onto the last tab.
    return len(_WORKSPACE_TABS) - 1


async def _production_detail(request: Request, brief_id: UUID) -> dict[str, Any] | None:
    """Load every persisted artifact for one brief — batched, one session."""

    database = _database(request)
    try:
        state = await ProductionService(database).state_for_brief(brief_id)
    except LookupError:
        return None
    async with database.transaction() as session:
        channel = await session.get(EditorialChannel, state.brief.editorial_channel_id)
        strategy = await session.get(
            ChannelStrategyVersion, state.brief.strategy_version_id
        )
        plans = list(
            await session.scalars(
                select(ResearchPlan)
                .where(ResearchPlan.content_brief_id == brief_id)
                .order_by(ResearchPlan.version_number.desc())
            )
        )
        questions = (
            list(
                await session.scalars(
                    select(ResearchPlanQuestion)
                    .where(ResearchPlanQuestion.research_plan_id == plans[0].id)
                    .order_by(ResearchPlanQuestion.ordinal)
                )
            )
            if plans
            else []
        )
        package = await session.scalar(
            select(ResearchPackage)
            .where(ResearchPackage.content_brief_id == brief_id)
            .order_by(ResearchPackage.package_version.desc())
            .limit(1)
        )
        matrices = list(
            await session.scalars(
                select(EvidenceMatrix)
                .where(EvidenceMatrix.content_brief_id == brief_id)
                .order_by(EvidenceMatrix.version_number.desc())
            )
        )
        matrix_items = (
            list(
                await session.scalars(
                    select(EvidenceMatrixItem)
                    .where(EvidenceMatrixItem.evidence_matrix_id == matrices[0].id)
                    .order_by(EvidenceMatrixItem.ordinal)
                )
            )
            if matrices
            else []
        )
        argument = await session.scalar(
            select(ArgumentPlan)
            .where(ArgumentPlan.content_brief_id == brief_id)
            .options(selectinload(ArgumentPlan.sections))
            .order_by(ArgumentPlan.version_number.desc())
            .limit(1)
        )
        narrative = await session.scalar(
            select(NarrativePlan)
            .where(NarrativePlan.content_brief_id == brief_id)
            .options(selectinload(NarrativePlan.sections))
            .order_by(NarrativePlan.version_number.desc())
            .limit(1)
        )
        master = await session.scalar(
            select(LectureMasterVersion)
            .where(
                LectureMasterVersion.content_brief_id == brief_id,
                LectureMasterVersion.origin_type == MasterOriginType.CONTENT_BRIEF,
            )
            .order_by(LectureMasterVersion.version_number.desc())
            .limit(1)
        )
        master_sections = (
            list(
                await session.scalars(
                    select(LectureSection)
                    .where(LectureSection.lecture_master_version_id == master.id)
                    .order_by(LectureSection.ordinal)
                )
            )
            if master is not None
            else []
        )
        master_claims = (
            list(
                await session.scalars(
                    select(LectureClaim)
                    .where(LectureClaim.lecture_master_version_id == master.id)
                    .order_by(LectureClaim.sequence)
                )
            )
            if master is not None
            else []
        )
        # The workspace works on the Persian primary script. Localized
        # drafts (lineage="localized") have their own version numbers and
        # must never be shown or acted on as "the script".
        drafts = list(
            await session.scalars(
                select(ScriptDraft)
                .where(
                    ScriptDraft.content_brief_id == brief_id,
                    ScriptDraft.lineage == "primary",
                )
                .order_by(ScriptDraft.version_number.desc())
            )
        )
        latest_draft = drafts[0] if drafts else None
        approved_draft = next(
            (draft for draft in drafts if draft.status is DraftStatus.APPROVED),
            None,
        )
        findings = (
            list(
                await session.scalars(
                    select(ReviewFinding)
                    .where(ReviewFinding.script_draft_id == latest_draft.id)
                    .order_by(ReviewFinding.critic_role, ReviewFinding.created_at)
                )
            )
            if latest_draft is not None
            else []
        )
        review_runs = (
            list(
                await session.scalars(
                    select(ReviewRun)
                    .where(ReviewRun.script_draft_id == latest_draft.id)
                    .order_by(ReviewRun.round_number.desc())
                )
            )
            if latest_draft is not None
            else []
        )
        # The run that certifies the current text: COMPLETED for this exact
        # draft version + hash. Anything else is history.
        current_run = (
            next(
                (
                    run
                    for run in review_runs
                    if run.status is ReviewRunStatus.COMPLETED
                    and run.draft_version == latest_draft.version_number
                    and run.draft_hash == latest_draft.content_hash
                ),
                None,
            )
            if latest_draft is not None
            else None
        )
        review_stale = (
            latest_draft is not None
            and current_run is None
            and any(run.status is ReviewRunStatus.COMPLETED for run in review_runs)
        )
        current_run_findings = [
            f
            for f in findings
            if current_run is not None and f.review_run_id == current_run.id
        ]
        historical_findings = [
            f
            for f in findings
            if current_run is None or f.review_run_id != current_run.id
        ]
        signature = None
        if approved_draft is not None:
            signature = await session.scalar(
                select(ScriptSignature).where(
                    ScriptSignature.script_draft_id == approved_draft.id
                )
            )
        elif latest_draft is not None:
            signature = await session.scalar(
                select(ScriptSignature).where(
                    ScriptSignature.script_draft_id == latest_draft.id
                )
            )
        # Allow-listed book references frozen with the draft, plus whether
        # each one visibly surfaced in the script text — read-only, the
        # selection is never re-run for display.
        book_ref_rows: list[dict[str, object]] = []
        if latest_draft is not None:
            raw_refs = latest_draft.provenance_json.get("book_references", [])
            parsed_refs = (
                [
                    BookReference.model_validate(item)
                    for item in raw_refs
                    if isinstance(item, dict)
                ]
                if isinstance(raw_refs, list)
                else []
            )
            for ref, used in zip(
                parsed_refs,
                reference_usage(latest_draft.text, parsed_refs),
                strict=True,
            ):
                book_ref_rows.append({"ref": ref, "used": used})
        # Native-pipeline truth: every per-language run derives from the
        # shared semantic package anchored to this brief's approved
        # Persian draft — no separate progress bookkeeping.
        pipeline_runs = list(
            await session.scalars(
                select(LocalizationPipelineRun)
                .join(
                    LocalizationSemanticPackage,
                    LocalizationPipelineRun.semantic_package_id
                    == LocalizationSemanticPackage.id,
                )
                .where(LocalizationSemanticPackage.content_brief_id == brief_id)
                .order_by(LocalizationPipelineRun.updated_at.desc())
            )
        )
        cost_rows = (
            await session.execute(
                select(
                    LLMCallEvent.language,
                    func.count(LLMCallEvent.id),
                    func.count(LLMCallEvent.cost_usd),
                    func.sum(LLMCallEvent.cost_usd),
                    func.coalesce(func.sum(LLMCallEvent.prompt_tokens), 0),
                    func.coalesce(func.sum(LLMCallEvent.completion_tokens), 0),
                )
                .where(LLMCallEvent.content_brief_id == brief_id)
                .group_by(LLMCallEvent.language)
            )
        ).all()
        # Provider-reported cost only: NULLs stay unavailable — never
        # present a missing upstream price as "$0.00 actual".
        llm_costs = [
            {
                "language": language or "—",
                "calls": int(calls),
                "calls_with_cost": int(with_cost),
                "cost_usd": (round(float(cost), 6) if cost is not None else None),
                "tokens": int(tokens_in) + int(tokens_out),
            }
            for language, calls, with_cost, cost, tokens_in, tokens_out in cost_rows
        ]
        research_runs = list(
            await session.scalars(
                select(WebResearchRun)
                .where(WebResearchRun.content_brief_id == brief_id)
                .order_by(WebResearchRun.created_at.desc())
                .limit(20)
            )
        )
        # Resolve every referenced unit/item/section in batched lookups.
        unit_ids: set[UUID] = set()
        item_ids: set[UUID] = set()
        argument_section_ids: set[UUID] = set()
        for item in matrix_items:
            for collection in (
                item.supporting_unit_ids,
                item.counterevidence_unit_ids,
                item.alternative_unit_ids,
            ):
                unit_ids.update(UUID(str(raw)) for raw in collection if _is_uuid(raw))
        if argument is not None:
            for section in argument.sections:
                item_ids.update(
                    UUID(str(raw)) for raw in section.evidence_item_ids if _is_uuid(raw)
                )
                for collection in (
                    section.story_unit_ids,
                    section.counterargument_ids,
                    section.claim_ids,
                ):
                    unit_ids.update(
                        UUID(str(raw)) for raw in collection if _is_uuid(raw)
                    )
        if narrative is not None:
            for narr_section in narrative.sections:
                argument_section_ids.update(
                    UUID(str(raw))
                    for raw in narr_section.argument_section_ids
                    if _is_uuid(raw)
                )
                unit_ids.update(
                    UUID(str(raw))
                    for raw in narr_section.story_unit_ids
                    if _is_uuid(raw)
                )
        if package is not None:
            selected = package.retrieval_snapshot.get("selected_unit_ids", [])
            if isinstance(selected, list):
                for raw in selected:
                    if _is_uuid(raw):
                        unit_ids.add(UUID(str(raw)))
        units = (
            list(
                await session.scalars(
                    select(KnowledgeUnit).where(KnowledgeUnit.id.in_(unit_ids))
                )
            )
            if unit_ids
            else []
        )
        version_ids = {unit.source_version_id for unit in units}
        source_rows = (
            (
                await session.execute(
                    select(SourceVersion.id, Source.id, Source.title)
                    .join(Source, Source.id == SourceVersion.source_id)
                    .where(SourceVersion.id.in_(version_ids))
                )
            ).all()
            if version_ids
            else []
        )
        source_by_version = {
            version_id: (source_id, title)
            for version_id, source_id, title in source_rows
        }
    unit_map = {
        str(unit.id): {
            "title": unit.title,
            "type": unit.unit_type.value,
            "source_id": source_by_version.get(unit.source_version_id, (None, ""))[0],
            "source_title": source_by_version.get(unit.source_version_id, (None, ""))[
                1
            ],
        }
        for unit in units
    }
    item_map = {str(item.id): item for item in matrix_items}
    argument_section_map = (
        {str(section.id): section for section in argument.sections}
        if argument is not None
        else {}
    )
    # Version lookup for master's persisted upstream provenance.
    upstream_versions: dict[str, object] = {}
    if master is not None:
        upstream_versions = {
            "package": master.research_package_version,
            "package_hash": master.research_package_content_hash[:16],
            "matrix": next(
                (
                    m.version_number
                    for m in matrices
                    if m.id == master.evidence_matrix_id
                ),
                None,
            ),
            "argument": (
                argument.version_number
                if argument is not None and argument.id == master.argument_plan_id
                else None
            ),
            "narrative": (
                narrative.version_number
                if narrative is not None and narrative.id == master.narrative_plan_id
                else None
            ),
        }
    return {
        "state": state,
        "brief": state.brief,
        "channel_slug": channel.slug if channel is not None else "",
        "channel_name": channel.name if channel is not None else "",
        "strategy_version": strategy.version_number if strategy else None,
        "plan": plans[0] if plans else None,
        "questions": questions,
        "package": package,
        "matrix": matrices[0] if matrices else None,
        "matrix_items": matrix_items,
        "argument": argument,
        "narrative": narrative,
        "master": master,
        "master_sections": master_sections,
        "master_claims": master_claims,
        "upstream_versions": upstream_versions,
        "drafts": drafts,
        "latest_draft": latest_draft,
        "approved_draft": approved_draft,
        "book_ref_rows": book_ref_rows,
        "findings": findings,
        "review_runs": review_runs,
        "current_run": current_run,
        "review_stale": review_stale,
        "current_run_findings": current_run_findings,
        "historical_findings": historical_findings,
        "signature": signature,
        "pipeline_runs": pipeline_runs,
        "llm_costs": llm_costs,
        "research_runs": research_runs,
        "unit_map": unit_map,
        "item_map": item_map,
        "argument_section_map": argument_section_map,
    }


def _is_uuid(raw: object) -> bool:
    try:
        UUID(str(raw))
    except (ValueError, AttributeError):
        return False
    return True


def _page_by_seq(version: SourceVersion | None) -> dict[int, int]:
    """Page map from file-imported sources (sequence → 1-based page)."""

    if version is None:
        return {}
    raw_pages = version.provider_metadata.get("segment_pages")
    if not isinstance(raw_pages, dict):
        return {}
    return {
        int(seq): int(page)
        for seq, page in raw_pages.items()
        if str(seq).isdigit() and isinstance(page, int) and page > 0
    }


@router.get("/studio/production/{brief_id}", response_class=HTMLResponse)
async def brief_workspace(
    request: Request, brief_id: UUID, stage: str | None = None
) -> Response:
    detail = await _production_detail(request, brief_id)
    if detail is None:
        return HTMLResponse("Brief not found", status_code=404)
    state = detail["state"]
    active_stage: ProductionStage = state.stage
    if stage:
        with contextlib.suppress(ValueError):
            active_stage = ProductionStage(stage)
    database = _database(request)
    localization_runs = await _localization_runs(database, brief_id)
    gap = await GapFillService(database).assess(brief_id)
    effective = await StudioSettingsService(database).effective()
    return await _render(
        request,
        "studio/brief_workspace.html",
        title=f"Production — {state.brief.question[:60]}",
        tabs=_WORKSPACE_TABS,
        active_stage=active_stage,
        current_index=_stage_index(state.stage),
        uncertain_epistemic=_UNCERTAIN_EPISTEMIC,
        gap=gap,
        web_research_enabled=bool(effective.get("web_research_enabled")),
        duration_min=effective.get("target_duration_min_minutes"),
        duration_max=effective.get("target_duration_max_minutes"),
        research_notice=request.query_params.get("research"),
        error=request.query_params.get("error"),
        job=jobs.get(str(brief_id)),
        action_labels=_ACTION_LABELS,
        localization_runs=localization_runs,
        localized_texts=await _localized_texts(database, localization_runs),
        **detail,
    )


@router.post("/studio/production/{brief_id}/web-research")
async def production_web_research(request: Request, brief_id: UUID) -> Response:
    """Owner-triggered internet research for a brief with a material gap."""

    try:
        outcome = await GapFillService(_database(request)).fill_gap(
            brief_id, process_inline=True, trigger="manual"
        )
    except LookupError:
        return HTMLResponse("Brief not found", status_code=404)
    if outcome.ran:
        succeeded = sum(1 for item in outcome.ingested if item.status != "failed")
        notice = (
            f"Recherche abgeschlossen: {succeeded} Quelle(n) gefunden, "
            f"{outcome.linked_units} neue Knowledge Units verknüpft."
            + (f" Hinweis: {human_error(outcome.error)}" if outcome.error else "")
        )
    elif outcome.skipped_reason == "material_sufficient":
        notice = "Genug Material vorhanden — keine Recherche nötig."
    elif outcome.skipped_reason == "web_research_disabled":
        notice = (
            "Internet-Recherche ist deaktiviert. Aktiviere sie unter Einstellungen."
        )
    else:
        notice = "Recherche nicht gestartet."
    return RedirectResponse(
        f"/studio/production/{brief_id}?research={quote(notice)}", status_code=303
    )


async def _latest_draft_id(database: Database, brief_id: UUID) -> UUID | None:
    async with database.transaction() as session:
        result: UUID | None = await session.scalar(
            select(ScriptDraft.id)
            .where(
                ScriptDraft.content_brief_id == brief_id,
                ScriptDraft.lineage == "primary",
            )
            .order_by(ScriptDraft.version_number.desc())
            .limit(1)
        )
        return result


_ACTION_LABELS = {
    "plan_research": "Recherche planen",
    "build_evidence": "Evidence aufbauen",
    "freeze_research": "Recherche einfrieren",
    "build_argument": "Argument aufbauen",
    "build_narrative": "Narrativ aufbauen",
    "build_master": "Semantic Master erstellen",
    "build_script": "Persisches Skript erstellen",
    "run_review": "Review starten",
    "revise": "Entwurf überarbeiten",
    "approve": "Freigeben",
    "start_review_cycle": "Neuen Review-Zyklus starten",
    "localize": "Übersetzen",
}

_LOCALIZE_LANGUAGES = ("de", "en", "ar")


async def _localization_runs(
    database: Database, brief_id: UUID
) -> dict[str, LocalizationPipelineRun]:
    """Latest native localization run per language for this brief."""

    async with database.transaction() as session:
        rows = list(
            await session.scalars(
                select(LocalizationPipelineRun)
                .join(
                    LocalizationSemanticPackage,
                    LocalizationSemanticPackage.id
                    == LocalizationPipelineRun.semantic_package_id,
                )
                .where(LocalizationSemanticPackage.content_brief_id == brief_id)
                .order_by(LocalizationPipelineRun.updated_at.desc())
            )
        )
    latest: dict[str, LocalizationPipelineRun] = {}
    for run in rows:
        latest.setdefault(run.language.value, run)
    return latest


async def _localized_texts(
    database: Database, runs: dict[str, LocalizationPipelineRun]
) -> dict[str, str]:
    draft_ids = {
        language: run.script_draft_id
        for language, run in runs.items()
        if run.script_draft_id is not None
    }
    if not draft_ids:
        return {}
    async with database.transaction() as session:
        drafts = {
            draft.id: draft.text
            for draft in await session.scalars(
                select(ScriptDraft).where(ScriptDraft.id.in_(draft_ids.values()))
            )
        }
    return {
        language: drafts[draft_id]
        for language, draft_id in draft_ids.items()
        if draft_id in drafts
    }


async def _run_production_action(
    database: Database, brief_id: UUID, action: str, language: str
) -> None:
    if action == "plan_research":
        # When web research is enabled and the topic lacks material for
        # the target duration, fill the gap before planning.
        gap_fill = GapFillService(database)
        await gap_fill.fill_gap(brief_id, process_inline=True)
        if (await gap_fill.assess(brief_id)).units_available == 0:
            raise GateBlockedError(
                "Für dieses Thema gibt es kein Quellmaterial (keine Knowledge "
                "Units). Weise dem Kanal passende Quellen zu oder aktiviere die "
                "Internet-Recherche unter Settings."
            )
        await GenericResearchService(database).create_plan_for_brief(brief_id)
    elif action == "build_evidence":
        await GapFillService(database).fill_gap(brief_id, process_inline=True)
        await GenericResearchService(database).build_evidence_matrix(brief_id)
    elif action == "freeze_research":
        async with database.transaction() as session:
            plan_id = await session.scalar(
                select(ResearchPlan.id)
                .where(
                    ResearchPlan.content_brief_id == brief_id,
                    ResearchPlan.status == ResearchPlanStatus.READY,
                )
                .order_by(ResearchPlan.version_number.desc())
                .limit(1)
            )
        if plan_id is None:
            raise GateBlockedError("Kein fertiger Recherche-Plan zum Einfrieren")
        await GenericResearchService(database).freeze_package(plan_id)
    elif action == "build_argument":
        await ContentEngineService(database).build_argument(brief_id)
    elif action == "build_narrative":
        await ContentEngineService(database).build_narrative(brief_id)
    elif action == "build_master":
        await GenericMasterService(database).build_from_content_brief(brief_id)
    elif action == "build_script":
        await ScriptService(database).build_script(brief_id)
    elif action in {"run_review", "revise", "approve"}:
        draft_id = await _latest_draft_id(database, brief_id)
        if draft_id is None:
            raise GateBlockedError("Kein Skript-Entwurf vorhanden")
        if action == "run_review":
            await ScriptService(database).review_draft(draft_id)
        elif action == "revise":
            await ScriptService(database).revise_draft(draft_id)
        else:
            await ScriptService(database).approve_draft(draft_id, approved_by="owner")
    elif action == "start_review_cycle":
        await ScriptService(database).start_review_cycle(brief_id, started_by="owner")
    elif action == "localize":
        # The certified native pipeline: translates the owner-approved
        # Persian script, not the earlier Semantic Master.
        await NativeLocalizationRunner(database).run_language(
            brief_id, PublicationLanguage(language)
        )


@router.post("/studio/production/{brief_id}/actions/{action}")
async def production_action(request: Request, brief_id: UUID, action: str) -> Response:
    """Start one pipeline step in the background.

    The step must be allowed by the persisted state right now; the
    workspace shows its progress and any error in plain language.
    """

    if action not in _ACTION_LABELS:
        return HTMLResponse("Unknown action", status_code=404)
    database = _database(request)
    key = str(brief_id)
    back = f"/studio/production/{brief_id}"
    language = "de"
    if action == "localize":
        form = await request.form()
        language = str(form.get("language") or "de")
        if language not in _LOCALIZE_LANGUAGES:
            return RedirectResponse(
                f"{back}?error={quote('Unbekannte Zielsprache')}", status_code=303
            )
    try:
        state = await ProductionService(database).state_for_brief(brief_id)
    except LookupError:
        return HTMLResponse("Brief not found", status_code=404)
    if action not in state.allowed_actions:
        message = f"„{_ACTION_LABELS[action]}“ ist im aktuellen Zustand nicht möglich."
        return RedirectResponse(f"{back}?error={quote(message)}", status_code=303)
    label = _ACTION_LABELS[action]
    if action == "localize":
        label = f"{label} ({language.upper()})"
    started = jobs.start(
        key,
        action,
        label,
        lambda: _run_production_action(database, brief_id, action, language),
    )
    if not started:
        running = jobs.get(key)
        message = (
            f"Es läuft bereits: {running.label}" if running else "Es läuft bereits"
        )
        return RedirectResponse(f"{back}?error={quote(message)}", status_code=303)
    return RedirectResponse(back, status_code=303)


@router.post("/studio/production/{brief_id}/job/dismiss")
async def production_job_dismiss(brief_id: UUID) -> Response:
    jobs.clear(str(brief_id))
    return RedirectResponse(f"/studio/production/{brief_id}", status_code=303)


@router.post("/studio/production/{brief_id}/findings/{finding_id}/waive")
async def production_waive_finding(
    request: Request, brief_id: UUID, finding_id: UUID
) -> Response:
    """Owner override: waive one open review finding."""

    database = _database(request)
    try:
        async with database.transaction() as session:
            draft_brief = await session.scalar(
                select(ScriptDraft.content_brief_id)
                .join(
                    ReviewFinding,
                    ReviewFinding.script_draft_id == ScriptDraft.id,
                )
                .where(ReviewFinding.id == finding_id)
            )
        if draft_brief != brief_id:
            return HTMLResponse("Finding not found", status_code=404)
        form = await request.form()
        reason = str(form.get("reason") or "").strip()
        await ScriptService(database).waive_finding(
            finding_id, waived_by="owner", reason=reason
        )
    except (LookupError, ValueError) as exc:
        return RedirectResponse(
            f"/studio/production/{brief_id}?stage=REVIEW&error={quote(str(exc)[:300])}",
            status_code=303,
        )
    return RedirectResponse(
        f"/studio/production/{brief_id}?stage=REVIEW", status_code=303
    )


@router.post("/studio/topics/{candidate_id}/brief")
async def topic_create_brief(request: Request, candidate_id: UUID) -> Response:
    """Create a minimal ContentBrief from a candidate, then open its page."""

    database = _database(request)
    async with database.transaction() as session:
        candidate = await session.get(TopicCandidate, candidate_id)
    if candidate is None:
        return HTMLResponse("Candidate not found", status_code=404)
    effective = await StudioSettingsService(database).effective()
    target_minutes = _clamp_duration(
        float(effective.get("target_duration_default_minutes") or 27.5),
        float(effective.get("target_duration_min_minutes") or 25),
        float(effective.get("target_duration_max_minutes") or 30),
    )
    try:
        brief = await BriefService(database).create_for_candidate(
            candidate_id,
            BriefInput(
                question=candidate.video_question,
                thesis=candidate.tentative_thesis,
                target_duration_minutes=target_minutes,
                angle=candidate.angle,
            ),
        )
    except (LookupError, ValueError) as exc:
        return HTMLResponse(str(exc), status_code=400)
    return RedirectResponse(f"/studio/production/{brief.id}", status_code=303)


@router.get("/library", response_class=HTMLResponse)
async def resource_library(
    request: Request,
    q: str | None = None,
    source_type: str | None = None,
    status: str | None = None,
) -> HTMLResponse:
    service = _service(request)
    channels = await service.list_channels()
    async with _database(request).transaction() as session:
        statement = select(Source).order_by(Source.created_at.desc())
        if q:
            pattern = f"%{q.strip()}%"
            statement = statement.where(
                Source.title.ilike(pattern)
                | Source.canonical_url.ilike(pattern)
                | Source.external_id.ilike(pattern)
            )
        if source_type:
            with contextlib.suppress(ValueError):
                statement = statement.where(
                    Source.source_type == SourceType(source_type)
                )
        sources = list(await session.scalars(statement))
        state_rows = (
            list(
                await session.scalars(
                    select(SourceProcessingState).where(
                        SourceProcessingState.source_id.in_(
                            [source.id for source in sources]
                        )
                    )
                )
            )
            if sources
            else []
        )
        state_by_source = {row.source_id: row for row in state_rows}
        if status:
            sources = [
                source
                for source in sources
                if _status_matches(state_by_source.get(source.id), status)
            ]
        segment_counts = {
            source_id: int(count)
            for source_id, count in (
                await session.execute(
                    select(SourceVersion.source_id, func.count(SourceSegment.id))
                    .join(
                        SourceSegment,
                        SourceSegment.source_version_id == SourceVersion.id,
                    )
                    .group_by(SourceVersion.source_id)
                )
            ).all()
        }
        assignments: dict[UUID, list[str]] = {}
        slug_by_id = {channel.id: channel.slug for channel in channels}
        if sources and slug_by_id:
            rows = (
                await session.execute(
                    select(
                        EditorialChannelResource.source_id,
                        EditorialChannelResource.editorial_channel_id,
                    ).where(
                        EditorialChannelResource.source_id.in_(
                            [source.id for source in sources]
                        )
                    )
                )
            ).all()
            for source_id, channel_id in rows:
                assignments.setdefault(source_id, []).append(
                    slug_by_id.get(channel_id, str(channel_id))
                )
    source_stats = await _source_stats(request, [source.id for source in sources])
    settings = get_settings()
    exhausted_count = sum(
        1
        for state in state_by_source.values()
        if state.status is SourceProcessingStatus.FAILED
        and classify_failure(state.last_error) is FailureClass.FAILED
        and state.attempt_count >= settings.speech_structure_max_attempts
    )
    return await _render(
        request,
        "studio/resource_library.html",
        title="Resource Library",
        sources=sources,
        exhausted_count=exhausted_count,
        segment_counts=segment_counts,
        assignments=assignments,
        source_stats=source_stats,
        channels=channels,
        source_types=list(SourceType),
        status_options=[
            "READY",
            "PROCESSING",
            "REVIEW_REQUIRED",
            "FAILED",
        ],
        query=q or "",
        type_filter=source_type or "",
        status_filter=status or "",
        error=None,
    )


@router.post("/library/retry-failed")
async def library_retry_failed(request: Request) -> Response:
    """Owner action: re-enqueue every FAILED source, ignoring the retry cap."""
    enqueued = await get_scheduler(_database(request)).retry_failed()
    return RedirectResponse(f"/library?retried={enqueued}", status_code=303)


def _status_matches(state: SourceProcessingState | None, status: str) -> bool:
    """Bucket the persisted processing status into owner-facing filters."""

    if status == "READY":
        return state is not None and state.status is SourceProcessingStatus.READY
    if status == "PROCESSING":
        if state is None:
            return False
        if state.status in {
            SourceProcessingStatus.INGESTED,
            SourceProcessingStatus.STRUCTURE_PENDING,
            SourceProcessingStatus.STRUCTURING,
            SourceProcessingStatus.STRUCTURED,
            SourceProcessingStatus.UNIT_EXTRACTION_PENDING,
            SourceProcessingStatus.UNIT_EXTRACTING,
        }:
            return True
        # Quota/rate-limit failures are retried automatically — still in
        # flight from the owner's perspective.
        return state.status is SourceProcessingStatus.FAILED and (
            classify_failure(state.last_error)
            in {FailureClass.QUOTA, FailureClass.RATE_LIMIT}
        )
    if status == "REVIEW_REQUIRED":
        return state is not None and state.status in {
            SourceProcessingStatus.STRUCTURE_REVIEW_REQUIRED,
            SourceProcessingStatus.UNIT_REVIEW_REQUIRED,
        }
    if status == "FAILED":
        # Only genuine failures: quota/rate-limit failures are retried
        # automatically and belong to the PROCESSING bucket.
        return (
            state is not None
            and state.status is SourceProcessingStatus.FAILED
            and classify_failure(state.last_error) is FailureClass.FAILED
        )
    return True


@router.get("/library/import", response_class=HTMLResponse)
async def library_import_form(request: Request) -> HTMLResponse:
    channels = await _service(request).list_channels()
    return await _render(
        request,
        "studio/resource_import.html",
        title="Import Resource",
        channels=channels,
        errors=[],
    )


async def _assign_import_channels(
    request: Request, source_id: UUID, slugs: list[str]
) -> None:
    service = _service(request)
    for slug in slugs:
        with contextlib.suppress(ChannelNotFoundError):
            channel = await service.get_channel(slug)
            await service.assign_resource(channel.id, source_id)


@router.post("/library/import")
async def library_import(request: Request) -> Response:
    form = await request.form()
    resource_type = str(form.get("resource_type") or "youtube")
    slugs = [str(slug) for slug in form.getlist("channel_slugs") if str(slug).strip()]
    database = _database(request)
    if resource_type == "youtube":
        locator = str(form.get("url", "")).strip()
        try:
            source_id = await import_youtube_resource(database, locator)
        except Exception:
            return RedirectResponse("/library?import=failed", status_code=303)
    else:
        source_type = SourceType.PDF if resource_type == "pdf" else SourceType.BOOK
        upload = form.get("file")
        pasted = str(form.get("text") or "")
        data: bytes
        filename: str
        if isinstance(upload, UploadFile) and upload.filename:
            data = await upload.read()
            filename = upload.filename
        elif pasted.strip():
            data = pasted.encode()
            filename = "pasted-text.txt"
        else:
            return RedirectResponse("/library/import?error=missing", status_code=303)
        try:
            source_id = await import_file_resource(
                database,
                filename=filename,
                data=data,
                source_type=source_type,
                title=str(form.get("title") or "") or None,
                creator=str(form.get("creator") or "") or None,
                language=str(form.get("language") or "en"),
            )
        except FileImportError:
            return RedirectResponse("/library/import?error=invalid", status_code=303)
    await _assign_import_channels(request, source_id, slugs)
    return RedirectResponse(f"/library/{source_id}", status_code=303)


@router.post("/library/{source_id}/assign")
async def library_assign(request: Request, source_id: UUID) -> Response:
    form = await request.form()
    slug = str(form.get("channel_slug", ""))
    service = _service(request)
    try:
        channel = await service.get_channel(slug)
    except ChannelNotFoundError:
        return HTMLResponse("Channel not found", status_code=404)
    await service.assign_resource(channel.id, source_id)
    return RedirectResponse(f"/library/{source_id}", status_code=303)


@router.get("/library/{source_id}", response_class=HTMLResponse)
async def resource_detail(request: Request, source_id: UUID) -> Response:
    """Overview tab: metadata, channel use, artifact journey, actions."""

    service = _service(request)
    channels = await service.list_channels()
    async with _database(request).transaction() as session:
        source = await session.get(Source, source_id)
        if source is None:
            return HTMLResponse("Resource not found", status_code=404)
        versions = list(
            await session.scalars(
                select(SourceVersion)
                .where(SourceVersion.source_id == source_id)
                .order_by(SourceVersion.acquired_at.desc())
            )
        )
        latest_version = versions[0] if versions else None
        links = list(
            await session.scalars(
                select(EditorialChannelResource).where(
                    EditorialChannelResource.source_id == source_id
                )
            )
        )
        state = await session.get(SourceProcessingState, source_id)
        counts = {
            "segments": 0,
            "nodes": 0,
            "units": 0,
            "concepts": 0,
        }
        if latest_version is not None:
            counts["segments"] = int(
                await session.scalar(
                    select(func.count(SourceSegment.id)).where(
                        SourceSegment.source_version_id == latest_version.id
                    )
                )
                or 0
            )
            counts["nodes"] = int(
                await session.scalar(
                    select(func.count(SourceStructureNode.id)).where(
                        SourceStructureNode.source_version_id == latest_version.id
                    )
                )
                or 0
            )
            counts["units"] = int(
                await session.scalar(
                    select(func.count(KnowledgeUnit.id)).where(
                        KnowledgeUnit.source_version_id == latest_version.id
                    )
                )
                or 0
            )
            counts["concepts"] = int(
                await session.scalar(
                    select(func.count(func.distinct(KnowledgeUnitConcept.concept_id)))
                    .join(
                        KnowledgeUnit,
                        KnowledgeUnit.id == KnowledgeUnitConcept.knowledge_unit_id,
                    )
                    .where(KnowledgeUnit.source_version_id == latest_version.id)
                )
                or 0
            )
        review_warnings = 0
        if latest_version is not None:
            review_warnings = int(
                await session.scalar(
                    select(func.count(KnowledgeUnit.id)).where(
                        KnowledgeUnit.source_version_id == latest_version.id,
                        KnowledgeUnit.metadata_json["retrieval_role"].astext
                        == "SUMMARY",
                    )
                )
                or 0
            ) + int(
                await session.scalar(
                    select(func.count(KnowledgeUnit.id)).where(
                        KnowledgeUnit.source_version_id == latest_version.id,
                        KnowledgeUnit.claim_type == ClaimType.UNKNOWN,
                    )
                )
                or 0
            )
    slug_by_id = {channel.id: channel.slug for channel in channels}
    return await _render(
        request,
        "studio/resource_detail.html",
        title=source.title,
        source=source,
        versions=versions,
        counts=counts,
        state=state,
        review_warnings=review_warnings,
        channels=channels,
        assigned_slugs=[
            slug_by_id.get(link.editorial_channel_id, "?") for link in links
        ],
        active_tab="overview",
    )


@router.get("/library/{source_id}/original", response_class=HTMLResponse)
async def resource_original(request: Request, source_id: UUID) -> Response:
    async with _database(request).transaction() as session:
        source = await session.get(Source, source_id)
        if source is None:
            return HTMLResponse("Resource not found", status_code=404)
        version = await session.scalar(
            select(SourceVersion)
            .where(SourceVersion.source_id == source_id)
            .order_by(SourceVersion.created_at.desc())
            .limit(1)
        )
        segments = (
            list(
                await session.scalars(
                    select(SourceSegment)
                    .where(SourceSegment.source_version_id == version.id)
                    .order_by(SourceSegment.sequence)
                )
            )
            if version is not None
            else []
        )
        state = await session.get(SourceProcessingState, source_id)
    return await _render(
        request,
        "studio/resource_original.html",
        title=f"{source.title} — Original",
        source=source,
        version=version,
        segments=segments,
        state=state,
        page_by_seq=_page_by_seq(version),
        active_tab="original",
    )


@router.get("/library/{source_id}/concepts", response_class=HTMLResponse)
async def resource_concepts(request: Request, source_id: UUID) -> Response:
    """Concepts linked to this source's units, with reuse and confidence."""

    async with _database(request).transaction() as session:
        source = await session.get(Source, source_id)
        if source is None:
            return HTMLResponse("Resource not found", status_code=404)
        version = await session.scalar(
            select(SourceVersion)
            .where(SourceVersion.source_id == source_id)
            .order_by(SourceVersion.created_at.desc())
            .limit(1)
        )
        state = await session.get(SourceProcessingState, source_id)
        rows = (
            (
                await session.execute(
                    select(
                        ExternalConcept.id,
                        ExternalConcept.canonical_name,
                        ExternalConcept.description,
                        func.count(func.distinct(KnowledgeUnit.id)),
                        func.count(KnowledgeUnitConcept.id),
                        func.min(KnowledgeUnitConcept.confidence),
                        func.max(KnowledgeUnitConcept.confidence),
                    )
                    .join(
                        KnowledgeUnitConcept,
                        KnowledgeUnitConcept.concept_id == ExternalConcept.id,
                    )
                    .join(
                        KnowledgeUnit,
                        KnowledgeUnit.id == KnowledgeUnitConcept.knowledge_unit_id,
                    )
                    .where(KnowledgeUnit.source_version_id == version.id)
                    .group_by(
                        ExternalConcept.id,
                        ExternalConcept.canonical_name,
                        ExternalConcept.description,
                    )
                    .order_by(func.count(func.distinct(KnowledgeUnit.id)).desc())
                )
            ).all()
            if version is not None
            else []
        )
        concept_ids = [row[0] for row in rows]
        reuse_rows = (
            (
                await session.execute(
                    select(
                        KnowledgeUnitConcept.concept_id,
                        func.count(func.distinct(KnowledgeUnit.source_version_id)),
                    )
                    .join(
                        KnowledgeUnit,
                        KnowledgeUnit.id == KnowledgeUnitConcept.knowledge_unit_id,
                    )
                    .where(KnowledgeUnitConcept.concept_id.in_(concept_ids))
                    .group_by(KnowledgeUnitConcept.concept_id)
                )
            ).all()
            if concept_ids
            else []
        )
    reuse_counts = {concept_id: int(count) for concept_id, count in reuse_rows}
    concepts = [
        {
            "name": row[1],
            "description": row[2],
            "unit_count": int(row[3]),
            "link_count": int(row[4]),
            "confidence_min": float(row[5]),
            "confidence_max": float(row[6]),
            "shared_versions": reuse_counts.get(row[0], 1),
        }
        for row in rows
    ]
    return await _render(
        request,
        "studio/resource_concepts.html",
        title=f"{source.title} — Concepts",
        source=source,
        state=state,
        concepts=concepts,
        unit_count=sum(item["unit_count"] for item in concepts),
        active_tab="concepts",
    )


@router.get("/library/{source_id}/processing", response_class=HTMLResponse)
async def resource_processing(request: Request, source_id: UUID) -> Response:
    """Owner-readable processing state: per-stage readiness plus warnings."""

    async with _database(request).transaction() as session:
        source = await session.get(Source, source_id)
        if source is None:
            return HTMLResponse("Resource not found", status_code=404)
        version = await session.scalar(
            select(SourceVersion)
            .where(SourceVersion.source_id == source_id)
            .order_by(SourceVersion.created_at.desc())
            .limit(1)
        )
        state = await session.get(SourceProcessingState, source_id)
        warnings: list[str] = []
        stages: list[dict[str, str]] = []
        if version is not None:
            segment_count = int(
                await session.scalar(
                    select(func.count(SourceSegment.id)).where(
                        SourceSegment.source_version_id == version.id
                    )
                )
                or 0
            )
            node_count = int(
                await session.scalar(
                    select(func.count(SourceStructureNode.id)).where(
                        SourceStructureNode.source_version_id == version.id
                    )
                )
                or 0
            )
            units = list(
                await session.scalars(
                    select(KnowledgeUnit).where(
                        KnowledgeUnit.source_version_id == version.id
                    )
                )
            )
            link_count = int(
                await session.scalar(
                    select(func.count(KnowledgeUnitConcept.id))
                    .join(
                        KnowledgeUnit,
                        KnowledgeUnit.id == KnowledgeUnitConcept.knowledge_unit_id,
                    )
                    .where(KnowledgeUnit.source_version_id == version.id)
                )
                or 0
            )
            indexed = sum(1 for unit in units if unit.search_vector is not None)
            stages = [
                {
                    "name": "Transcript",
                    "status": "Ready" if segment_count else "Missing",
                    "detail": f"{segment_count} segments",
                },
                {
                    "name": "Vortragsstruktur",
                    "status": "Ready" if node_count else "Not built",
                    "detail": f"{node_count} nodes",
                },
                {
                    "name": "Knowledge Units",
                    "status": "Ready" if units else "Not extracted",
                    "detail": f"{len(units)} units",
                },
                {
                    "name": "Concept Mapping",
                    "status": "Ready" if link_count else "Not mapped",
                    "detail": f"{link_count} links",
                },
                {
                    "name": "Retrieval Index",
                    "status": "Ready" if indexed else "Not indexed",
                    "detail": f"{indexed} indexed",
                },
            ]
            oversized = [
                unit
                for unit in units
                if unit_retrieval_role(unit.metadata_json) == "SUMMARY"
            ]
            if oversized:
                warnings.append(
                    f"{len(oversized)} oversized unit(s) demoted to summary role"
                )
            unknown = sum(1 for unit in units if unit.claim_type is ClaimType.UNKNOWN)
            if units and unknown:
                warnings.append(
                    f"{unknown} of {len(units)} units have unknown claim type"
                )
            mapped_unit_ids = {
                row[0]
                for row in (
                    await session.execute(
                        select(KnowledgeUnitConcept.knowledge_unit_id)
                        .join(
                            KnowledgeUnit,
                            KnowledgeUnit.id == KnowledgeUnitConcept.knowledge_unit_id,
                        )
                        .where(KnowledgeUnit.source_version_id == version.id)
                    )
                ).all()
            }
            unmapped = sum(1 for unit in units if unit.id not in mapped_unit_ids)
            if units and unmapped:
                warnings.append(f"{unmapped} unit(s) have no concept links")
        if state is not None and state.last_error:
            warnings.append(f"Letzter Fehler: {human_error(state.last_error)}")
    return await _render(
        request,
        "studio/resource_processing.html",
        title=f"{source.title} — Processing",
        source=source,
        version=version,
        state=state,
        stages=stages,
        warnings=warnings,
        active_tab="processing",
    )


@router.get("/library/{source_id}/structure", response_class=HTMLResponse)
async def resource_structure(
    request: Request, source_id: UUID, node: UUID | None = None
) -> Response:
    async with _database(request).transaction() as session:
        source = await session.get(Source, source_id)
        if source is None:
            return HTMLResponse("Resource not found", status_code=404)
        version = await session.scalar(
            select(SourceVersion)
            .where(SourceVersion.source_id == source_id)
            .order_by(SourceVersion.created_at.desc())
            .limit(1)
        )
        state = await session.get(SourceProcessingState, source_id)
    service = SourceStructureService(_database(request))
    tree = await service.get_tree(version.id) if version is not None else []
    detail = await service.get_node_detail(node) if node is not None else None
    return await _render(
        request,
        "studio/resource_structure.html",
        title=f"{source.title} — Structure",
        source=source,
        state=state,
        tree=tree,
        page_by_seq=_page_by_seq(version),
        selected_node=detail[0] if detail else None,
        node_segments=detail[1] if detail else [],
        active_tab="structure",
    )


@router.post("/library/{source_id}/structure")
async def resource_structure_build(request: Request, source_id: UUID) -> Response:
    service = SourceStructureService(_database(request))
    await service.process_source(source_id)
    return RedirectResponse(f"/library/{source_id}/structure", status_code=303)


@router.get("/library/{source_id}/units", response_class=HTMLResponse)
async def resource_units(
    request: Request, source_id: UUID, q: str | None = None
) -> Response:
    async with _database(request).transaction() as session:
        source = await session.get(Source, source_id)
        if source is None:
            return HTMLResponse("Resource not found", status_code=404)
        version = await session.scalar(
            select(SourceVersion)
            .where(SourceVersion.source_id == source_id)
            .order_by(SourceVersion.created_at.desc())
            .limit(1)
        )
        state = await session.get(SourceProcessingState, source_id)
    service = KnowledgeUnitService(_database(request))
    units = await service.list_units(version.id, query=q) if version is not None else []
    async with _database(request).transaction() as session:
        concept_rows = (
            (
                await session.execute(
                    select(
                        KnowledgeUnitConcept.knowledge_unit_id,
                        ExternalConcept.canonical_name,
                    )
                    .join(
                        ExternalConcept,
                        ExternalConcept.id == KnowledgeUnitConcept.concept_id,
                    )
                    .where(
                        KnowledgeUnitConcept.knowledge_unit_id.in_(
                            [unit.id for unit in units]
                        )
                    )
                )
            ).all()
            if units
            else []
        )
    concepts_by_unit: dict[UUID, list[str]] = {}
    for unit_id, name in concept_rows:
        concepts_by_unit.setdefault(unit_id, []).append(name)
    epistemic = {
        unit.id: classify_epistemic(
            unit_type=unit.unit_type,
            claim_type=unit.claim_type,
            evidence_level=unit.evidence_level,
        ).value
        for unit in units
    }
    retrieval_roles = {
        unit.id: unit_retrieval_role(unit.metadata_json) for unit in units
    }
    return await _render(
        request,
        "studio/resource_units.html",
        title=f"{source.title} — Knowledge Units",
        source=source,
        state=state,
        units=units,
        concepts_by_unit=concepts_by_unit,
        epistemic=epistemic,
        retrieval_roles=retrieval_roles,
        query=q or "",
        active_tab="units",
    )


@router.post("/library/{source_id}/units")
async def resource_units_extract(request: Request, source_id: UUID) -> Response:
    service = KnowledgeUnitService(_database(request))
    await service.extract_for_source(source_id)
    return RedirectResponse(f"/library/{source_id}/units", status_code=303)


@router.post("/library/{source_id}/concepts")
async def resource_map_concepts(request: Request, source_id: UUID) -> Response:
    async with _database(request).transaction() as session:
        version = await session.scalar(
            select(SourceVersion)
            .where(SourceVersion.source_id == source_id)
            .order_by(SourceVersion.created_at.desc())
            .limit(1)
        )
    if version is not None:
        await ConceptMappingService(_database(request)).map_source_units(version.id)
    return RedirectResponse(f"/library/{source_id}/units", status_code=303)


@router.get("/studio/search", response_class=HTMLResponse)
async def studio_search(
    request: Request, q: str | None = None, expansion: str = "NONE"
) -> Response:
    mode = (
        ExpansionMode(expansion)
        if expansion in {item.value for item in ExpansionMode}
        else ExpansionMode.NONE
    )
    service = KnowledgeUnitSearchService(
        _database(request),
        getattr(request.app.state, "embedding_provider", None),
    )
    results = await service.search(q, expansion=mode) if q else []
    return await _render(
        request,
        "studio/search.html",
        title="Knowledge Search",
        results=results,
        query=q or "",
        expansion=mode.value,
        modes=list(ExpansionMode),
    )


@router.get("/production", response_class=HTMLResponse)
async def production_list(request: Request) -> HTMLResponse:
    database = _database(request)
    productions = await _brief_states(request)
    async with database.transaction() as session:
        slug_by_id = {
            channel.id: channel.slug
            for channel in (await session.scalars(select(EditorialChannel))).all()
        }
    return await _render(
        request,
        "studio/production_list.html",
        title="Production",
        productions=productions,
        action_labels=_ACTION_LABELS,
        brief_channels={
            state.brief.id: slug_by_id.get(state.brief.editorial_channel_id, "?")
            for state in productions
        },
    )


@router.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request) -> HTMLResponse:
    async with _database(request).transaction() as session:
        stats = {
            "sources": int(await session.scalar(select(func.count(Source.id))) or 0),
            "segments": int(
                await session.scalar(select(func.count(SourceSegment.id))) or 0
            ),
            "productions": int(
                await session.scalar(select(func.count(ContentBrief.id))) or 0
            ),
            "drafts": int(
                await session.scalar(
                    select(func.count(ScriptDraft.id)).where(
                        ScriptDraft.lineage == "primary"
                    )
                )
                or 0
            ),
            "approved": int(
                await session.scalar(
                    select(func.count(ScriptDraft.id)).where(
                        ScriptDraft.lineage == "primary",
                        ScriptDraft.status == DraftStatus.APPROVED,
                    )
                )
                or 0
            ),
            "translations_ready": int(
                await session.scalar(
                    select(func.count(LocalizationPipelineRun.id)).where(
                        LocalizationPipelineRun.stage
                        == LocalizationPipelineStage.READY_FOR_VOICE
                    )
                )
                or 0
            ),
        }
    return await _render(
        request, "studio/analytics.html", title="Analytics", stats=stats
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    settings = get_settings()
    service = StudioSettingsService(_database(request), settings)
    web_research = await service.effective()
    overrides = await service.overrides()
    if web_research.get("web_research_api_key"):
        web_research["web_research_api_key"] = _mask_key(
            str(web_research["web_research_api_key"])
        )
    scheduler = get_scheduler(_database(request))
    return await _render(
        request,
        "studio/settings.html",
        title="Settings",
        environment=settings.environment.value,
        storage_root=str(settings.storage_root),
        llm_provider="APIMaster (rollenbasiert, einziger LLM-Gateway)",
        youtube_mcp_enabled=settings.youtube_mcp_enabled,
        youtube_mcp_url=settings.youtube_mcp_url,
        web_research=web_research,
        web_research_overrides=overrides,
        provider_capacity=get_capacity().snapshot(),
        background_jobs_running=scheduler.active_count(),
        background_jobs_waiting=scheduler.queued_count(),
        background_jobs_by_class=scheduler.active_work_classes(),
        saved=request.query_params.get("saved") == "1",
    )


def _mask_key(value: str) -> str:
    return ("•" * max(len(value) - 4, 0)) + value[-4:] if len(value) > 4 else "••••"


def _clamp_duration(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


@router.post("/settings")
async def settings_save(request: Request) -> Response:
    form = await request.form()
    values: dict[str, Any] = {
        "web_research_enabled": form.get("web_research_enabled") == "on",
        "web_research_provider": str(form.get("web_research_provider") or "tavily"),
        "web_research_base_url": str(form.get("web_research_base_url") or "").strip()
        or None,
        "web_research_model": str(form.get("web_research_model") or "").strip() or None,
        "web_research_max_results": str(
            form.get("web_research_max_results") or ""
        ).strip()
        or None,
        "web_research_timeout_seconds": str(
            form.get("web_research_timeout_seconds") or ""
        ).strip()
        or None,
        "target_duration_default_minutes": str(
            form.get("target_duration_default_minutes") or ""
        ).strip()
        or None,
        "target_duration_min_minutes": str(
            form.get("target_duration_min_minutes") or ""
        ).strip()
        or None,
        "target_duration_max_minutes": str(
            form.get("target_duration_max_minutes") or ""
        ).strip()
        or None,
        "max_revision_rounds": str(form.get("max_revision_rounds") or "").strip()
        or None,
        "first_draft_min_duration_ratio": str(
            form.get("first_draft_min_duration_ratio") or ""
        ).strip()
        or None,
        "first_draft_max_duration_ratio": str(
            form.get("first_draft_max_duration_ratio") or ""
        ).strip()
        or None,
        "generation_max_correction_attempts": str(
            form.get("generation_max_correction_attempts") or ""
        ).strip()
        or None,
        "units_per_video_minute": str(form.get("units_per_video_minute") or "").strip()
        or None,
        "speech_wpm_fa": str(form.get("speech_wpm_fa") or "").strip() or None,
        "speech_wpm_en": str(form.get("speech_wpm_en") or "").strip() or None,
        "speech_wpm_de": str(form.get("speech_wpm_de") or "").strip() or None,
        "speech_wpm_ar": str(form.get("speech_wpm_ar") or "").strip() or None,
        "background_processing_paused": (
            form.get("background_processing_paused") == "on"
        ),
    }
    api_key = str(form.get("web_research_api_key") or "").strip()
    if api_key and not api_key.startswith("•"):
        values["web_research_api_key"] = api_key
    try:
        await StudioSettingsService(_database(request)).set_many(values)
    except ValueError as exc:
        return HTMLResponse(f"Ungültige Einstellung: {exc}", status_code=422)
    # Reflect the toggle on the live scheduler immediately — the next
    # scan re-reads it too, but the owner expects instant effect.
    get_scheduler(_database(request)).set_paused(
        bool(values["background_processing_paused"])
    )
    return RedirectResponse("/settings?saved=1", status_code=303)


# ---------------------------------------------------------------------------
# Global Knowledge browser — exploratory views over the shared base.
# ---------------------------------------------------------------------------

_KNOWLEDGE_SECTIONS = (
    "concepts",
    "units",
    "stories",
    "case_studies",
    "claims",
    "people",
    "works",
    "sources",
)


def _unit_epistemic(unit: KnowledgeUnit) -> str:
    return classify_epistemic(
        unit_type=unit.unit_type,
        claim_type=unit.claim_type,
        evidence_level=unit.evidence_level,
    ).value


async def _unit_sources(
    session: AsyncSession, units: list[KnowledgeUnit]
) -> dict[UUID, tuple[UUID, str, SourceType]]:
    """Map source_version_id → (source_id, title, type) for unit lists."""

    version_ids = {unit.source_version_id for unit in units}
    rows = (
        (
            await session.execute(
                select(SourceVersion.id, Source.id, Source.title, Source.source_type)
                .join(Source, Source.id == SourceVersion.source_id)
                .where(SourceVersion.id.in_(version_ids))
            )
        ).all()
        if version_ids
        else []
    )
    return {row[0]: (row[1], row[2], row[3]) for row in rows}


@router.get("/knowledge", response_class=HTMLResponse)
async def knowledge_browser(
    request: Request,
    section: str = "concepts",
    q: str | None = None,
    unit_type: str | None = None,
    source_type: str | None = None,
    epistemic: str | None = None,
    atomic: str | None = None,
    retrieval_role: str | None = None,
    concept: UUID | None = None,
) -> Response:
    if section not in _KNOWLEDGE_SECTIONS:
        section = "concepts"
    database = _database(request)
    context: dict[str, Any] = {
        "title": "Knowledge",
        "section": section,
        "sections": _KNOWLEDGE_SECTIONS,
        "query": q or "",
        "filters": {
            "unit_type": unit_type or "",
            "source_type": source_type or "",
            "epistemic": epistemic or "",
            "atomic": atomic or "",
            "retrieval_role": retrieval_role or "",
            "concept": str(concept) if concept else "",
        },
        "unit_types": list(KnowledgeUnitType),
        "source_types": list(SourceType),
    }
    async with database.transaction() as session:
        if section == "concepts":
            pattern = f"%{q.strip()}%" if q else None
            statement = (
                select(
                    ExternalConcept.id,
                    ExternalConcept.canonical_name,
                    ExternalConcept.description,
                    func.count(func.distinct(KnowledgeUnit.id)),
                    func.count(func.distinct(KnowledgeUnit.source_version_id)),
                )
                .join(
                    KnowledgeUnitConcept,
                    KnowledgeUnitConcept.concept_id == ExternalConcept.id,
                )
                .join(
                    KnowledgeUnit,
                    KnowledgeUnit.id == KnowledgeUnitConcept.knowledge_unit_id,
                )
                .group_by(
                    ExternalConcept.id,
                    ExternalConcept.canonical_name,
                    ExternalConcept.description,
                )
                .order_by(func.count(func.distinct(KnowledgeUnit.id)).desc())
            )
            if pattern:
                statement = statement.where(
                    ExternalConcept.canonical_name.ilike(pattern)
                    | ExternalConcept.normalized_name.ilike(pattern)
                )
            rows = (await session.execute(statement.limit(300))).all()
            concept_ids = [row[0] for row in rows]
            usage_rows = (
                (
                    await session.execute(
                        select(
                            KnowledgeUnitConcept.concept_id,
                            EditorialChannelResource.editorial_channel_id,
                        )
                        .join(
                            KnowledgeUnit,
                            KnowledgeUnit.id == KnowledgeUnitConcept.knowledge_unit_id,
                        )
                        .join(
                            SourceVersion,
                            SourceVersion.id == KnowledgeUnit.source_version_id,
                        )
                        .join(
                            EditorialChannelResource,
                            EditorialChannelResource.source_id
                            == SourceVersion.source_id,
                        )
                        .where(KnowledgeUnitConcept.concept_id.in_(concept_ids))
                    )
                ).all()
                if concept_ids
                else []
            )
            slug_by_id = {
                channel.id: channel.slug
                for channel in (await session.scalars(select(EditorialChannel))).all()
            }
            usage: dict[UUID, set[str]] = {}
            for concept_id, channel_id in usage_rows:
                usage.setdefault(concept_id, set()).add(
                    slug_by_id.get(channel_id, str(channel_id))
                )
            context["concepts"] = [
                {
                    "id": row[0],
                    "name": row[1],
                    "description": row[2],
                    "unit_count": int(row[3]),
                    "version_count": int(row[4]),
                    "channels": sorted(usage.get(row[0], ())),
                }
                for row in rows
            ]
        elif section in {"units", "stories", "case_studies", "claims"}:
            forced_type = {
                "stories": KnowledgeUnitType.STORY,
                "case_studies": KnowledgeUnitType.CASE_STUDY,
                "claims": KnowledgeUnitType.CLAIM,
            }.get(section)
            unit_stmt = select(KnowledgeUnit)
            if forced_type is not None:
                unit_stmt = unit_stmt.where(KnowledgeUnit.unit_type == forced_type)
            elif unit_type:
                with contextlib.suppress(ValueError):
                    unit_stmt = unit_stmt.where(
                        KnowledgeUnit.unit_type == KnowledgeUnitType(unit_type)
                    )
            if atomic == "1":
                unit_stmt = unit_stmt.where(KnowledgeUnit.atomic.is_(True))
            if retrieval_role:
                unit_stmt = unit_stmt.where(
                    KnowledgeUnit.metadata_json["retrieval_role"].astext
                    == retrieval_role
                )
            if concept is not None:
                unit_stmt = unit_stmt.join(
                    KnowledgeUnitConcept,
                    KnowledgeUnitConcept.knowledge_unit_id == KnowledgeUnit.id,
                ).where(KnowledgeUnitConcept.concept_id == concept)
            if q:
                pattern = f"%{q.strip()}%"
                unit_stmt = unit_stmt.where(
                    KnowledgeUnit.title.ilike(pattern)
                    | KnowledgeUnit.summary.ilike(pattern)
                )
            units = list(
                await session.scalars(
                    unit_stmt.order_by(KnowledgeUnit.created_at.desc()).limit(500)
                )
            )
            source_map = await _unit_sources(session, units)
            if source_type:
                with contextlib.suppress(ValueError):
                    wanted = SourceType(source_type)
                    units = [
                        unit
                        for unit in units
                        if source_map.get(unit.source_version_id, (None, "", None))[2]
                        is wanted
                    ]
            epistemic_map = {unit.id: _unit_epistemic(unit) for unit in units}
            if epistemic == "UNCERTAIN":
                units = [
                    unit
                    for unit in units
                    if epistemic_map[unit.id] in _UNCERTAIN_EPISTEMIC
                ]
            elif epistemic:
                units = [unit for unit in units if epistemic_map[unit.id] == epistemic]
            units = units[:200]
            concept_rows = (
                (
                    await session.execute(
                        select(
                            KnowledgeUnitConcept.knowledge_unit_id,
                            ExternalConcept.canonical_name,
                        )
                        .join(
                            ExternalConcept,
                            ExternalConcept.id == KnowledgeUnitConcept.concept_id,
                        )
                        .where(
                            KnowledgeUnitConcept.knowledge_unit_id.in_(
                                [unit.id for unit in units]
                            )
                        )
                    )
                ).all()
                if units
                else []
            )
            concepts_by_unit: dict[UUID, list[str]] = {}
            for unit_id, name in concept_rows:
                concepts_by_unit.setdefault(unit_id, []).append(name)
            used_ids: set[str] = set()
            if section in {"stories", "case_studies"}:
                for raw_ids in (
                    await session.scalars(select(ScriptSignature.story_unit_ids))
                ).all():
                    used_ids.update(str(unit_id) for unit_id in raw_ids)
            context["units"] = [
                {
                    "unit": unit,
                    "epistemic": epistemic_map[unit.id],
                    "uncertain": epistemic_map[unit.id] in _UNCERTAIN_EPISTEMIC,
                    "role": unit_retrieval_role(unit.metadata_json),
                    "concepts": sorted(concepts_by_unit.get(unit.id, ())),
                    "source_id": source_map.get(
                        unit.source_version_id, (None, "", None)
                    )[0],
                    "source_title": source_map.get(
                        unit.source_version_id, (None, "", None)
                    )[1],
                    "source_type": source_map.get(
                        unit.source_version_id, (None, "", None)
                    )[2],
                    "used": str(unit.id) in used_ids,
                }
                for unit in units
            ]
        elif section == "people":
            person_stmt = select(Person).order_by(Person.canonical_name)
            if q:
                person_stmt = person_stmt.where(
                    Person.canonical_name.ilike(f"%{q.strip()}%")
                )
            people = list(await session.scalars(person_stmt.limit(300)))
            label_rows = (
                (
                    await session.execute(
                        select(EntityLabel.person_id, func.count(EntityLabel.id))
                        .where(EntityLabel.person_id.in_([p.id for p in people]))
                        .group_by(EntityLabel.person_id)
                    )
                ).all()
                if people
                else []
            )
            label_counts = {row[0]: int(row[1]) for row in label_rows}
            context["people"] = [
                {"person": person, "labels": label_counts.get(person.id, 0)}
                for person in people
            ]
        elif section == "works":
            work_stmt = select(Work).order_by(Work.canonical_title)
            if q:
                work_stmt = work_stmt.where(
                    Work.canonical_title.ilike(f"%{q.strip()}%")
                )
            context["works"] = list(await session.scalars(work_stmt.limit(300)))
        elif section == "sources":
            sources = list(
                await session.scalars(
                    select(Source).order_by(Source.created_at.desc()).limit(300)
                )
            )
            stats = await _source_stats(request, [s.id for s in sources])
            context["sources"] = [
                {"source": source, "stats": stats.get(source.id, {})}
                for source in sources
            ]
    return await _render(request, "studio/knowledge.html", **context)


@router.get("/knowledge/concepts/{concept_id}", response_class=HTMLResponse)
async def knowledge_concept_detail(request: Request, concept_id: UUID) -> Response:
    async with _database(request).transaction() as session:
        concept = await session.get(ExternalConcept, concept_id)
        if concept is None:
            return HTMLResponse("Concept not found", status_code=404)
        labels = list(
            await session.scalars(
                select(EntityLabel).where(EntityLabel.concept_id == concept_id)
            )
        )
        link_rows = (
            await session.execute(
                select(KnowledgeUnit, KnowledgeUnitConcept.confidence)
                .join(
                    KnowledgeUnitConcept,
                    KnowledgeUnitConcept.knowledge_unit_id == KnowledgeUnit.id,
                )
                .where(KnowledgeUnitConcept.concept_id == concept_id)
                .order_by(KnowledgeUnitConcept.confidence.desc())
                .limit(200)
            )
        ).all()
        units = [row[0] for row in link_rows]
        confidence_by_unit = {row[0].id: float(row[1]) for row in link_rows}
        source_map = await _unit_sources(session, units)
        source_ids = {value[0] for value in source_map.values() if value[0] is not None}
        channels = (
            (
                await session.execute(
                    select(
                        EditorialChannelResource.source_id,
                        EditorialChannel.slug,
                    )
                    .join(
                        EditorialChannel,
                        EditorialChannel.id
                        == EditorialChannelResource.editorial_channel_id,
                    )
                    .where(EditorialChannelResource.source_id.in_(source_ids))
                )
            ).all()
            if source_ids
            else []
        )
        related_rows = (
            await session.execute(
                select(
                    KnowledgeUnitConcept.concept_id,
                    func.count(),
                )
                .where(
                    KnowledgeUnitConcept.knowledge_unit_id.in_(
                        select(KnowledgeUnitConcept.knowledge_unit_id).where(
                            KnowledgeUnitConcept.concept_id == concept_id
                        )
                    ),
                    KnowledgeUnitConcept.concept_id != concept_id,
                )
                .group_by(KnowledgeUnitConcept.concept_id)
                .order_by(func.count().desc())
                .limit(10)
            )
        ).all()
        related = (
            list(
                await session.scalars(
                    select(ExternalConcept).where(
                        ExternalConcept.id.in_([row[0] for row in related_rows])
                    )
                )
            )
            if related_rows
            else []
        )
    return await _render(
        request,
        "studio/knowledge_concept.html",
        title=f"Concept — {concept.canonical_name}",
        concept=concept,
        labels=labels,
        units=units,
        confidence_by_unit=confidence_by_unit,
        source_map=source_map,
        channels=sorted({slug for _sid, slug in channels}),
        related=related,
    )
