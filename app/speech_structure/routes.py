"""Owner-facing routes for the isolated Vortragsstruktur module."""

from pathlib import Path
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.db.session import Database
from app.knowledge.models import Source, SourceSegment, SourceVersion
from app.speech_structure.models import SpeechStructure
from app.speech_structure.service import SpeechStructureService

router = APIRouter(tags=["owner-speech-structure"])
templates = Jinja2Templates(
    directory=str(Path(__file__).parents[1] / "web" / "templates")
)


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


@router.get("/speech-structures", response_class=HTMLResponse)
async def speech_structures(request: Request) -> HTMLResponse:
    async with _database(request).transaction() as session:
        sources = list(
            await session.scalars(
                select(Source)
                .join(SourceVersion, SourceVersion.source_id == Source.id)
                .join(
                    SourceSegment, SourceSegment.source_version_id == SourceVersion.id
                )
                .distinct()
                .order_by(Source.created_at.desc())
            )
        )
        structures = list(
            await session.scalars(
                select(SpeechStructure).order_by(SpeechStructure.version.desc())
            )
        )
    current: dict[UUID, SpeechStructure] = {}
    for structure in structures:
        current.setdefault(structure.source_id, structure)
    return templates.TemplateResponse(
        request=request,
        name="speech_structures.html",
        context={
            "title": "Vortragsstruktur",
            "sources": sources,
            "structures": current,
        },
    )


@router.post("/speech-structures/{source_id}/generate")
async def generate_speech_structure(
    request: Request, source_id: UUID
) -> RedirectResponse:
    service = SpeechStructureService(_database(request))
    await service.create_for_source(source_id)
    return RedirectResponse(f"/speech-structures/{source_id}", status_code=303)


@router.post("/speech-structures/{source_id}/regenerate")
async def regenerate_speech_structure(
    request: Request, source_id: UUID
) -> RedirectResponse:
    service = SpeechStructureService(_database(request))
    await service.regenerate(source_id)
    return RedirectResponse(f"/speech-structures/{source_id}", status_code=303)


@router.get("/speech-structures/{source_id}", response_class=HTMLResponse)
async def speech_structure_detail(
    request: Request, source_id: UUID, section_id: UUID | None = None
) -> HTMLResponse:
    database = _database(request)
    async with database.transaction() as session:
        source = await session.get(Source, source_id)
        if source is None:
            return HTMLResponse("Quelle nicht gefunden", status_code=404)
        structure = await session.scalar(
            select(SpeechStructure)
            .where(SpeechStructure.source_id == source_id)
            .order_by(SpeechStructure.version.desc())
        )
    tree = []
    report = None
    selected = None
    selected_segments = []
    if structure is not None:
        service = SpeechStructureService(database)
        tree = await service.get_tree(structure.id)
        report = await service.validate(structure.id)
        if section_id is not None:
            selected = await service.get_section(section_id)
            if selected is not None:
                selected_segments = await service.get_section_segments(section_id)
    return templates.TemplateResponse(
        request=request,
        name="speech_structure_detail.html",
        context={
            "title": "Vortragsstruktur",
            "source": source,
            "structure": structure,
            "tree": tree,
            "report": report,
            "selected": selected,
            "selected_segments": selected_segments,
        },
    )
