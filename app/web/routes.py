"""German-first owner routes for sources, knowledge, and topic discovery."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.channel_monitoring.domain import CandidateStatus
from app.channel_monitoring.models import ChannelVideoCandidate, MonitoredChannel
from app.channel_monitoring.service import ChannelDiscoveryService
from app.content_strategy.domain import TopicOrigin, TopicWorkspaceStatus
from app.content_strategy.lesson_workflow import (
    lesson_package_from_project,
    lesson_project_metadata,
    lesson_research_summary,
)
from app.content_strategy.models import (
    ContentTopic,
    EditorialLanguageTrack,
    EditorialProject,
    PersianDraft,
    PersianReviewFinding,
    TopicSuggestionBatch,
)
from app.content_strategy.multilingual_service import MultilingualEditorialService
from app.content_strategy.persian_service import PersianEditorialService
from app.content_strategy.story_library import StoryLibrary
from app.content_strategy.strategy_service import TopicStrategyService
from app.content_strategy.text_library import (
    TRACK_STATUS_LABELS,
    archive_project,
    duplicate_project,
    library_filter_options,
    load_library_items,
    publish_project,
    restore_project,
)
from app.core.config import get_settings
from app.db.session import Database
from app.knowledge.adapters.youtube_mcp import YouTubeMcpClient
from app.knowledge.models import (
    ExternalClaim,
    Mention,
    ReviewFlag,
    Source,
    SourceSegment,
    SourceVersion,
)
from app.knowledge.structure.scheduler import (
    collect_source_infos,
    get_scheduler,
    summarize_states,
)
from app.lecture.domain import PublicationLanguage
from app.localization.lexicon import (
    CRITICALITY_LABELS,
    DEFAULT_PROVIDER_PROFILE,
    LANGUAGES,
    STATUS_LABELS,
    PronunciationLexiconService,
    load_approved_lexicon,
)
from app.localization.pronunciation import (
    PronunciationPreparation,
    prepare_pronunciation,
)
from app.topic_discovery import (
    TopicAnalysisService,
    TopicSuggestionService,
    dashboard_counts,
    save_topic,
    topic_detail_view,
)
from app.web.service import TopicSuggestion, import_youtube_resource

router = APIRouter(tags=["owner-web"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
logger = logging.getLogger(__name__)


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


async def _render(request: Request, name: str, **context: object) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name=name, context=context)


def _optional_int(value: str) -> int | None:
    """Treat empty HTML number inputs as absent instead of returning HTTP 422."""

    try:
        return int(value) if value.strip() else None
    except ValueError:
        return None


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    async with _database(request).transaction() as session:
        counts = await dashboard_counts(session)
        sources = list(
            await session.scalars(
                select(Source).order_by(Source.created_at.desc()).limit(5)
            )
        )
        topics = list(
            await session.scalars(
                select(ContentTopic).order_by(ContentTopic.id.desc()).limit(5)
            )
        )
        pending_channels = int(
            await session.scalar(
                select(func.count(ChannelVideoCandidate.id)).where(
                    ChannelVideoCandidate.status == CandidateStatus.NEW
                )
            )
            or 0
        )
        structure_states = summarize_states(
            await collect_source_infos(session),
            get_scheduler(_database(request)),
            now=datetime.now(UTC),
        )
    structure_counts: dict[str, int] = {}
    for state in structure_states.values():
        key = state.status.value
        structure_counts[key] = structure_counts.get(key, 0) + 1
    return await _render(
        request,
        "dashboard.html",
        title="Dashboard",
        counts=counts,
        sources=sources,
        topics=topics,
        pending_channels=pending_channels,
        structure_counts=structure_counts,
    )


@router.get("/sources", response_class=HTMLResponse)
async def sources(request: Request) -> HTMLResponse:
    async with _database(request).transaction() as session:
        rows = list(
            await session.scalars(select(Source).order_by(Source.created_at.desc()))
        )
        segment_counts = dict(
            (source_id, count)
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
        )
    return await _render(
        request,
        "sources.html",
        title="Quellen",
        sources=rows,
        segment_counts=segment_counts,
        error=None,
    )


@router.get("/sources/new", response_class=HTMLResponse)
async def source_form(request: Request) -> HTMLResponse:
    mcp_status: str | None = None
    settings = get_settings()
    if settings.youtube_mcp_enabled:
        client = YouTubeMcpClient(
            settings.youtube_mcp_url,
            timeout_seconds=min(settings.youtube_mcp_timeout_seconds, 10),
        )
        mcp_status = "verbunden" if await client.health() else "nicht erreichbar"
    return await _render(
        request,
        "source_new.html",
        title="Quelle hinzufügen",
        error=None,
        mcp_status=mcp_status,
    )


@router.post("/sources", response_class=HTMLResponse)
async def add_source(request: Request) -> Response:
    form = await request.form()
    locator = str(form.get("url", "")).strip()
    try:
        await import_youtube_resource(_database(request), locator)
    except ValueError as exc:
        return await _render(
            request, "source_new.html", title="Quelle hinzufügen", error=str(exc)
        )
    except Exception:
        return await _render(
            request,
            "source_new.html",
            title="Quelle hinzufügen",
            error=(
                "Die Quelle konnte nicht verarbeitet werden. "
                "Bitte URL und Transkript prüfen."
            ),
        )
    return RedirectResponse("/sources", status_code=303)


@router.get("/sources/{source_id}", response_class=HTMLResponse)
async def source_detail(request: Request, source_id: UUID) -> HTMLResponse:
    async with _database(request).transaction() as session:
        source = await session.get(Source, source_id)
        if source is None:
            return HTMLResponse("Quelle nicht gefunden", status_code=404)
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
        mentions = (
            list(
                await session.scalars(
                    select(Mention)
                    .where(Mention.source_version_id.in_(version_ids))
                    .order_by(Mention.created_at)
                )
            )
            if version_ids
            else []
        )
        claims = (
            list(
                await session.scalars(
                    select(ExternalClaim)
                    .where(ExternalClaim.source_version_id.in_(version_ids))
                    .order_by(ExternalClaim.created_at)
                )
            )
            if version_ids
            else []
        )
        reviews = (
            list(
                await session.scalars(
                    select(ReviewFlag)
                    .where(ReviewFlag.source_version_id.in_(version_ids))
                    .order_by(ReviewFlag.created_at)
                )
            )
            if version_ids
            else []
        )
    return await _render(
        request,
        "source_detail.html",
        title=source.title,
        source=source,
        segments=segments,
        mentions=mentions,
        claims=claims,
        reviews=reviews,
    )


# NOTE: `/knowledge` is served by the Studio browser in
# `app/web/studio_routes.py`; the legacy German list view was retired.


@router.get("/lessons")
async def retired_lessons() -> RedirectResponse:
    """The 100-lesson catalog is retired; production lives in the Studio."""

    return RedirectResponse("/studio", status_code=303)


@router.get("/lessons/{rest:path}")
async def retired_lesson_urls(rest: str) -> RedirectResponse:
    """Keep old lesson bookmarks safe without exposing the catalog."""

    return RedirectResponse("/studio", status_code=303)


@router.get("/stories", response_class=HTMLResponse)
async def stories(
    request: Request,
    q: str = "",
    category: str = "",
    lesson_id: str = "",
) -> HTMLResponse:
    """Render curated external stories as research material, not canon."""

    try:
        library = StoryLibrary()
        selected = library.search(query=q, category=category, lesson_id=lesson_id)
        error = None
    except (FileNotFoundError, ValueError) as exc:
        logger.exception("story library unavailable")
        library = None
        selected = ()
        error = str(exc)
    return await _render(
        request,
        "stories.html",
        title="Geschichten",
        stories=selected,
        total=library.count if library else 0,
        categories=library.categories if library else (),
        q=q,
        category=category,
        lesson_id=lesson_id,
        error=error,
    )


@router.get("/stories/{story_id}", response_class=HTMLResponse)
async def story_detail(request: Request, story_id: str) -> HTMLResponse:
    try:
        story = StoryLibrary().story(story_id)
    except FileNotFoundError:
        return HTMLResponse("Story Bank nicht gefunden", status_code=503)
    except ValueError:
        return HTMLResponse("Geschichte nicht gefunden", status_code=404)
    return await _render(
        request,
        "story_detail.html",
        title=story.title_fa,
        story=story,
    )


@router.get("/topics", response_class=HTMLResponse)
async def topics(request: Request) -> HTMLResponse:
    selected_status = str(request.query_params.get("status", "NEW")).upper()
    allowed_statuses = {item.value for item in TopicWorkspaceStatus}
    if selected_status not in allowed_statuses:
        selected_status = TopicWorkspaceStatus.NEW.value
    async with _database(request).transaction() as session:
        rows = list(
            await session.scalars(select(ContentTopic).order_by(ContentTopic.id.desc()))
        )
        counts: dict[str, int] = {status: 0 for status in allowed_statuses}
        for topic in rows:
            key = str(topic.workspace_status)
            counts[key] = counts.get(key, 0) + 1
        rows = [
            topic for topic in rows if str(topic.workspace_status) == selected_status
        ]
    return await _render(
        request,
        "topics.html",
        title="Themen",
        topics=rows,
        suggestions=None,
        analysis=None,
        error=None,
        selected_status=selected_status,
        counts=counts,
    )


@router.post("/topics/suggestions", response_class=HTMLResponse)
async def topic_suggestions(request: Request) -> HTMLResponse:
    form = await request.form()
    raw_count = str(form.get("requested_count", "5")).strip()
    requested_count = int(raw_count) if raw_count.isdigit() else 5
    instruction = str(form.get("owner_instruction", "")).strip() or None
    async with _database(request).transaction() as session:
        batch = TopicSuggestionBatch(
            requested_count=requested_count,
            owner_instruction=instruction,
            corpus_snapshot={
                "source_count": int(
                    await session.scalar(select(func.count(Source.id))) or 0
                ),
                "topic_count": int(
                    await session.scalar(select(func.count(ContentTopic.id))) or 0
                ),
            },
        )
        session.add(batch)
        await session.flush()
        suggestions = await TopicSuggestionService().suggestions(
            session,
            requested_count=min(requested_count * 4, 50),
            owner_instruction=instruction,
        )
        existing_topics = list(await session.scalars(select(ContentTopic)))
        existing = {
            " ".join(f"{topic.title} {topic.human_question}".lower().split())
            for topic in existing_topics
        }
        accepted_suggestions: list[TopicSuggestion] = []
        for suggestion in suggestions:
            if len(accepted_suggestions) >= requested_count:
                break
            identity = " ".join(
                f"{suggestion.title} {suggestion.human_question}".lower().split()
            )
            if identity in existing:
                continue
            if any(
                TopicSuggestionService._overlap(
                    suggestion.human_question, topic.human_question
                )
                >= 0.92
                for topic in existing_topics
            ):
                continue
            analysis = await TopicAnalysisService().analyze(
                session, suggestion.human_question
            )
            analysis["rationale"] = suggestion.rationale
            analysis["suggestion_type"] = suggestion.suggestion_type
            await save_topic(
                session,
                title=suggestion.title,
                question=suggestion.human_question,
                origin=TopicOrigin.AI_SUGGESTED,
                analysis=analysis,
                suggestion_batch_id=batch.id,
            )
            existing.add(identity)
            accepted_suggestions.append(suggestion)
        rows = list(
            await session.scalars(
                select(ContentTopic)
                .where(ContentTopic.workspace_status == TopicWorkspaceStatus.NEW)
                .order_by(ContentTopic.id.desc())
            )
        )
        all_topics = list(await session.scalars(select(ContentTopic)))
        counts = {status.value: 0 for status in TopicWorkspaceStatus}
        for topic in all_topics:
            key = str(topic.workspace_status)
            counts[key] = counts.get(key, 0) + 1
    return await _render(
        request,
        "topics.html",
        title="Themen",
        topics=rows,
        suggestions=accepted_suggestions,
        analysis=None,
        error=None,
        selected_status=TopicWorkspaceStatus.NEW.value,
        counts=counts,
    )


@router.post("/topics/analyze", response_class=HTMLResponse)
async def analyze_topic(request: Request) -> HTMLResponse:
    form = await request.form()
    title = str(form.get("title", "")).strip()
    question = str(form.get("question", title)).strip()
    async with _database(request).transaction() as session:
        analysis = await TopicAnalysisService().analyze(session, question)
        rows = list(
            await session.scalars(select(ContentTopic).order_by(ContentTopic.id.desc()))
        )
    analysis["title"] = title or question
    analysis["question"] = question
    return await _render(
        request,
        "topics.html",
        title="Themen",
        topics=rows,
        suggestions=None,
        analysis=analysis,
        error=None,
        selected_status=TopicWorkspaceStatus.NEW.value,
        counts={},
    )


@router.post("/topics/save", response_class=HTMLResponse)
async def save_topic_route(request: Request) -> RedirectResponse:
    form = await request.form()
    title = str(form.get("title", "Eigenes Thema")).strip()
    question = str(form.get("question", title)).strip()
    origin = (
        TopicOrigin.AI_SUGGESTED
        if form.get("origin") == TopicOrigin.AI_SUGGESTED.value
        else TopicOrigin.USER_CREATED
    )
    raw_status = str(form.get("workspace_status", "NEW")).upper()
    workspace_status = (
        raw_status
        if raw_status in {item.value for item in TopicWorkspaceStatus}
        else "NEW"
    )
    async with _database(request).transaction() as session:
        analysis = await TopicAnalysisService().analyze(session, question)
        topic = await save_topic(
            session,
            title=title,
            question=question,
            origin=origin,
            analysis=analysis,
            workspace_status=workspace_status,
        )
    return RedirectResponse(f"/topics/{topic.id}", status_code=303)


@router.post("/topics/{topic_id}/later")
async def defer_topic(request: Request, topic_id: UUID) -> Response:
    async with _database(request).transaction() as session:
        topic = await session.get(ContentTopic, topic_id)
        if topic is None:
            return HTMLResponse("Thema nicht gefunden", status_code=404)
        topic.workspace_status = TopicWorkspaceStatus.LATER
    return RedirectResponse("/topics?status=LATER", status_code=303)


@router.post("/topics/{topic_id}/archive")
async def archive_topic(request: Request, topic_id: UUID) -> Response:
    async with _database(request).transaction() as session:
        topic = await session.get(ContentTopic, topic_id)
        if topic is None:
            return HTMLResponse("Thema nicht gefunden", status_code=404)
        topic.workspace_status = TopicWorkspaceStatus.ARCHIVED
    return RedirectResponse("/topics?status=ARCHIVED", status_code=303)


@router.post("/topics/{topic_id}/restore")
async def restore_topic(request: Request, topic_id: UUID) -> Response:
    async with _database(request).transaction() as session:
        topic = await session.get(ContentTopic, topic_id)
        if topic is None:
            return HTMLResponse("Thema nicht gefunden", status_code=404)
        topic.workspace_status = TopicWorkspaceStatus.NEW
    return RedirectResponse("/topics?status=NEW", status_code=303)


@router.get("/topics/{topic_id}", response_class=HTMLResponse)
async def topic_detail(
    request: Request,
    topic_id: UUID,
    analysis: str | None = None,
) -> HTMLResponse:
    async with _database(request).transaction() as session:
        topic = await session.get(ContentTopic, topic_id)
        if topic is None:
            return HTMLResponse("Thema nicht gefunden", status_code=404)
        projects = list(
            await session.scalars(
                select(EditorialProject)
                .where(EditorialProject.content_topic_id == topic.id)
                .order_by(EditorialProject.created_at.desc())
            )
        )
    detail = topic_detail_view(topic)
    return await _render(
        request,
        "topic_detail.html",
        title=topic.title,
        topic=topic,
        editorial_projects=projects,
        analysis_feedback=analysis,
        **detail,
    )


@router.post("/topics/{topic_id}/use")
async def use_content_topic(request: Request, topic_id: UUID) -> RedirectResponse:
    form = await request.form()
    prompt = str(form.get("owner_prompt", "")).strip() or None
    raw_duration = str(form.get("target_duration_minutes", "")).strip()
    duration = int(raw_duration) if raw_duration.isdigit() else None
    try:
        project_id = await TopicStrategyService(_database(request)).use_content_topic(
            topic_id,
            owner_prompt=prompt,
            target_duration_minutes=duration,
        )
    except ValueError:
        return RedirectResponse(f"/topics/{topic_id}?production=error", status_code=303)
    async with _database(request).transaction() as session:
        topic = await session.get(ContentTopic, topic_id)
        if topic is not None:
            topic.workspace_status = TopicWorkspaceStatus.IN_PROGRESS
    return RedirectResponse(f"/workspace/{project_id}", status_code=303)


@router.post("/topics/{topic_id}/analyze", response_class=HTMLResponse)
async def refresh_topic_analysis(request: Request, topic_id: UUID) -> Response:
    async with _database(request).transaction() as session:
        topic = await session.get(ContentTopic, topic_id)
        if topic is None:
            return HTMLResponse("Thema nicht gefunden", status_code=404)
        try:
            analysis_result = await TopicAnalysisService().analyze(
                session, topic.human_question
            )
            topic.analysis_json = analysis_result
            primary = analysis_result.get("primary_concept_key")
            topic.primary_concept_key = primary if isinstance(primary, str) else None
        except Exception:
            logger.exception(
                "topic analysis refresh failed", extra={"topic_id": str(topic_id)}
            )
            return RedirectResponse(
                f"/topics/{topic_id}?analysis=error", status_code=303
            )
    return RedirectResponse(f"/topics/{topic_id}?analysis=updated", status_code=303)


@router.get("/strategy")
async def retired_strategy_tree() -> RedirectResponse:
    """Retire the former fixed tree without deleting historical references."""

    return RedirectResponse("/studio", status_code=303)


@router.post("/strategy/generate")
async def generate_strategy() -> RedirectResponse:
    """Never recreate the obsolete owner-facing strategy tree."""

    return RedirectResponse("/studio", status_code=303)


@router.post("/strategy/{strategy_id}/approve")
async def approve_strategy(request: Request, strategy_id: UUID) -> RedirectResponse:
    return RedirectResponse("/studio", status_code=303)


@router.get("/strategy/topics/{node_id}")
async def retired_strategy_topic(node_id: UUID) -> RedirectResponse:
    """Keep old URLs safe while removing the tree as a navigation surface."""

    return RedirectResponse("/studio", status_code=303)


@router.post("/strategy/topics/{node_id}/use")
async def use_strategy_topic(node_id: UUID) -> RedirectResponse:
    """Block new projects from obsolete fixed strategy topics."""

    return RedirectResponse("/studio", status_code=303)


@router.get("/workspace/{project_id}", response_class=HTMLResponse)
async def editorial_workspace(
    request: Request,
    project_id: UUID,
) -> HTMLResponse:
    """Read-only workspace for historical editorial projects.

    Lesson canon, lesson research, and Persian draft generation are retired;
    drafts, findings, and tracks remain viewable and maintainable.
    """

    async with _database(request).transaction() as session:
        project = await session.get(EditorialProject, project_id)
        if project is None:
            return HTMLResponse("Arbeitsbereich nicht gefunden", status_code=404)
        drafts = list(
            await session.scalars(
                select(PersianDraft)
                .where(PersianDraft.editorial_project_id == project.id)
                .order_by(PersianDraft.variant_index, PersianDraft.version_number)
            )
        )
        draft_ids = [draft.id for draft in drafts]
        finding_rows = (
            list(
                await session.scalars(
                    select(PersianReviewFinding)
                    .where(PersianReviewFinding.draft_id.in_(draft_ids))
                    .order_by(PersianReviewFinding.created_at)
                )
            )
            if draft_ids
            else []
        )
        review_findings: dict[UUID, list[PersianReviewFinding]] = {}
        for finding in finding_rows:
            review_findings.setdefault(finding.draft_id, []).append(finding)
        tracks = list(
            await session.scalars(
                select(EditorialLanguageTrack)
                .where(EditorialLanguageTrack.editorial_project_id == project.id)
                .order_by(
                    EditorialLanguageTrack.language,
                    EditorialLanguageTrack.version_number.desc(),
                )
            )
        )
        workspace_items = await load_library_items(session, status=None)
        workspace_item = next(
            (item for item in workspace_items if item.project.id == project.id), None
        )
        lesson_metadata = lesson_project_metadata(project)
        lesson_package = lesson_package_from_project(project)
        research_summary = await lesson_research_summary(session, project)
    return await _render(
        request,
        "editorial_workspace.html",
        title=project.title,
        project=project,
        drafts=drafts,
        tracks=tracks,
        lesson_metadata=lesson_metadata,
        lesson_package=lesson_package,
        research_summary=research_summary,
        review_findings=review_findings,
        studio_progress={
            "lesson": lesson_package is not None,
            "research": research_summary is not None,
            "package": bool(research_summary and research_summary.ready_for_writing),
            "persian": bool(drafts),
            "review": any(
                draft.provenance.get("review_completed") is True for draft in drafts
            ),
            "approval": any(draft.status == "PERSIAN_APPROVED" for draft in drafts),
        },
        project_status_label=(
            workspace_item.status_label if workspace_item else "In Arbeit"
        ),
    )


@router.get("/texts", response_class=HTMLResponse)
async def text_library(
    request: Request,
    q: str | None = None,
    status: str = "ACTIVE",
    origin: str | None = None,
    language: str | None = None,
    branch: str | None = None,
    sort: str = "updated",
) -> HTMLResponse:
    async with _database(request).transaction() as session:
        items = await load_library_items(
            session,
            query=q,
            status=status,
            origin=origin,
            language=language,
            branch=branch,
            sort=sort,
        )
        all_items = await load_library_items(session, status=None)
    return await _render(
        request,
        "texts.html",
        title="Texte",
        items=items,
        filters=library_filter_options(all_items),
        q=q or "",
        selected_status=status,
        selected_origin=origin or "",
        selected_language=language or "",
        selected_branch=branch or "",
        selected_sort=sort,
    )


@router.get("/texts/{project_id}", response_class=HTMLResponse)
async def text_detail(request: Request, project_id: UUID) -> HTMLResponse:
    async with _database(request).transaction() as session:
        items = await load_library_items(session, status=None)
        item = next(
            (candidate for candidate in items if candidate.project.id == project_id),
            None,
        )
        if item is None:
            return HTMLResponse("Text nicht gefunden", status_code=404)
        track_history = list(
            await session.scalars(
                select(EditorialLanguageTrack)
                .where(EditorialLanguageTrack.editorial_project_id == project_id)
                .order_by(
                    EditorialLanguageTrack.language,
                    EditorialLanguageTrack.version_number.desc(),
                )
            )
        )
        published_items = await load_library_items(session, status="PUBLISHED")
        related_published = [
            published
            for published in published_items
            if published.project.id != project_id
            and item.lesson is not None
            and published.lesson is not None
            and published.lesson.lesson_id == item.lesson.lesson_id
        ]
    return await _render(
        request,
        "text_detail.html",
        title=item.project.title,
        item=item,
        project=item.project,
        drafts=item.drafts,
        tracks=item.tracks,
        track_history=track_history,
        track_status_labels=TRACK_STATUS_LABELS,
        related_published=related_published,
    )


@router.post("/texts/{project_id}/duplicate")
async def duplicate_text(request: Request, project_id: UUID) -> RedirectResponse:
    async with _database(request).transaction() as session:
        project = await duplicate_project(session, project_id)
    return RedirectResponse(f"/workspace/{project.id}", status_code=303)


@router.post("/texts/{project_id}/archive")
async def archive_text(request: Request, project_id: UUID) -> RedirectResponse:
    async with _database(request).transaction() as session:
        await archive_project(session, project_id)
    return RedirectResponse("/texts", status_code=303)


@router.post("/texts/{project_id}/restore")
async def restore_text(request: Request, project_id: UUID) -> RedirectResponse:
    async with _database(request).transaction() as session:
        await restore_project(session, project_id)
    return RedirectResponse("/texts?status=ACTIVE", status_code=303)


@router.post("/texts/{project_id}/publish")
async def publish_text(request: Request, project_id: UUID) -> Response:
    try:
        async with _database(request).transaction() as session:
            await publish_project(session, project_id)
    except ValueError:
        return RedirectResponse(
            f"/texts/{project_id}?publication=approval-required", status_code=303
        )
    return RedirectResponse(f"/texts/{project_id}", status_code=303)


@router.get("/archive", response_class=HTMLResponse)
async def published_archive(request: Request) -> HTMLResponse:
    """Expose published-only channel memory without raw ledger tables."""

    async with _database(request).transaction() as session:
        items = await load_library_items(session, status="PUBLISHED")
    return await _render(
        request,
        "archive.html",
        title="Archiv",
        items=items,
    )


@router.get("/texts/{project_id}/export")
async def export_text(request: Request, project_id: UUID) -> Response:
    async with _database(request).transaction() as session:
        items = await load_library_items(session, status=None)
        item = next(
            (candidate for candidate in items if candidate.project.id == project_id),
            None,
        )
        if item is None:
            return HTMLResponse("Text nicht gefunden", status_code=404)
        payload: dict[str, object] = {
            "project_id": str(item.project.id),
            "title": item.project.title,
            "human_question": item.project.human_question,
            "origin": item.origin_key,
            "strategy_node_id": str(item.strategy_node.id)
            if item.strategy_node
            else None,
            "strategy_topic_snapshot": item.project.strategy_topic_snapshot,
            "content_topic_id": str(item.topic.id) if item.topic else None,
            "target_duration_minutes": item.project.target_duration_minutes,
            "status": item.status_key,
            "languages": {
                language: {
                    "display_text": track.display_text,
                    "voice_ready_text": track.voice_ready_text,
                    "elevenlabs_performance_text": track.elevenlabs_performance_text,
                    "status": track.status,
                    "version": track.version_number,
                    "word_count": track.actual_word_count,
                    "estimated_duration_seconds": track.estimated_duration_seconds,
                    "provenance": track.provenance,
                }
                for language, track in item.tracks.items()
            },
            "persian_versions": [
                {
                    "id": str(draft.id),
                    "version": draft.version_number,
                    "status": draft.status,
                    "text": draft.text,
                    "created_at": draft.created_at.isoformat(),
                }
                for draft in item.drafts
            ],
        }
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="text-{project_id}.json"'
        },
    )


@router.post("/workspace/{project_id}/persian/drafts/{draft_id}/edit")
async def edit_persian_draft(
    request: Request, project_id: UUID, draft_id: UUID
) -> RedirectResponse:
    form = await request.form()
    await PersianEditorialService(_database(request)).edit(
        draft_id, str(form.get("text", ""))
    )
    return RedirectResponse(f"/workspace/{project_id}", status_code=303)


@router.post("/workspace/{project_id}/persian/drafts/{draft_id}/review")
async def review_persian_draft(
    request: Request, project_id: UUID, draft_id: UUID
) -> RedirectResponse:
    await PersianEditorialService(_database(request)).review(draft_id)
    return RedirectResponse(f"/workspace/{project_id}", status_code=303)


@router.post("/workspace/{project_id}/persian/drafts/{draft_id}/approve")
async def approve_persian_draft(
    request: Request, project_id: UUID, draft_id: UUID
) -> RedirectResponse:
    await PersianEditorialService(_database(request)).approve(draft_id)
    return RedirectResponse(f"/workspace/{project_id}", status_code=303)


@router.post("/workspace/{project_id}/translations")
async def create_translations(request: Request, project_id: UUID) -> RedirectResponse:
    form = await request.form()
    draft_id = UUID(str(form.get("draft_id")))
    raw_languages = form.getlist("languages")
    languages = tuple(str(item) for item in raw_languages) or ("fa", "de", "en", "ar")
    service = MultilingualEditorialService(_database(request))
    await service.create(draft_id, languages, expected_project_id=project_id)
    return RedirectResponse(f"/workspace/{project_id}", status_code=303)


@router.post("/workspace/{project_id}/tracks/{track_id}/voice")
async def prepare_track_voice(
    request: Request, project_id: UUID, track_id: UUID
) -> RedirectResponse:
    await MultilingualEditorialService(_database(request)).prepare_voice(
        track_id, expected_project_id=project_id
    )
    return RedirectResponse(f"/workspace/{project_id}", status_code=303)


@router.post("/workspace/{project_id}/tracks/{track_id}/performance")
async def prepare_track_performance(
    request: Request, project_id: UUID, track_id: UUID
) -> RedirectResponse:
    await MultilingualEditorialService(_database(request)).prepare_performance(
        track_id, expected_project_id=project_id
    )
    return RedirectResponse(f"/workspace/{project_id}", status_code=303)


@router.get("/studio/voice", response_class=HTMLResponse)
async def studio_voice(request: Request) -> HTMLResponse:
    return await _render(
        request,
        "studio_voice.html",
        title="Text für Voice vorbereiten",
        result=None,
        error=None,
    )


@router.post("/studio/voice", response_class=HTMLResponse)
async def studio_voice_prepare(request: Request) -> HTMLResponse:
    form = await request.form()
    language = str(form.get("language", "fa"))
    text = str(form.get("text", ""))
    if language not in LANGUAGES or not text.strip():
        return await _render(
            request,
            "studio_voice.html",
            title="Text für Voice vorbereiten",
            result=None,
            error="Sprache und Text sind erforderlich.",
        )
    publication_language = PublicationLanguage(language)
    async with _database(request).transaction() as session:
        lexicon = await load_approved_lexicon(session, publication_language)
    result = prepare_pronunciation(
        publication_language,
        text,
        lexicon.entries,
        lexicon_version=lexicon.version,
        provider_profile=DEFAULT_PROVIDER_PROFILE,
    )
    return await _render(
        request,
        "studio_voice.html",
        title="Text für Voice vorbereiten",
        result=result,
        error=None,
    )


async def _render_lexicon(
    request: Request,
    *,
    language: str = "",
    status: str = "",
    error: str | None = None,
    preview: PronunciationPreparation | None = None,
    preview_language: str = "fa",
    preview_text: str = "",
) -> HTMLResponse:
    service = PronunciationLexiconService(_database(request))
    try:
        entries = await service.entries(
            language=language or None, status=status or None
        )
        filter_error = None
    except ValueError:
        entries, filter_error = [], "Ungültige Filterauswahl."
    return await _render(
        request,
        "lexicon.html",
        title="Aussprache-Lexikon",
        entries=entries,
        languages=LANGUAGES,
        status_labels=STATUS_LABELS,
        criticality_labels=CRITICALITY_LABELS,
        selected_language=language,
        selected_status=status,
        error=error or filter_error,
        preview=preview,
        preview_language=preview_language,
        preview_text=preview_text,
    )


@router.get("/lexicon", response_class=HTMLResponse)
async def lexicon(
    request: Request, language: str = "", status: str = ""
) -> HTMLResponse:
    return await _render_lexicon(request, language=language, status=status)


@router.post("/lexicon", response_class=HTMLResponse)
async def propose_lexicon_entry(request: Request) -> Response:
    form = await request.form()
    try:
        await PronunciationLexiconService(_database(request)).propose(
            language=str(form.get("language", "")),
            written_form=str(form.get("written_form", "")),
            preferred_pronunciation=str(form.get("preferred_pronunciation", "")),
            transliteration=str(form.get("transliteration", "")),
            ipa=str(form.get("ipa", "")),
            provider_form=str(form.get("provider_form", "")),
            criticality=str(form.get("criticality", "IMPORTANT")),
            notes=str(form.get("notes", "")),
        )
    except ValueError as exc:
        return await _render_lexicon(request, error=str(exc))
    return RedirectResponse("/lexicon", status_code=303)


@router.post("/lexicon/preview", response_class=HTMLResponse)
async def lexicon_preview(request: Request) -> HTMLResponse:
    form = await request.form()
    language = str(form.get("language", "fa"))
    text = str(form.get("text", ""))
    if language not in LANGUAGES or not text.strip():
        return await _render_lexicon(
            request,
            error="Sprache und Text sind erforderlich.",
            preview_language=language,
            preview_text=text,
        )
    publication_language = PublicationLanguage(language)
    async with _database(request).transaction() as session:
        approved = await load_approved_lexicon(session, publication_language)
    result = prepare_pronunciation(
        publication_language,
        text,
        approved.entries,
        lexicon_version=approved.version,
        provider_profile=DEFAULT_PROVIDER_PROFILE,
    )
    return await _render_lexicon(
        request,
        preview=result,
        preview_language=language,
        preview_text=text,
    )


@router.post("/lexicon/{entry_id}/approve")
async def approve_lexicon_entry(request: Request, entry_id: UUID) -> Response:
    form = await request.form()
    try:
        await PronunciationLexiconService(_database(request)).approve(
            entry_id, notes=str(form.get("notes", ""))
        )
    except ValueError:
        return HTMLResponse("Lexikon-Eintrag nicht freigebbar", status_code=400)
    return RedirectResponse("/lexicon", status_code=303)


@router.post("/lexicon/{entry_id}/deprecate")
async def deprecate_lexicon_entry(request: Request, entry_id: UUID) -> Response:
    form = await request.form()
    try:
        await PronunciationLexiconService(_database(request)).deprecate(
            entry_id, notes=str(form.get("notes", ""))
        )
    except ValueError:
        return HTMLResponse("Lexikon-Eintrag nicht verwerfbar", status_code=400)
    return RedirectResponse("/lexicon", status_code=303)


@router.get("/channels", response_class=HTMLResponse)
async def channels(request: Request) -> HTMLResponse:
    async with _database(request).transaction() as session:
        rows = list(
            await session.scalars(
                select(MonitoredChannel).order_by(MonitoredChannel.name)
            )
        )
        counts = dict(
            (
                channel_id,
                count,
            )
            for channel_id, count in (
                await session.execute(
                    select(
                        ChannelVideoCandidate.channel_id,
                        func.count(ChannelVideoCandidate.id),
                    )
                    .where(ChannelVideoCandidate.status == CandidateStatus.NEW)
                    .group_by(ChannelVideoCandidate.channel_id)
                )
            ).all()
        )
    return await _render(
        request,
        "channels.html",
        title="Kanäle",
        channels=rows,
        pending_counts=counts,
        error=None,
    )


@router.get("/channels/new", response_class=HTMLResponse)
async def channel_form(request: Request) -> HTMLResponse:
    return await _render(
        request, "channel_new.html", title="Kanal hinzufügen", error=None
    )


@router.post("/channels", response_class=HTMLResponse)
async def add_channel(request: Request) -> Response:
    form = await request.form()
    locator = str(form.get("url", "")).strip()
    try:
        channel = await ChannelDiscoveryService(_database(request)).register(locator)
    except ValueError as exc:
        return await _render(
            request, "channel_new.html", title="Kanal hinzufügen", error=str(exc)
        )
    except Exception:
        return await _render(
            request,
            "channel_new.html",
            title="Kanal hinzufügen",
            error="Der YouTube-Kanal konnte nicht aufgelöst werden.",
        )
    return RedirectResponse(f"/channels/{channel.id}", status_code=303)


@router.get("/channels/{channel_id}", response_class=HTMLResponse)
async def channel_detail(request: Request, channel_id: UUID) -> HTMLResponse:
    service = ChannelDiscoveryService(_database(request))
    async with _database(request).transaction() as session:
        channel = await session.get(MonitoredChannel, channel_id)
    if channel is None:
        return HTMLResponse("Kanal nicht gefunden", status_code=404)
    candidates = await service.candidates(channel_id)
    grouped = {
        status.value: [item for item in candidates if item.status == status]
        for status in CandidateStatus
    }
    return await _render(
        request,
        "channel_detail.html",
        title=channel.name,
        channel=channel,
        grouped=grouped,
        results=None,
        error=None,
    )


@router.post("/channels/{channel_id}/check", response_class=HTMLResponse)
async def check_channel(request: Request, channel_id: UUID) -> Response:
    try:
        await ChannelDiscoveryService(_database(request)).discover(channel_id)
    except ValueError:
        return HTMLResponse("Kanal nicht gefunden", status_code=404)
    except Exception:
        return RedirectResponse(f"/channels/{channel_id}?error=check", status_code=303)
    return RedirectResponse(f"/channels/{channel_id}", status_code=303)


@router.post("/channels/{channel_id}/import", response_class=HTMLResponse)
async def import_channel_candidates(request: Request, channel_id: UUID) -> Response:
    form = await request.form()
    ignored = form.get("ignore_candidate")
    if ignored is not None:
        try:
            await ChannelDiscoveryService(_database(request)).ignore(
                channel_id, UUID(str(ignored))
            )
        except ValueError:
            return HTMLResponse("Ungültige Videoauswahl", status_code=400)
        return RedirectResponse(f"/channels/{channel_id}", status_code=303)
    raw_ids = form.getlist("candidate_ids")
    try:
        candidate_ids = [UUID(str(value)) for value in raw_ids]
    except ValueError:
        return HTMLResponse("Ungültige Videoauswahl", status_code=400)
    results = await ChannelDiscoveryService(_database(request)).import_selected(
        channel_id, candidate_ids
    )
    service = ChannelDiscoveryService(_database(request))
    async with _database(request).transaction() as session:
        channel = await session.get(MonitoredChannel, channel_id)
    if channel is None:
        return HTMLResponse("Kanal nicht gefunden", status_code=404)
    candidates = await service.candidates(channel_id)
    grouped = {
        status.value: [item for item in candidates if item.status == status]
        for status in CandidateStatus
    }
    return await _render(
        request,
        "channel_detail.html",
        title=channel.name,
        channel=channel,
        grouped=grouped,
        results=results,
        error=None,
    )


@router.post("/channels/{channel_id}/candidates/{candidate_id}/ignore")
async def ignore_channel_candidate(
    request: Request, channel_id: UUID, candidate_id: UUID
) -> RedirectResponse:
    await ChannelDiscoveryService(_database(request)).ignore(channel_id, candidate_id)
    return RedirectResponse(f"/channels/{channel_id}", status_code=303)


@router.post("/channels/{channel_id}/delete")
async def delete_channel(request: Request, channel_id: UUID) -> Response:
    deleted = await ChannelDiscoveryService(_database(request)).delete_channel(
        channel_id
    )
    if not deleted:
        return HTMLResponse("Kanal nicht gefunden", status_code=404)
    return RedirectResponse("/channels", status_code=303)


@router.post("/channels/check-all", response_class=HTMLResponse)
async def check_all_channels(request: Request) -> HTMLResponse:
    service = ChannelDiscoveryService(_database(request))
    channels_to_check = await service.active_channels()
    for channel in channels_to_check:
        try:
            await service.discover(channel.id)
        except Exception:
            continue
    async with _database(request).transaction() as session:
        candidates = list(
            await session.scalars(
                select(ChannelVideoCandidate).where(
                    ChannelVideoCandidate.status == CandidateStatus.NEW
                )
            )
        )
        rows = {channel.id: channel for channel in channels_to_check}
    return await _render(
        request,
        "channel_candidates.html",
        title="Neue Videos",
        candidates=candidates,
        channels=rows,
        error=None,
    )


@router.post("/channels/check-all/import", response_class=HTMLResponse)
async def import_all_channel_candidates(request: Request) -> Response:
    form = await request.form()
    try:
        selected = [UUID(str(value)) for value in form.getlist("candidate_ids")]
    except ValueError:
        return HTMLResponse("Ungültige Videoauswahl", status_code=400)
    async with _database(request).transaction() as session:
        rows = list(
            await session.scalars(
                select(ChannelVideoCandidate).where(
                    ChannelVideoCandidate.id.in_(selected),
                    ChannelVideoCandidate.status == CandidateStatus.NEW,
                )
            )
        )
    grouped_ids: dict[UUID, list[UUID]] = {}
    for candidate in rows:
        grouped_ids.setdefault(candidate.channel_id, []).append(candidate.id)
    service = ChannelDiscoveryService(_database(request))
    for channel_id, candidate_ids in grouped_ids.items():
        await service.import_selected(channel_id, candidate_ids)
    return RedirectResponse("/channels", status_code=303)
