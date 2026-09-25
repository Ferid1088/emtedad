"""German-first owner routes for sources, knowledge, and topic discovery."""

import json
import logging
from pathlib import Path
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channel_monitoring.domain import CandidateStatus
from app.channel_monitoring.models import ChannelVideoCandidate, MonitoredChannel
from app.channel_monitoring.service import ChannelDiscoveryService
from app.content_strategy.domain import TopicOrigin, TopicWorkspaceStatus
from app.content_strategy.lesson_canon import LessonCanonRepository
from app.content_strategy.lesson_catalog import (
    filter_lesson_catalog,
    load_lesson_catalog,
)
from app.content_strategy.lesson_research import (
    LessonResearchService,
    lesson_research_summary,
)
from app.content_strategy.lesson_workflow import (
    create_lesson_project,
    lesson_package_from_project,
    lesson_project_metadata,
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
from app.core.ayin.models import CanonDocument
from app.db.session import Database
from app.knowledge.adapters.youtube import YouTubeAdapter
from app.knowledge.llm.codex import CodexCliProvider, CodexProviderError
from app.knowledge.models import (
    ExternalClaim,
    Mention,
    Person,
    ReviewFlag,
    Source,
    SourceSegment,
    SourceVersion,
    Work,
)
from app.lecture.domain import MasterStatus
from app.lecture.models import LectureMasterVersion
from app.retrieval.domain import BuildStatus, QueryLanguage
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.models import EmbeddingRun
from app.semantic_content.generation import AutomatedContentService
from app.semantic_content.ingestion import SemanticKnowledgePipeline
from app.semantic_content.models import (
    GeneratedContentProject,
    PreferredSemanticStructureRun,
    SemanticNode,
    SemanticStructureRun,
)
from app.semantic_content.schemas import (
    GenerateContentRequest,
    SemanticStructureRequest,
)
from app.semantic_content.structuring import SemanticStructureService
from app.topic_discovery import (
    TopicAnalysisService,
    TopicSuggestionService,
    dashboard_counts,
    save_topic,
    topic_detail_view,
    validate_youtube_url,
)
from app.web.service import TopicSuggestion

router = APIRouter(tags=["owner-web"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
logger = logging.getLogger(__name__)


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def _embedding_provider(request: Request) -> EmbeddingProvider:
    return cast(EmbeddingProvider, request.app.state.embedding_provider)


def _channel_service(request: Request) -> ChannelDiscoveryService:
    return ChannelDiscoveryService(
        _database(request),
        embedding_provider=_embedding_provider(request),
    )


async def _latest_content_index(session: AsyncSession) -> EmbeddingRun | None:
    return cast(
        EmbeddingRun | None,
        await session.scalar(
            select(EmbeddingRun)
            .where(EmbeddingRun.status == BuildStatus.SUCCEEDED)
            .order_by(EmbeddingRun.completed_at.desc(), EmbeddingRun.created_at.desc())
            .limit(1)
        ),
    )


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
        lesson_progress = None
        lesson_health = None
        try:
            lesson_repository = LessonCanonRepository()
            _, lesson_progress = await load_lesson_catalog(session, lesson_repository)
            lesson_health = {
                "lessons": lesson_repository.lesson_count,
                "relations": lesson_repository.relation_count,
                "concepts": len(lesson_repository.core_concepts()),
            }
        except (FileNotFoundError, ValueError):
            logger.exception("lesson canon unavailable for dashboard")
    return await _render(
        request,
        "dashboard.html",
        title="Dashboard",
        counts=counts,
        sources=sources,
        topics=topics,
        pending_channels=pending_channels,
        lesson_progress=lesson_progress,
        lesson_health=lesson_health,
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


async def _structure_page_rows(request: Request) -> list[dict[str, object]]:
    """Build one row per source using its newest immutable transcript version."""

    async with _database(request).transaction() as session:
        sources = list(
            await session.scalars(select(Source).order_by(Source.created_at.desc()))
        )
        versions = list(
            await session.scalars(
                select(SourceVersion).order_by(
                    SourceVersion.source_id,
                    SourceVersion.acquired_at.desc(),
                    SourceVersion.created_at.desc(),
                )
            )
        )
        latest_by_source: dict[UUID, SourceVersion] = {}
        for version in versions:
            latest_by_source.setdefault(version.source_id, version)
        version_ids = [version.id for version in latest_by_source.values()]
        pointers: dict[UUID, PreferredSemanticStructureRun] = {}
        latest_runs: dict[UUID, SemanticStructureRun] = {}
        if version_ids:
            for pointer in await session.scalars(
                select(PreferredSemanticStructureRun).where(
                    PreferredSemanticStructureRun.source_version_id.in_(version_ids)
                )
            ):
                pointers[pointer.source_version_id] = pointer
            runs = list(
                await session.scalars(
                    select(SemanticStructureRun)
                    .where(SemanticStructureRun.source_version_id.in_(version_ids))
                    .order_by(
                        SemanticStructureRun.source_version_id,
                        SemanticStructureRun.created_at.desc(),
                    )
                )
            )
            for run in runs:
                latest_runs.setdefault(run.source_version_id, run)

        rows: list[dict[str, object]] = []
        for source in sources:
            version = latest_by_source.get(source.id)
            if version is None:
                continue
            pointer = pointers.get(version.id)
            run = latest_runs.get(version.id)
            rows.append(
                {
                    "source": source,
                    "version": version,
                    "preferred": pointer is not None,
                    "run": run,
                }
            )
        return rows


@router.get("/structures", response_class=HTMLResponse)
@router.get("/vortragsstruktur", response_class=HTMLResponse)
async def semantic_structures(
    request: Request,
    failed: str | None = None,
    created: str | None = None,
    batch: str | None = None,
) -> HTMLResponse:
    return await _render(
        request,
        "semantic_structures.html",
        title="Vortragsstruktur",
        rows=await _structure_page_rows(request),
        failed=failed,
        created=created,
        batch=batch,
    )


@router.post("/structures/{source_version_id}")
async def build_semantic_structure_from_ui(
    request: Request,
    source_version_id: UUID,
) -> RedirectResponse:
    try:
        await SemanticStructureService(
            _database(request),
            CodexCliProvider(),
        ).build(
            source_version_id,
            SemanticStructureRequest(),
        )
    except (CodexProviderError, ValueError):
        logger.exception(
            "semantic_structure.ui_build_failed",
            extra={"source_version_id": str(source_version_id)},
        )
        return RedirectResponse(
            f"/structures?failed={source_version_id}",
            status_code=303,
        )
    except Exception:
        logger.exception(
            "semantic_structure.ui_unexpected_failure",
            extra={"source_version_id": str(source_version_id)},
        )
        return RedirectResponse(
            f"/structures?failed={source_version_id}",
            status_code=303,
        )
    return RedirectResponse(
        f"/structures?created={source_version_id}",
        status_code=303,
    )


@router.post("/structures/build-missing")
async def build_missing_semantic_structures(request: Request) -> RedirectResponse:
    try:
        result = await SemanticKnowledgePipeline(
            _database(request),
            YouTubeAdapter(),
            CodexCliProvider(),
            _embedding_provider(request),
        ).backfill_existing()
    except Exception:
        logger.exception("semantic_structure.backfill_failed")
        return RedirectResponse("/structures?batch=failed", status_code=303)
    state = (
        "ok"
        if not result.failed_source_version_ids
        else f"partial-{len(result.failed_source_version_ids)}"
    )
    return RedirectResponse(f"/structures?batch={state}", status_code=303)


@router.get("/sources/new", response_class=HTMLResponse)
async def source_form(request: Request) -> HTMLResponse:
    return await _render(
        request, "source_new.html", title="Quelle hinzufügen", error=None
    )


@router.post("/sources", response_class=HTMLResponse)
async def add_source(request: Request) -> Response:
    form = await request.form()
    locator = str(form.get("url", "")).strip()
    try:
        validate_youtube_url(locator)
        result = await SemanticKnowledgePipeline(
            _database(request),
            YouTubeAdapter(),
            CodexCliProvider(),
            _embedding_provider(request),
        ).ingest(locator)
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
    return RedirectResponse(
        f"/sources/{result.source_id}?prepared=1",
        status_code=303,
    )


@router.get("/sources/{source_id}", response_class=HTMLResponse)
async def source_detail(
    request: Request,
    source_id: UUID,
    prepared: str | None = None,
) -> HTMLResponse:
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
        semantic_nodes: list[SemanticNode] = []
        if versions:
            preferred = await session.get(
                PreferredSemanticStructureRun, versions[0].id
            )
            if preferred is not None:
                semantic_nodes = list(
                    await session.scalars(
                        select(SemanticNode)
                        .where(
                            SemanticNode.semantic_structure_run_id
                            == preferred.semantic_structure_run_id
                        )
                        .order_by(SemanticNode.ordinal)
                    )
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
        semantic_nodes=semantic_nodes,
        prepared=prepared == "1",
    )


@router.get("/knowledge", response_class=HTMLResponse)
async def knowledge(request: Request, section: str = "sources") -> HTMLResponse:
    async with _database(request).transaction() as session:
        data: object
        if section == "script_archive":
            data = await load_library_items(session, status="PUBLISHED")
        elif section == "ayin_source":
            data = list(
                await session.scalars(
                    select(CanonDocument).order_by(CanonDocument.created_at.desc())
                )
            )
        elif section == "people":
            data = list(
                await session.scalars(select(Person).order_by(Person.canonical_name))
            )
        elif section == "works":
            data = list(
                await session.scalars(select(Work).order_by(Work.canonical_title))
            )
        elif section == "claims":
            data = list(
                await session.scalars(
                    select(ExternalClaim).order_by(ExternalClaim.created_at.desc())
                )
            )
        elif section == "references":
            data = list(
                await session.scalars(
                    select(Mention).order_by(Mention.created_at.desc())
                )
            )
        elif section == "review":
            data = list(
                await session.scalars(
                    select(ReviewFlag).order_by(
                        ReviewFlag.status, ReviewFlag.created_at
                    )
                )
            )
        else:
            data = list(
                await session.scalars(select(Source).order_by(Source.created_at.desc()))
            )
    return await _render(
        request,
        "knowledge.html",
        title="Wissensbasis",
        section=section,
        data=data,
        ayin_zone_labels={
            "AYIN_CANON": "Ayin-Kanon",
            "AYIN_WORKING": "Ayin-Arbeitsstand",
        },
    )


@router.get("/lessons", response_class=HTMLResponse)
async def lessons(
    request: Request,
    q: str = "",
    status: str = "",
    concept: str = "",
    prerequisites: str = "ALL",
    number_from: str = "",
    number_to: str = "",
) -> HTMLResponse:
    """Render the approved lesson canon as the long-term editorial map."""

    try:
        repository = LessonCanonRepository()
        async with _database(request).transaction() as session:
            catalog, progress = await load_lesson_catalog(session, repository)
        filtered = filter_lesson_catalog(
            catalog,
            query=q,
            status=status,
            concept=concept,
            prerequisites=prerequisites,
            number_from=_optional_int(number_from),
            number_to=_optional_int(number_to),
        )
        health = {
            "lessons": repository.lesson_count,
            "relations": repository.relation_count,
            "concepts": len(repository.core_concepts()),
        }
        core_concepts = repository.core_concepts()
        error = None
    except (FileNotFoundError, ValueError) as exc:
        logger.exception("lesson canon unavailable")
        filtered = []
        progress = None
        health = None
        core_concepts = []
        error = str(exc)
    return await _render(
        request,
        "lessons.html",
        title="Lektionen",
        lessons=filtered,
        progress=progress,
        health=health,
        core_concepts=core_concepts,
        error=error,
        q=q,
        selected_status=status,
        selected_concept=concept,
        selected_prerequisites=prerequisites,
        number_from=number_from,
        number_to=number_to,
    )


@router.get("/lessons/concepts", response_class=HTMLResponse)
async def lesson_concepts(request: Request) -> HTMLResponse:
    try:
        repository = LessonCanonRepository()
        concepts = repository.core_concepts()
        error = None
    except (FileNotFoundError, ValueError) as exc:
        logger.exception("lesson core concepts unavailable")
        concepts = []
        error = str(exc)
    return await _render(
        request,
        "lesson_concepts.html",
        title="Kernbegriffe",
        concepts=concepts,
        error=error,
    )


@router.get("/lessons/{lesson_id}", response_class=HTMLResponse)
async def lesson_detail(request: Request, lesson_id: str) -> HTMLResponse:
    try:
        repository = LessonCanonRepository()
        package = repository.package(lesson_id)
    except ValueError:
        return HTMLResponse("Lektion nicht gefunden", status_code=404)
    except FileNotFoundError:
        return HTMLResponse("Lektionskanon nicht importiert", status_code=503)

    summaries = {item.lesson_id: item for item in repository.summaries()}
    prerequisites_view = [
        {
            "lesson": summaries[relation.to_lesson_id],
            "number": repository.ordinal(relation.to_lesson_id),
            "explanation": relation.explanation_fa,
        }
        for relation in repository.outgoing_relations(lesson_id)
        if relation.is_prerequisite
    ]
    prepares_view = [
        {
            "lesson": summaries[relation.from_lesson_id],
            "number": repository.ordinal(relation.from_lesson_id),
            "explanation": relation.explanation_fa,
        }
        for relation in repository.incoming_relations(lesson_id)
        if relation.is_prerequisite
    ]
    related: dict[str, dict[str, object]] = {}
    for relation in repository.outgoing_relations(lesson_id):
        if not relation.is_prerequisite:
            related[relation.to_lesson_id] = {
                "lesson": summaries[relation.to_lesson_id],
                "number": repository.ordinal(relation.to_lesson_id),
                "explanation": relation.explanation_fa,
            }
    for relation in repository.incoming_relations(lesson_id):
        if not relation.is_prerequisite:
            related.setdefault(
                relation.from_lesson_id,
                {
                    "lesson": summaries[relation.from_lesson_id],
                    "number": repository.ordinal(relation.from_lesson_id),
                    "explanation": relation.explanation_fa,
                },
            )

    async with _database(request).transaction() as session:
        catalog, _ = await load_lesson_catalog(session, repository)
        item = next(entry for entry in catalog if entry.package.lesson_id == lesson_id)
        projects = [
            entry
            for entry in await load_library_items(session, status=None)
            if entry.lesson is not None and entry.lesson.lesson_id == lesson_id
        ]
    return await _render(
        request,
        "lesson_detail.html",
        title=package.canonical_lesson_title,
        item=item,
        package=package,
        projects=projects,
        prerequisites_view=prerequisites_view,
        prepares_view=prepares_view,
        related_view=list(related.values()),
    )


@router.post("/lessons/{lesson_id}/projects")
async def start_lesson_project(request: Request, lesson_id: str) -> Response:
    form = await request.form()
    owner_prompt = str(form.get("owner_prompt", "")).strip() or None
    raw_duration = str(form.get("target_duration_minutes", "")).strip()
    duration = int(raw_duration) if raw_duration.isdigit() else None
    try:
        repository = LessonCanonRepository()
        async with _database(request).transaction() as session:
            project = await create_lesson_project(
                session,
                repository,
                lesson_id,
                owner_prompt=owner_prompt,
                target_duration_minutes=duration,
            )
    except ValueError:
        return HTMLResponse("Lektion nicht gefunden", status_code=404)
    return RedirectResponse(f"/workspace/{project.id}", status_code=303)


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

    return RedirectResponse("/lessons", status_code=303)


@router.post("/strategy/generate")
async def generate_strategy() -> RedirectResponse:
    """Never recreate the obsolete owner-facing strategy tree."""

    return RedirectResponse("/lessons", status_code=303)


@router.post("/strategy/{strategy_id}/approve")
async def approve_strategy(request: Request, strategy_id: UUID) -> RedirectResponse:
    return RedirectResponse("/lessons", status_code=303)


@router.get("/strategy/topics/{node_id}")
async def retired_strategy_topic(node_id: UUID) -> RedirectResponse:
    """Keep old URLs safe while removing the tree as a navigation surface."""

    return RedirectResponse("/lessons", status_code=303)


@router.post("/strategy/topics/{node_id}/use")
async def use_strategy_topic(node_id: UUID) -> RedirectResponse:
    """Block new projects from obsolete fixed strategy topics."""

    return RedirectResponse("/lessons", status_code=303)


@router.get("/workspace/{project_id}", response_class=HTMLResponse)
async def editorial_workspace(
    request: Request,
    project_id: UUID,
    research: str | None = None,
) -> HTMLResponse:
    try:
        lesson_canon = LessonCanonRepository()
        lesson_summaries = lesson_canon.summaries()
    except (FileNotFoundError, ValueError):
        lesson_summaries = []
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
        if lesson_metadata is not None:
            masters = (
                list(
                    await session.scalars(
                        select(LectureMasterVersion).where(
                            LectureMasterVersion.id == project.semantic_master_id,
                            LectureMasterVersion.research_package_id
                            == project.research_package_id,
                            LectureMasterVersion.status == MasterStatus.READY,
                        )
                    )
                )
                if research_summary is not None
                and research_summary.ready_for_writing
                and project.semantic_master_id is not None
                and project.research_package_id is not None
                else []
            )
        else:
            masters = list(
                await session.scalars(
                    select(LectureMasterVersion)
                    .where(LectureMasterVersion.status == MasterStatus.READY)
                    .order_by(LectureMasterVersion.created_at.desc())
                )
            )
    research_messages = {
        "ready": "Die externe Recherche ist eingefroren und bereit für den Entwurf.",
        "empty": (
            "Die Recherche wurde ausgeführt, fand aber keine passenden externen "
            "Treffer. Der Kanon wurde nicht mit erfundenem Material ergänzt."
        ),
        "review": (
            "Externe Treffer wurden gespeichert, der Semantic Master benötigt "
            "jedoch eine Prüfung."
        ),
        "missing-index": (
            "Die externe Wissensbasis ist noch nicht suchbereit. Bitte Quellen "
            "zuerst indexieren."
        ),
        "invalid": "Diese Recherche kann für das Projekt nicht gestartet werden.",
        "failed": (
            "Die externe Recherche konnte nicht abgeschlossen werden. "
            "Die vorhandenen Projektdaten blieben unverändert."
        ),
    }
    return await _render(
        request,
        "editorial_workspace.html",
        title=project.title,
        project=project,
        drafts=drafts,
        tracks=tracks,
        masters=masters,
        lessons=lesson_summaries,
        lesson_metadata=lesson_metadata,
        lesson_package=lesson_package,
        research_summary=research_summary,
        research_message=research_messages.get(research or ""),
        research_message_is_error=research in {"missing-index", "invalid", "failed"},
        review_findings=review_findings,
        studio_progress={
            "lesson": lesson_package is not None,
            "research": research_summary is not None,
            "package": bool(
                research_summary and research_summary.ready_for_writing
            ),
            "persian": bool(drafts),
            "review": any(
                draft.provenance.get("review_completed") is True for draft in drafts
            ),
            "approval": any(
                draft.status == "PERSIAN_APPROVED" for draft in drafts
            ),
        },
        project_status_label=(
            workspace_item.status_label if workspace_item else "In Arbeit"
        ),
    )


@router.post("/workspace/{project_id}/research")
async def run_lesson_research(request: Request, project_id: UUID) -> RedirectResponse:
    """Create the lesson-scoped external package before any script generation."""

    form = await request.form()
    owner_focus = str(form.get("owner_focus", "")).strip() or None
    provider = cast(EmbeddingProvider, request.app.state.embedding_provider)
    try:
        result = await LessonResearchService(_database(request), provider).run(
            project_id, owner_focus=owner_focus
        )
    except ValueError as exc:
        logger.warning(
            "lesson_research.rejected",
            extra={"project_id": str(project_id), "reason": str(exc)},
        )
        code = (
            "missing-index"
            if "Wissensindex" in str(exc) or "indexiert" in str(exc)
            else "invalid"
        )
        return RedirectResponse(
            f"/workspace/{project_id}?research={code}", status_code=303
        )
    except Exception:
        logger.exception(
            "lesson_research.failed", extra={"project_id": str(project_id)}
        )
        return RedirectResponse(
            f"/workspace/{project_id}?research=failed", status_code=303
        )
    state = (
        "ready"
        if result.ready_for_writing
        else "empty"
        if result.result_count == 0
        else "review"
    )
    return RedirectResponse(
        f"/workspace/{project_id}?research={state}", status_code=303
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


@router.post("/workspace/{project_id}/persian/drafts")
async def generate_persian_drafts(
    request: Request, project_id: UUID
) -> RedirectResponse:
    form = await request.form()
    master_id = UUID(str(form.get("semantic_master_id")))
    lesson_id = str(form.get("lesson_id", "")).strip()
    target = int(str(form.get("target_duration_minutes", "15")))
    count = int(str(form.get("draft_count", "1")))
    prompt = str(form.get("owner_prompt", "")).strip() or None
    await PersianEditorialService(_database(request)).generate(
        project_id,
        master_id,
        lesson_id=lesson_id,
        target_minutes=target,
        draft_count=count,
        owner_prompt=prompt,
    )
    return RedirectResponse(f"/workspace/{project_id}", status_code=303)


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


@router.get("/studio", response_class=HTMLResponse)
async def studio(request: Request) -> HTMLResponse:
    async with _database(request).transaction() as session:
        items = await load_library_items(session, status="ACTIVE")
    return await _render(request, "studio.html", title="Studio", items=items)


@router.get("/generator", response_class=HTMLResponse)
async def content_generator(
    request: Request,
    error: str | None = None,
) -> HTMLResponse:
    async with _database(request).transaction() as session:
        index = await _latest_content_index(session)
        projects = list(
            await session.scalars(
                select(GeneratedContentProject)
                .order_by(GeneratedContentProject.created_at.desc())
                .limit(20)
            )
        )
    messages = {
        "no-index": (
            "Die Wissensbasis ist noch nicht vollständig indexiert. "
            "Importiere zuerst mindestens eine Quelle."
        ),
        "invalid": "Thema, Sprache oder Dauer sind ungültig.",
        "failed": (
            "Die Generierung konnte nicht abgeschlossen werden. "
            "Bereits gespeicherte Wissensdaten blieben unverändert."
        ),
    }
    return await _render(
        request,
        "content_generator.html",
        title="Content Generator",
        index=index,
        projects=projects,
        error=messages.get(error or ""),
    )


@router.post("/generator")
async def generate_content_from_ui(request: Request) -> Response:
    form = await request.form()
    topic = str(form.get("topic", "")).strip()
    language_value = str(form.get("language", "fa")).strip()
    duration_value = str(form.get("duration_minutes", "20")).strip()
    if (
        len(topic) < 3
        or language_value not in {item.value for item in QueryLanguage}
        or not duration_value.isdigit()
    ):
        return RedirectResponse("/generator?error=invalid", status_code=303)
    duration_minutes = int(duration_value)
    if duration_minutes < 5 or duration_minutes > 60:
        return RedirectResponse("/generator?error=invalid", status_code=303)
    async with _database(request).transaction() as session:
        index = await _latest_content_index(session)
    if index is None:
        return RedirectResponse("/generator?error=no-index", status_code=303)
    try:
        result = await AutomatedContentService(
            _database(request),
            _embedding_provider(request),
            CodexCliProvider(),
        ).generate(
            GenerateContentRequest(
                topic=topic,
                language=QueryLanguage(language_value),
                chunking_run_id=index.chunking_run_id,
                embedding_model_id=index.embedding_model_id,
                target_duration_seconds=duration_minutes * 60,
            )
        )
    except Exception:
        logger.exception("semantic_content.generation_failed")
        return RedirectResponse("/generator?error=failed", status_code=303)
    return RedirectResponse(f"/generator/{result.id}", status_code=303)


@router.get("/generator/{project_id}", response_class=HTMLResponse)
async def generated_content_detail(
    request: Request, project_id: UUID
) -> HTMLResponse:
    try:
        project = await AutomatedContentService(
            _database(request),
            _embedding_provider(request),
            CodexCliProvider(),
        ).project(project_id)
    except ValueError:
        return HTMLResponse("Generierter Inhalt nicht gefunden", status_code=404)
    return await _render(
        request,
        "generated_content_detail.html",
        title=project.topic,
        project=project,
    )


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
    if language not in {"fa", "de", "en", "ar"} or not text.strip():
        return await _render(
            request,
            "studio_voice.html",
            title="Text für Voice vorbereiten",
            result=None,
            error="Sprache und Text sind erforderlich.",
        )
    from app.lecture.domain import PublicationLanguage
    from app.localization.pronunciation import prepare_pronunciation

    result = prepare_pronunciation(PublicationLanguage(language), text, [])
    return await _render(
        request,
        "studio_voice.html",
        title="Text für Voice vorbereiten",
        result=result,
        error=None,
    )


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
        channel = await _channel_service(request).register(locator)
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
    service = _channel_service(request)
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
        await _channel_service(request).discover(channel_id)
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
            await _channel_service(request).ignore(
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
    results = await _channel_service(request).import_selected(
        channel_id, candidate_ids
    )
    service = _channel_service(request)
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
    await _channel_service(request).ignore(channel_id, candidate_id)
    return RedirectResponse(f"/channels/{channel_id}", status_code=303)


@router.post("/channels/{channel_id}/delete")
async def delete_channel(request: Request, channel_id: UUID) -> Response:
    deleted = await _channel_service(request).delete_channel(
        channel_id
    )
    if not deleted:
        return HTMLResponse("Kanal nicht gefunden", status_code=404)
    return RedirectResponse("/channels", status_code=303)


@router.post("/channels/check-all", response_class=HTMLResponse)
async def check_all_channels(request: Request) -> HTMLResponse:
    service = _channel_service(request)
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
    service = _channel_service(request)
    for channel_id, candidate_ids in grouped_ids.items():
        await service.import_selected(channel_id, candidate_ids)
    return RedirectResponse("/channels", status_code=303)
