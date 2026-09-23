"""German-first owner routes for sources, knowledge, and topic discovery."""

from pathlib import Path
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.content_strategy.domain import TopicOrigin
from app.content_strategy.models import ContentTopic
from app.db.session import Database
from app.knowledge.adapters.youtube import YouTubeAdapter
from app.knowledge.importer import ExternalKnowledgeImporter
from app.knowledge.llm.codex import CodexCliProvider
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
from app.topic_discovery import (
    TopicAnalysisService,
    TopicSuggestionService,
    dashboard_counts,
    save_topic,
    validate_youtube_url,
)

router = APIRouter(tags=["owner-web"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


async def _render(request: Request, name: str, **context: object) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name=name, context=context)


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
    return await _render(
        request,
        "dashboard.html",
        title="Dashboard",
        counts=counts,
        sources=sources,
        topics=topics,
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
    return await _render(
        request, "source_new.html", title="Quelle hinzufügen", error=None
    )


@router.post("/sources", response_class=HTMLResponse)
async def add_source(request: Request) -> Response:
    form = await request.form()
    locator = str(form.get("url", "")).strip()
    try:
        validate_youtube_url(locator)
        importer = ExternalKnowledgeImporter(
            _database(request), YouTubeAdapter(), CodexCliProvider()
        )
        await importer.ingest(locator)
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


@router.get("/knowledge", response_class=HTMLResponse)
async def knowledge(request: Request, section: str = "sources") -> HTMLResponse:
    async with _database(request).transaction() as session:
        data: object
        if section == "people":
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
        request, "knowledge.html", title="Wissensbasis", section=section, data=data
    )


@router.get("/topics", response_class=HTMLResponse)
async def topics(request: Request) -> HTMLResponse:
    async with _database(request).transaction() as session:
        rows = list(
            await session.scalars(select(ContentTopic).order_by(ContentTopic.id.desc()))
        )
    return await _render(
        request,
        "topics.html",
        title="Themen",
        topics=rows,
        suggestions=None,
        analysis=None,
        error=None,
    )


@router.post("/topics/suggestions", response_class=HTMLResponse)
async def topic_suggestions(request: Request) -> HTMLResponse:
    async with _database(request).transaction() as session:
        suggestions = await TopicSuggestionService().suggestions(session)
        rows = list(
            await session.scalars(select(ContentTopic).order_by(ContentTopic.id.desc()))
        )
    return await _render(
        request,
        "topics.html",
        title="Themen",
        topics=rows,
        suggestions=suggestions,
        analysis=None,
        error=None,
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
    async with _database(request).transaction() as session:
        topic = await save_topic(session, title=title, question=question, origin=origin)
    return RedirectResponse(f"/topics/{topic.id}", status_code=303)


@router.get("/topics/{topic_id}", response_class=HTMLResponse)
async def topic_detail(request: Request, topic_id: UUID) -> HTMLResponse:
    async with _database(request).transaction() as session:
        topic = await session.get(ContentTopic, topic_id)
        if topic is None:
            return HTMLResponse("Thema nicht gefunden", status_code=404)
    return await _render(request, "topic_detail.html", title=topic.title, topic=topic)
