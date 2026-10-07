"""Owner tools outside the production pipeline: voice text preparation and
the pronunciation lexicon. Everything else lives in the Studio
(``studio_routes``); the root URL opens the Studio.
"""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.db.session import Database
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
from app.web.studio_routes import _render

router = APIRouter(tags=["owner-web"])


def _database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


@router.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse("/studio", status_code=307)


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
    key = None
    error = None
    voice_text = result.voice_text
    if language == "fa" and form.get("harakat") == "1":
        # Pronunciation agent: harakat for every word a voice could misread.
        from app.knowledge.llm.factory import resolve_llm_provider
        from app.knowledge.llm.roles import AgentRole
        from app.voice.pronunciation_key import PronunciationKeyEditor
        from app.web.jobs import friendly_error

        try:
            key = await PronunciationKeyEditor(
                resolve_llm_provider(role=AgentRole.PRONUNCIATION_EDITOR)
            ).annotate(result.voice_text)
            voice_text = key.voice_text("vowelled")
        except Exception as exc:  # noqa: BLE001 — shown to the owner
            error = "Aussprache-Schlüssel fehlgeschlagen: " + friendly_error(exc)
    return await _render(
        request,
        "studio_voice.html",
        title="Text für Voice vorbereiten",
        result=result,
        voice_text=voice_text,
        key=key,
        error=error,
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
