"""Owner-facing routes for the isolated Vortragsstruktur module."""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.db.session import Database
from app.knowledge.models import Source, SourceSegment
from app.speech_structure.models import SpeechStructure, SpeechStructureRun
from app.speech_structure.scheduler import (
    SpeechStructureScheduler,
    collect_source_infos,
    get_scheduler,
    summarize_states,
)
from app.speech_structure.service import SpeechStructureService

router = APIRouter(tags=["owner-speech-structure"])
templates = Jinja2Templates(
    directory=str(Path(__file__).parents[1] / "web" / "templates")
)


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def _scheduler(request: Request) -> SpeechStructureScheduler:
    return get_scheduler(_database(request))


def _segment_paragraphs(
    segments: Sequence[SourceSegment], *, pause_seconds: float = 4.0
) -> list[str]:
    """Join transcript segments into readable paragraphs at speech pauses."""

    paragraphs: list[str] = []
    current: list[str] = []
    previous_end: float | None = None
    for segment in segments:
        if previous_end is not None and (
            float(segment.start_seconds) - previous_end > pause_seconds
        ):
            paragraphs.append(" ".join(current))
            current = []
        if segment.raw_text.strip():
            current.append(segment.raw_text.strip())
        previous_end = float(segment.end_seconds)
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


@router.get("/speech-structures", response_class=HTMLResponse)
async def speech_structures(request: Request) -> HTMLResponse:
    scheduler = _scheduler(request)
    async with _database(request).transaction() as session:
        sources = list(
            await session.scalars(
                select(Source).order_by(Source.created_at.desc())
            )
        )
        infos = await collect_source_infos(session)
        structures = list(
            await session.scalars(
                select(SpeechStructure)
                .distinct(SpeechStructure.source_id)
                .order_by(
                    SpeechStructure.source_id, SpeechStructure.version.desc()
                )
            )
        )
    info_by_source = {info.source_id: info for info in infos}
    states = summarize_states(infos, scheduler, now=datetime.now(UTC))
    current: dict[UUID, SpeechStructure] = {
        structure.source_id: structure for structure in structures
    }
    counts: dict[str, int] = {}
    for state in states.values():
        counts[state.status.value] = counts.get(state.status.value, 0) + 1
    return templates.TemplateResponse(
        request=request,
        name="speech_structures.html",
        context={
            "title": "Vortragsstruktur",
            "sources": sources,
            "structures": current,
            "infos": info_by_source,
            "states": states,
            "counts": counts,
            "scheduler": scheduler,
        },
    )


@router.post("/speech-structures/{source_id}/generate")
async def generate_speech_structure(
    request: Request, source_id: UUID
) -> RedirectResponse:
    _scheduler(request).enqueue(source_id)
    return RedirectResponse(f"/speech-structures/{source_id}", status_code=303)


@router.post("/speech-structures/{source_id}/regenerate")
async def regenerate_speech_structure(
    request: Request, source_id: UUID
) -> RedirectResponse:
    _scheduler(request).enqueue(source_id, force=True)
    return RedirectResponse(f"/speech-structures/{source_id}", status_code=303)


@router.post("/speech-structures/scan")
async def scan_speech_structures(request: Request) -> RedirectResponse:
    await _scheduler(request).scan_once()
    return RedirectResponse("/speech-structures", status_code=303)


@router.post("/speech-structures/retry-failed")
async def retry_failed_speech_structures(request: Request) -> RedirectResponse:
    await _scheduler(request).retry_failed()
    return RedirectResponse("/speech-structures", status_code=303)


@router.get("/speech-structures/{source_id}", response_class=HTMLResponse)
async def speech_structure_detail(
    request: Request, source_id: UUID, section_id: UUID | None = None
) -> HTMLResponse:
    database = _database(request)
    scheduler = _scheduler(request)
    async with database.transaction() as session:
        source = await session.get(Source, source_id)
        if source is None:
            return HTMLResponse("Quelle nicht gefunden", status_code=404)
        structure = await session.scalar(
            select(SpeechStructure)
            .where(SpeechStructure.source_id == source_id)
            .order_by(SpeechStructure.version.desc())
        )
        latest_run = None
        if structure is not None:
            latest_run = await session.scalar(
                select(SpeechStructureRun)
                .where(SpeechStructureRun.speech_structure_id == structure.id)
                .order_by(SpeechStructureRun.created_at.desc())
            )
        infos = await collect_source_infos(session)
    info = next((item for item in infos if item.source_id == source_id), None)
    state = None
    if info is not None:
        state = summarize_states(
            [info], scheduler, now=datetime.now(UTC)
        ).get(source_id)
    tree = []
    report = None
    selected = None
    selected_paragraphs: list[str] = []
    if structure is not None:
        service = SpeechStructureService(database)
        tree = await service.get_tree(structure.id)
        report = await service.validate(structure.id)
        if section_id is not None:
            selected = await service.get_section(section_id)
            if selected is not None:
                segments = await service.get_section_segments(section_id)
                selected_paragraphs = _segment_paragraphs(segments)
    return templates.TemplateResponse(
        request=request,
        name="speech_structure_detail.html",
        context={
            "title": "Vortragsstruktur",
            "source": source,
            "structure": structure,
            "latest_run": latest_run,
            "state": state,
            "info": info,
            "phase": scheduler.phase_of(source_id),
            "tree": tree,
            "report": report,
            "selected": selected,
            "selected_paragraphs": selected_paragraphs,
        },
    )
