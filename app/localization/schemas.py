"""Boundary schemas for display/TTS localization records."""

from uuid import UUID

from pydantic import BaseModel, Field

from app.lecture.domain import PublicationLanguage
from app.localization.domain import (
    LocalizationStatus,
    PronunciationStatus,
    SemanticValidationStatus,
)


class LocalizationStatementInput(BaseModel):
    master_claim_id: UUID
    sequence: int = Field(ge=0)
    display_text: str = Field(min_length=1)
    tts_text: str | None = None
    epistemic_status: str
    certainty: str


class LocalizationCreate(BaseModel):
    lecture_master_version_id: UUID
    language: PublicationLanguage
    statements: list[LocalizationStatementInput] = Field(default_factory=list)
    pronunciation_lexicon_version: int | None = None
    tts_provider_profile: str | None = None


class LocalizationRead(BaseModel):
    id: UUID
    language: PublicationLanguage
    status: LocalizationStatus
    semantic_validation_status: SemanticValidationStatus
    pronunciation_status: PronunciationStatus
    pronunciation_lexicon_version: int | None
    tts_provider_profile: str | None
