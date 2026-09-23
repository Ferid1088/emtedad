"""Direct approved-Persian language tracks and voice-ready preparation."""

import re
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.content_strategy.models import EditorialLanguageTrack, PersianDraft
from app.db.session import Database
from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.llm.codex import CodexCliProvider
from app.lecture.domain import PublicationLanguage
from app.localization.models import PronunciationLexiconEntry
from app.localization.pronunciation import prepare_pronunciation


class _Translation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)


def _count(text: str) -> int:
    return len(re.findall(r"[\w\u0600-\u06ff]+", text))


class MultilingualEditorialService:
    """Create DE/EN/AR independently from the exact approved Persian text."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.provider = CodexCliProvider()

    async def create(
        self,
        draft_id: UUID,
        languages: tuple[str, ...],
        *,
        expected_project_id: UUID | None = None,
    ) -> list[UUID]:
        async with self.database.transaction() as session:
            draft = await session.get(PersianDraft, draft_id)
            if draft is None or draft.status != "PERSIAN_APPROVED":
                raise ValueError("translations require an approved Persian version")
            source_text = draft.text
            project_id = draft.editorial_project_id
            master_id = draft.semantic_master_id
            if expected_project_id is not None and project_id != expected_project_id:
                raise ValueError("draft does not belong to this editorial project")
        tracks: list[UUID] = []
        for language in languages:
            if language not in {item.value for item in PublicationLanguage}:
                raise ValueError("unsupported language")
            if language == "fa":
                text = source_text
            else:
                result = cast(
                    _Translation,
                    await self.provider.extract(
                        StructuredExtractionRequest(
                            task="approved Persian editorial translation",
                            prompt_version="phase-12-fa-source-v1",
                            model="configured-default",
                            instructions=(
                                "Translate the approved Persian lecture into natural "
                                "spoken "
                                f"{language}. Use the Persian text as the direct "
                                "source, "
                                "preserve uncertainty and Ayin terms, "
                                "do not add facts, and return only the translated text."
                            ),
                            input_text=source_text,
                            output_model=_Translation,
                            timeout_seconds=300,
                        )
                    ),
                )
                text = result.text
            async with self.database.transaction() as session:
                latest = await session.scalar(
                    select(EditorialLanguageTrack)
                    .where(
                        EditorialLanguageTrack.editorial_project_id == project_id,
                        EditorialLanguageTrack.language == language,
                    )
                    .order_by(EditorialLanguageTrack.version_number.desc())
                )
                track = EditorialLanguageTrack(
                    editorial_project_id=project_id,
                    source_persian_draft_id=draft_id,
                    semantic_master_id=master_id,
                    language=language,
                    version_number=(latest.version_number + 1 if latest else 1),
                    display_text=text,
                    actual_word_count=_count(text),
                    estimated_duration_seconds=round(_count(text) / 130 * 60),
                    semantic_validation_status=(
                        "PASSED" if language == "fa" else "REVIEW_REQUIRED"
                    ),
                    provenance={
                        "source_persian_draft_id": str(draft_id),
                        "direct_source_language": "fa",
                        "semantic_master_id": str(master_id),
                        "translation_mode": "direct_from_approved_persian",
                    },
                )
                session.add(track)
                await session.flush()
                tracks.append(track.id)
        return tracks

    async def prepare_voice(
        self, track_id: UUID, *, expected_project_id: UUID | None = None
    ) -> UUID:
        async with self.database.transaction() as session:
            track = await session.get(EditorialLanguageTrack, track_id)
            if track is None:
                raise ValueError("language track not found")
            if (
                expected_project_id is not None
                and track.editorial_project_id != expected_project_id
            ):
                raise ValueError("language track does not belong to this project")
            if track.semantic_validation_status != "PASSED":
                raise ValueError(
                    "semantic validation is required before voice preparation"
                )
            language = PublicationLanguage(track.language)
            lexicon_rows = list(
                await session.scalars(
                    select(PronunciationLexiconEntry).where(
                        PronunciationLexiconEntry.language == language
                    )
                )
            )
            lexicon: list[dict[str, object]] = [
                {
                    "written_form": row.written_form,
                    "preferred_pronunciation": row.preferred_pronunciation,
                    "criticality": row.criticality.value,
                    "provider_representation": row.provider_representation,
                }
                for row in lexicon_rows
            ]
            prepared = prepare_pronunciation(
                language,
                track.display_text,
                lexicon,
                lexicon_version=1,
            )
            track.voice_ready_text = prepared.voice_text
            track.status = "READY_FOR_VOICE"
            return track.id
