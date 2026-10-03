"""Studio shell routes: channel workspaces, resource library, production."""

import contextlib
from pathlib import Path
from typing import TypedDict, cast
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.briefs.models import ContentBrief
from app.briefs.service import BriefInput, BriefService
from app.content_engine.domain import ProductionStage
from app.content_engine.models import ScriptDraft
from app.content_engine.review import ScriptService
from app.content_engine.service import (
    ContentEngineService,
    GateBlockedError,
)
from app.content_strategy.models import (
    EditorialLanguageTrack,
    EditorialProject,
    PersianDraft,
)
from app.content_strategy.text_library import load_library_items
from app.core.config import get_settings
from app.core.exceptions import ApplicationError
from app.db.session import Database
from app.editorial_channels.domain import ChannelResourceRole
from app.editorial_channels.models import (
    ChannelStrategyVersion,
    EditorialChannel,
    EditorialChannelResource,
)
from app.editorial_channels.service import (
    ChannelNotFoundError,
    EditorialChannelService,
)
from app.knowledge.domain import SourceType
from app.knowledge.models import (
    ExternalConcept,
    Source,
    SourceSegment,
    SourceVersion,
)
from app.knowledge.structure.domain import SourceProcessingStatus
from app.knowledge.structure.models import SourceProcessingState, SourceStructureNode
from app.knowledge.structure.service import SourceStructureService
from app.knowledge.units.domain import ClaimType
from app.knowledge.units.mapping_service import ConceptMappingService
from app.knowledge.units.models import KnowledgeUnit, KnowledgeUnitConcept
from app.knowledge.units.quality import unit_retrieval_role
from app.knowledge.units.service import KnowledgeUnitService
from app.lecture.domain import PublicationLanguage
from app.lecture.generic_service import GenericMasterService
from app.localization.service import LocalizationService
from app.production.service import ProductionService, ProductionState
from app.research.epistemic import classify_epistemic
from app.research.generic import GenericResearchService
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
from app.web.service import import_youtube_resource

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
    return templates.TemplateResponse(request=request, name=name, context=context)


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
    attention_states = (
        SourceProcessingStatus.STRUCTURE_REVIEW_REQUIRED,
        SourceProcessingStatus.UNIT_REVIEW_REQUIRED,
        SourceProcessingStatus.FAILED,
    )
    async with _database(request).transaction() as session:
        source_count = int(await session.scalar(select(func.count(Source.id))) or 0)
        attention_rows = (
            await session.execute(
                select(Source, SourceProcessingState)
                .join(
                    SourceProcessingState,
                    SourceProcessingState.source_id == Source.id,
                )
                .where(SourceProcessingState.status.in_(attention_states))
                .order_by(SourceProcessingState.updated_at.desc())
                .limit(10)
            )
        ).all()
        attention = [
            {
                "source": source,
                "status": state.status.value,
                "error": state.last_error,
            }
            for source, state in attention_rows
        ]
        recent_signatures = list(
            await session.scalars(
                select(ScriptSignature)
                .order_by(ScriptSignature.created_at.desc())
                .limit(5)
            )
        )
    productions = await _brief_states(request, limit=8)
    return await _render(
        request,
        "studio/home.html",
        title="Studio",
        channels=summaries,
        source_count=source_count,
        production_count=len(productions),
        productions=productions,
        attention=attention,
        recent_signatures=recent_signatures,
    )


@router.get("/studio/channels", response_class=HTMLResponse)
async def studio_channels(request: Request) -> HTMLResponse:
    summaries = await _service(request).channel_summaries()
    return await _render(
        request, "studio/channels.html", title="Channels", channels=summaries
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
    with contextlib.suppress(ApplicationError):
        await service.activate_strategy(version_id)
    return RedirectResponse(f"/studio/channels/{slug}/strategy", status_code=303)


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


@router.get("/studio/production/{brief_id}", response_class=HTMLResponse)
async def brief_workspace(request: Request, brief_id: UUID) -> Response:
    try:
        state = await ProductionService(_database(request)).state_for_brief(brief_id)
    except LookupError:
        return HTMLResponse("Brief not found", status_code=404)
    channel_slug = ""
    async with _database(request).transaction() as session:
        channel = await session.get(EditorialChannel, state.brief.editorial_channel_id)
        if channel is not None:
            channel_slug = channel.slug
        signature = None
        if state.latest_draft_id is not None:
            signature = await session.scalar(
                select(ScriptSignature).where(
                    ScriptSignature.script_draft_id == state.latest_draft_id
                )
            )
        draft_status = None
        if state.latest_draft_id is not None:
            draft_status = await session.scalar(
                select(ScriptDraft.status).where(
                    ScriptDraft.id == state.latest_draft_id
                )
            )
    return await _render(
        request,
        "studio/brief_workspace.html",
        title=f"Production — {state.brief.question[:60]}",
        state=state,
        brief=state.brief,
        channel_slug=channel_slug,
        stages=list(ProductionStage),
        signature=signature,
        draft_status=draft_status,
    )


_ACTION_HANDLERS = {
    "plan_research": "research",
    "build_evidence": "evidence",
    "build_argument": "argument",
    "build_narrative": "narrative",
    "build_master": "master",
    "build_script": "script",
    "run_review": "review",
    "revise": "revise",
    "approve": "approve",
    "localize": "localize",
}


async def _latest_draft_id(database: Database, brief_id: UUID) -> UUID | None:
    async with database.transaction() as session:
        result: UUID | None = await session.scalar(
            select(ScriptDraft.id)
            .where(ScriptDraft.content_brief_id == brief_id)
            .order_by(ScriptDraft.version_number.desc())
            .limit(1)
        )
        return result


@router.post("/studio/production/{brief_id}/actions/{action}")
async def production_action(request: Request, brief_id: UUID, action: str) -> Response:
    """Run one pipeline action; availability was already gated by state."""

    if action not in _ACTION_HANDLERS:
        return HTMLResponse("Unknown action", status_code=404)
    database = _database(request)
    try:
        if action == "plan_research":
            await GenericResearchService(database).create_plan_for_brief(brief_id)
        elif action == "build_evidence":
            await GenericResearchService(database).build_evidence_matrix(brief_id)
        elif action == "build_argument":
            await ContentEngineService(database).build_argument(brief_id)
        elif action == "build_narrative":
            await ContentEngineService(database).build_narrative(brief_id)
        elif action == "build_master":
            await GenericMasterService(database).build_from_content_brief(brief_id)
        elif action == "build_script":
            await ScriptService(database).build_script(brief_id)
        elif action == "run_review":
            draft_id = await _latest_draft_id(database, brief_id)
            if draft_id is not None:
                await ScriptService(database).review_draft(draft_id)
        elif action == "revise":
            draft_id = await _latest_draft_id(database, brief_id)
            if draft_id is not None:
                await ScriptService(database).revise_draft(draft_id)
        elif action == "approve":
            draft_id = await _latest_draft_id(database, brief_id)
            if draft_id is not None:
                await ScriptService(database).approve_draft(draft_id)
        elif action == "localize":
            form = await request.form()
            language = str(form.get("language") or "en")
            state = await ProductionService(database).state_for_brief(brief_id)
            if state.latest_master_id is not None:
                await LocalizationService(database).create(
                    state.latest_master_id, PublicationLanguage(language)
                )
    except (LookupError, ValueError, GateBlockedError):
        pass
    return RedirectResponse(f"/studio/production/{brief_id}", status_code=303)


@router.post("/studio/topics/{candidate_id}/brief")
async def topic_create_brief(request: Request, candidate_id: UUID) -> Response:
    """Create a minimal ContentBrief from a candidate, then open its page."""

    database = _database(request)
    async with database.transaction() as session:
        candidate = await session.get(TopicCandidate, candidate_id)
    if candidate is None:
        return HTMLResponse("Candidate not found", status_code=404)
    try:
        brief = await BriefService(database).create_for_candidate(
            candidate_id,
            BriefInput(
                question=candidate.video_question,
                thesis=candidate.tentative_thesis,
                target_duration_minutes=12,
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
    return await _render(
        request,
        "studio/resource_library.html",
        title="Resource Library",
        sources=sources,
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


def _status_matches(state: SourceProcessingState | None, status: str) -> bool:
    """Bucket the persisted processing status into owner-facing filters."""

    if status == "READY":
        return state is not None and state.status is SourceProcessingStatus.READY
    if status == "PROCESSING":
        return state is not None and state.status in {
            SourceProcessingStatus.INGESTED,
            SourceProcessingStatus.STRUCTURE_PENDING,
            SourceProcessingStatus.STRUCTURING,
            SourceProcessingStatus.STRUCTURED,
            SourceProcessingStatus.UNIT_EXTRACTION_PENDING,
            SourceProcessingStatus.UNIT_EXTRACTING,
        }
    if status == "REVIEW_REQUIRED":
        return state is not None and state.status in {
            SourceProcessingStatus.STRUCTURE_REVIEW_REQUIRED,
            SourceProcessingStatus.UNIT_REVIEW_REQUIRED,
        }
    if status == "FAILED":
        return state is not None and state.status is SourceProcessingStatus.FAILED
    return True


@router.post("/library/import")
async def library_import(request: Request) -> Response:
    form = await request.form()
    locator = str(form.get("url", "")).strip()
    try:
        source_id = await import_youtube_resource(_database(request), locator)
    except Exception:
        return RedirectResponse("/library?import=failed", status_code=303)
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
            warnings.append(f"Last error: {state.last_error}")
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
        items = await load_library_items(session, status="ACTIVE")
    return await _render(
        request,
        "studio/production_list.html",
        title="Production",
        items=items,
        productions=productions,
        brief_channels={
            state.brief.id: slug_by_id.get(state.brief.editorial_channel_id, "?")
            for state in productions
        },
    )


@router.get("/production/{project_id}", response_class=HTMLResponse)
async def production_workspace(request: Request, project_id: UUID) -> Response:
    async with _database(request).transaction() as session:
        project = await session.get(EditorialProject, project_id)
        if project is None:
            return HTMLResponse("Production not found", status_code=404)
        drafts = list(
            await session.scalars(
                select(PersianDraft)
                .where(PersianDraft.editorial_project_id == project_id)
                .order_by(PersianDraft.version_number.desc())
            )
        )
        tracks = list(
            await session.scalars(
                select(EditorialLanguageTrack).where(
                    EditorialLanguageTrack.editorial_project_id == project_id
                )
            )
        )
    return await _render(
        request,
        "studio/production_workspace.html",
        title=project.title,
        project=project,
        drafts=drafts,
        tracks=tracks,
    )


@router.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request) -> HTMLResponse:
    async with _database(request).transaction() as session:
        stats = {
            "sources": int(await session.scalar(select(func.count(Source.id))) or 0),
            "segments": int(
                await session.scalar(select(func.count(SourceSegment.id))) or 0
            ),
            "projects": int(
                await session.scalar(select(func.count(EditorialProject.id))) or 0
            ),
            "drafts": int(
                await session.scalar(select(func.count(PersianDraft.id))) or 0
            ),
            "tracks": int(
                await session.scalar(select(func.count(EditorialLanguageTrack.id))) or 0
            ),
        }
    return await _render(
        request, "studio/analytics.html", title="Analytics", stats=stats
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    settings = get_settings()
    return await _render(
        request,
        "studio/settings.html",
        title="Settings",
        environment=settings.environment.value,
        storage_root=str(settings.storage_root),
        llm_provider=settings.llm_provider,
        youtube_mcp_enabled=settings.youtube_mcp_enabled,
        youtube_mcp_url=settings.youtube_mcp_url,
    )
