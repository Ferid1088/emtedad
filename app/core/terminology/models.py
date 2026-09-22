"""Versioned terminology entities for Persian, German, English, and Arabic."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ayin.domain import EditorialStatus, LanguageCode, TermFormType
from app.core.ayin.models import CORE, _enum
from app.db.base import Base
from app.ops.assets.models import utc_now


class Term(Base):
    """Stable terminology identity, optionally linked to an Ayin concept."""

    __tablename__ = "terms"
    __table_args__ = ({"schema": CORE},)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    concept_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CORE}.ayin_concepts.id", ondelete="RESTRICT"), nullable=True
    )
    stable_key: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[EditorialStatus] = mapped_column(
        _enum(EditorialStatus, "editorial_status")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class TermForm(Base):
    """One versioned language form, including forbidden equivalents."""

    __tablename__ = "term_forms"
    __table_args__ = (
        UniqueConstraint("term_id", "language", "form", "form_type", "version"),
        Index(
            "uq_term_forms_approved_preferred",
            "term_id",
            "language",
            "scope",
            unique=True,
            postgresql_where=text(
                "form_type = 'preferred' AND approval_status = 'approved' "
                "AND effective_to IS NULL"
            ),
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL "
            "OR effective_to > effective_from",
            name="valid_effective_interval",
        ),
        CheckConstraint(
            "approval_status <> 'approved' OR effective_from IS NOT NULL",
            name="approved_effective_from",
        ),
        ForeignKeyConstraint(
            ["source_passage_id", "canon_version_id"],
            [f"{CORE}.canon_passages.id", f"{CORE}.canon_passages.canon_version_id"],
            ondelete="RESTRICT",
        ),
        {"schema": CORE},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    term_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CORE}.terms.id", ondelete="RESTRICT"), index=True
    )
    canon_version_id: Mapped[UUID]
    source_passage_id: Mapped[UUID]
    language: Mapped[LanguageCode] = mapped_column(_enum(LanguageCode, "language_code"))
    script: Mapped[str] = mapped_column(String(32))
    scope: Mapped[str] = mapped_column(String(64), default="global")
    form: Mapped[str] = mapped_column(String(512))
    form_type: Mapped[TermFormType] = mapped_column(
        _enum(TermFormType, "term_form_type")
    )
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_status: Mapped[EditorialStatus] = mapped_column(
        _enum(EditorialStatus, "editorial_status")
    )
    version: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
