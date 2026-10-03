"""Studio shell routes: channel workspaces, resource library, production."""

import contextlib
from pathlib import Path
from typing import TypedDict, cast
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

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
from app.knowledge.models import ExternalConcept, Source, SourceSegment, SourceVersion
from app.knowledge.structure.models import SourceProcessingState
from app.knowledge.structure.service import SourceStructureService
from app.knowledge.units.mapping_service import ConceptMappingService
from app.knowledge.units.models import KnowledgeUnitConcept
from app.knowledge.units.service import KnowledgeUnitService
from app.lecture.generic_service import GenericMasterService
from app.production.service import ProductionService
from app.research.generic import GenericResearchService
from app.retrieval.unit_retrieval import (
    ExpansionMode,
    KnowledgeUnitSearchService,
)
from app.topics.domain import TopicStatus
from app.topics.models import TopicCandidate
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
        production_count = int(
            await session.scalar(
                select(func.count(EditorialProject.id)).where(
                    EditorialProject.status != "PUBLISHED"
                )
            )
            or 0
        )
    return await _render(
        request,
        "studio/home.html",
        title="Studio",
        channels=summaries,
        source_count=source_count,
        production_count=production_count,
    )


@router.get("/studio/channels", response_class=HTMLResponse)
async def studio_channels(request: Request) -> HTMLResponse:
    summaries = await _service(request).channel_summaries()
    return await _render(
        request, "studio/channels.html", title="Channels", channels=summaries
    )


@router.get("/studio/channels/{slug}", response_class=HTMLResponse)
async def channel_overview(request: Request, slug: str) -> Response:
    context = await _channel_context(request, slug)
    if context is None:
        return HTMLResponse("Channel not found", status_code=404)
    source_ids = [link.source_id for link in context["resources"]]
    async with _database(request).transaction() as session:
        sources = (
            list(await session.scalars(select(Source).where(Source.id.in_(source_ids))))
            if source_ids
            else []
        )
    return await _render(
        request,
        "studio/channel_overview.html",
        title=context["channel"].name,
        sources=sources,
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
async def channel_topics(request: Request, slug: str) -> Response:
    context = await _channel_context(request, slug)
    if context is None:
        return HTMLResponse("Channel not found", status_code=404)
    candidates = await TopicService(_database(request)).list_candidates(slug)
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
        actionable_statuses=[
            TopicStatus.SHORTLISTED,
            TopicStatus.NEEDS_RESEARCH,
            TopicStatus.REJECTED,
            TopicStatus.ARCHIVED,
        ],
        **context,
    )


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
    return await _render(
        request,
        "studio/channel_production.html",
        title=f"{context['channel'].name} — Production",
        **context,
    )


@router.get("/studio/channels/{slug}/published", response_class=HTMLResponse)
async def channel_published(request: Request, slug: str) -> Response:
    context = await _channel_context(request, slug)
    if context is None:
        return HTMLResponse("Channel not found", status_code=404)
    return await _render(
        request,
        "studio/channel_published.html",
        title=f"{context['channel'].name} — Published",
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
    return await _render(
        request,
        "studio/brief_workspace.html",
        title=f"Production — {state.brief.question[:60]}",
        state=state,
        brief=state.brief,
        channel_slug=channel_slug,
        stages=list(ProductionStage),
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
}


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
            async with database.transaction() as session:
                draft_id = await session.scalar(
                    select(ScriptDraft.id)
                    .where(ScriptDraft.content_brief_id == brief_id)
                    .order_by(ScriptDraft.version_number.desc())
                    .limit(1)
                )
            if draft_id is not None:
                await ScriptService(database).review_draft(draft_id)
        elif action == "revise":
            async with database.transaction() as session:
                draft_id = await session.scalar(
                    select(ScriptDraft.id)
                    .where(ScriptDraft.content_brief_id == brief_id)
                    .order_by(ScriptDraft.version_number.desc())
                    .limit(1)
                )
            if draft_id is not None:
                await ScriptService(database).revise_draft(draft_id)
        elif action == "approve":
            async with database.transaction() as session:
                draft_id = await session.scalar(
                    select(ScriptDraft.id)
                    .where(ScriptDraft.content_brief_id == brief_id)
                    .order_by(ScriptDraft.version_number.desc())
                    .limit(1)
                )
            if draft_id is not None:
                await ScriptService(database).approve_draft(draft_id)
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
async def resource_library(request: Request) -> HTMLResponse:
    service = _service(request)
    channels = await service.list_channels()
    async with _database(request).transaction() as session:
        sources = list(
            await session.scalars(select(Source).order_by(Source.created_at.desc()))
        )
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
    return await _render(
        request,
        "studio/resource_library.html",
        title="Resource Library",
        sources=sources,
        segment_counts=segment_counts,
        assignments=assignments,
        channels=channels,
        error=None,
    )


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
        version_ids = [version.id for version in versions]
        segments = (
            list(
                await session.scalars(
                    select(SourceSegment)
                    .where(SourceSegment.source_version_id.in_(version_ids))
                    .order_by(SourceSegment.sequence)
                )
            )
            if version_ids
            else []
        )
        links = list(
            await session.scalars(
                select(EditorialChannelResource).where(
                    EditorialChannelResource.source_id == source_id
                )
            )
        )
    slug_by_id = {channel.id: channel.slug for channel in channels}
    return await _render(
        request,
        "studio/resource_detail.html",
        title=source.title,
        source=source,
        versions=versions,
        segments=segments,
        channels=channels,
        assigned_slugs=[
            slug_by_id.get(link.editorial_channel_id, "?") for link in links
        ],
        active_tab="original",
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
    return await _render(
        request,
        "studio/resource_units.html",
        title=f"{source.title} — Knowledge Units",
        source=source,
        state=state,
        units=units,
        concepts_by_unit=concepts_by_unit,
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
    async with _database(request).transaction() as session:
        items = await load_library_items(session, status="ACTIVE")
    return await _render(
        request,
        "studio/production_list.html",
        title="Production",
        items=items,
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
