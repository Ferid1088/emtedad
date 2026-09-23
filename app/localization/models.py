"""Versioned localization and pronunciation persistence."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ayin.domain import LanguageCode
from app.core.ayin.models import CORE
from app.db.base import Base, PostgresSchema
from app.lecture.domain import PublicationLanguage
from app.localization.domain import (
    AudioQAStatus,
    LocalizationStatus,
    PronunciationCriticality,
    PronunciationLexiconStatus,
    PronunciationStatus,
    SemanticValidationStatus,
)
from app.ops.assets.models import utc_now

CONTENT = PostgresSchema.CONTENT.value


def _local_enum(enum_type: type[object], name: str) -> ENUM:
    return ENUM(
        enum_type,
        name=name,
        schema=CONTENT,
        values_callable=lambda members: [member.value for member in members],
    )


def _language_enum() -> ENUM:
    """Reference the shared core language enum without recreating it."""

    return ENUM(
        LanguageCode,
        name="language_code",
        schema=CORE,
        create_type=False,
        values_callable=lambda members: [member.value for member in members],
    )


class LocalizationProject(Base):
    __tablename__ = "localization_projects"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    lecture_master_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_master_versions.id", ondelete="RESTRICT")
    )
    language: Mapped[PublicationLanguage] = mapped_column(
        _local_enum(PublicationLanguage, "publication_language")
    )
    status: Mapped[LocalizationStatus] = mapped_column(
        _local_enum(LocalizationStatus, "localization_status"),
        default=LocalizationStatus.DRAFT,
    )
    created_by: Mapped[str] = mapped_column(String(255), default="operator")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class LocalizationVersion(Base):
    __tablename__ = "localization_versions"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    localization_project_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.localization_projects.id", ondelete="RESTRICT")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    display_language: Mapped[LanguageCode] = mapped_column(_language_enum())
    status: Mapped[LocalizationStatus] = mapped_column(
        _local_enum(LocalizationStatus, "localization_status"),
        default=LocalizationStatus.DRAFT,
    )
    semantic_validation_status: Mapped[SemanticValidationStatus] = mapped_column(
        _local_enum(SemanticValidationStatus, "semantic_validation_status"),
        default=SemanticValidationStatus.NOT_VALIDATED,
    )
    pronunciation_status: Mapped[PronunciationStatus] = mapped_column(
        _local_enum(PronunciationStatus, "pronunciation_status"),
        default=PronunciationStatus.NOT_PREPARED,
    )
    pronunciation_lexicon_version: Mapped[int | None] = mapped_column(nullable=True)
    tts_provider_profile: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)


class LocalizationStatement(Base):
    __tablename__ = "localization_statements"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    localization_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.localization_versions.id", ondelete="CASCADE")
    )
    lecture_claim_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.lecture_claims.id", ondelete="RESTRICT")
    )
    sequence: Mapped[int] = mapped_column(Integer)
    display_text: Mapped[str] = mapped_column(Text)
    tts_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    claim_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class PronunciationLexiconEntry(Base):
    __tablename__ = "pronunciation_lexicon_entries"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    term_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CORE}.terms.id", ondelete="RESTRICT"), nullable=True
    )
    language: Mapped[LanguageCode] = mapped_column(_language_enum())
    written_form: Mapped[str] = mapped_column(String(512))
    preferred_pronunciation: Mapped[str] = mapped_column(String(512))
    provider_representation: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True
    )
    transliteration: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ipa: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ssml: Mapped[str | None] = mapped_column(Text, nullable=True)
    criticality: Mapped[PronunciationCriticality] = mapped_column(
        _local_enum(PronunciationCriticality, "pronunciation_criticality")
    )
    status: Mapped[PronunciationLexiconStatus] = mapped_column(
        _local_enum(PronunciationLexiconStatus, "pronunciation_lexicon_status")
    )
    version: Mapped[int] = mapped_column(Integer)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class LocalizationValidationRun(Base):
    __tablename__ = "localization_validation_runs"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    localization_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.localization_versions.id", ondelete="CASCADE")
    )
    valid: Mapped[bool] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class LocalizationValidationFinding(Base):
    __tablename__ = "localization_validation_findings"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    validation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.localization_validation_runs.id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text)
    blocking: Mapped[bool] = mapped_column()


class AudioPronunciationQA(Base):
    __tablename__ = "audio_pronunciation_qa"
    __table_args__ = {"schema": CONTENT}

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    localization_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTENT}.localization_versions.id", ondelete="RESTRICT")
    )
    status: Mapped[AudioQAStatus] = mapped_column(
        _local_enum(AudioQAStatus, "audio_qa_status")
    )
    provider: Mapped[str] = mapped_column(String(255))
    audio_asset_id: Mapped[UUID | None] = mapped_column(nullable=True)
    findings: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
