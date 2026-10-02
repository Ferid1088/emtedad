"""Owner-facing curation of the versioned pronunciation lexicon.

Lexicon entries follow an explicit review lifecycle (PROPOSED -> APPROVED ->
DEPRECATED).  Only approved entries may reach voice preparation; a changed
pronunciation is a new version row, so consumed states remain inspectable.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ayin.domain import LanguageCode
from app.db.session import Database
from app.lecture.domain import PublicationLanguage
from app.localization.domain import (
    PronunciationCriticality,
    PronunciationLexiconStatus,
)
from app.localization.models import PronunciationLexiconEntry

# The ElevenLabs v3 profile used by the editorial voice-preparation pipeline.
DEFAULT_PROVIDER_PROFILE = "elevenlabs_v3"

STATUS_LABELS = {
    "PROPOSED": "Vorgeschlagen",
    "APPROVED": "Freigegeben",
    "DEPRECATED": "Verworfen",
}
CRITICALITY_LABELS = {
    "CRITICAL": "Kritisch",
    "IMPORTANT": "Wichtig",
    "NORMAL": "Normal",
}
LANGUAGES = ("fa", "de", "en", "ar")


@dataclass(frozen=True, slots=True)
class ApprovedLexicon:
    """Approved entries in the shape consumed by ``prepare_pronunciation``."""

    entries: list[dict[str, object]]
    version: int | None
    entry_ids: tuple[UUID, ...]


async def load_approved_lexicon(
    session: AsyncSession, language: PublicationLanguage
) -> ApprovedLexicon:
    """Load approved entries only; proposals never reach voice preparation."""

    rows = list(
        await session.scalars(
            select(PronunciationLexiconEntry)
            .where(
                PronunciationLexiconEntry.language == LanguageCode(language.value),
                PronunciationLexiconEntry.status == PronunciationLexiconStatus.APPROVED,
            )
            .order_by(
                # Longest forms first so a phrase deterministically wins over
                # terms it contains during sequential replacement.
                func.length(PronunciationLexiconEntry.written_form).desc(),
                PronunciationLexiconEntry.written_form,
            )
        )
    )
    return ApprovedLexicon(
        entries=[
            {
                "written_form": row.written_form,
                "preferred_pronunciation": row.preferred_pronunciation,
                "criticality": row.criticality.value,
                "provider_representation": row.provider_representation,
            }
            for row in rows
        ],
        version=max((row.version for row in rows), default=None),
        entry_ids=tuple(row.id for row in rows),
    )


class PronunciationLexiconService:
    """Curate pronunciation entries through an explicit review lifecycle."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def entries(
        self, *, language: str | None = None, status: str | None = None
    ) -> list[PronunciationLexiconEntry]:
        """List entries, optionally filtered by language and review status."""

        query = select(PronunciationLexiconEntry)
        if language:
            query = query.where(
                PronunciationLexiconEntry.language == LanguageCode(language)
            )
        if status:
            query = query.where(
                PronunciationLexiconEntry.status == PronunciationLexiconStatus(status)
            )
        query = query.order_by(
            PronunciationLexiconEntry.language,
            PronunciationLexiconEntry.written_form,
            PronunciationLexiconEntry.version.desc(),
        )
        async with self.database.transaction() as session:
            return list(await session.scalars(query))

    async def propose(
        self,
        *,
        language: str,
        written_form: str,
        preferred_pronunciation: str,
        transliteration: str | None = None,
        ipa: str | None = None,
        provider_form: str | None = None,
        criticality: str = PronunciationCriticality.IMPORTANT.value,
        notes: str | None = None,
    ) -> UUID:
        """Create a PROPOSED entry; re-proposal after deprecation versions up."""

        try:
            language_code = LanguageCode(language)
        except ValueError:
            raise ValueError("unsupported language") from None
        try:
            criticality_level = PronunciationCriticality(criticality)
        except ValueError:
            raise ValueError("unsupported criticality") from None
        form = written_form.strip()
        pronunciation = preferred_pronunciation.strip()
        if not form or not pronunciation:
            raise ValueError("written form and pronunciation are required")
        if len(form) > 512 or len(pronunciation) > 512:
            raise ValueError("written form and pronunciation must fit 512 characters")
        provider_representation = (
            {DEFAULT_PROVIDER_PROFILE: provider_form.strip()}
            if provider_form and provider_form.strip()
            else None
        )
        async with self.database.transaction() as session:
            siblings = list(
                await session.scalars(
                    select(PronunciationLexiconEntry).where(
                        PronunciationLexiconEntry.language == language_code,
                        PronunciationLexiconEntry.written_form == form,
                    )
                )
            )
            # At most one active entry per written form so replacement during
            # voice preparation stays deterministic.
            if any(
                sibling.status != PronunciationLexiconStatus.DEPRECATED
                for sibling in siblings
            ):
                raise ValueError("an active entry already exists for this written form")
            entry = PronunciationLexiconEntry(
                language=language_code,
                written_form=form,
                preferred_pronunciation=pronunciation,
                provider_representation=provider_representation,
                transliteration=self._clean(transliteration),
                ipa=self._clean(ipa),
                criticality=criticality_level,
                status=PronunciationLexiconStatus.PROPOSED,
                version=max((sibling.version for sibling in siblings), default=0) + 1,
                reviewer_notes=self._clean(notes),
            )
            session.add(entry)
            await session.flush()
            return entry.id

    async def approve(self, entry_id: UUID, notes: str | None = None) -> None:
        """Approve a proposed entry for use in voice preparation."""

        async with self.database.transaction() as session:
            entry = await session.get(PronunciationLexiconEntry, entry_id)
            if entry is None:
                raise ValueError("lexicon entry not found")
            if entry.status != PronunciationLexiconStatus.PROPOSED:
                raise ValueError("only proposed entries can be approved")
            entry.status = PronunciationLexiconStatus.APPROVED
            note = self._clean(notes)
            if note:
                entry.reviewer_notes = note

    async def deprecate(self, entry_id: UUID, notes: str | None = None) -> None:
        """Withdraw an entry; deprecated rows stay for reproducibility."""

        async with self.database.transaction() as session:
            entry = await session.get(PronunciationLexiconEntry, entry_id)
            if entry is None:
                raise ValueError("lexicon entry not found")
            if entry.status == PronunciationLexiconStatus.DEPRECATED:
                raise ValueError("entry is already deprecated")
            entry.status = PronunciationLexiconStatus.DEPRECATED
            note = self._clean(notes)
            if note:
                entry.reviewer_notes = note

    @staticmethod
    def _clean(value: str | None) -> str | None:
        cleaned = value.strip() if value else ""
        return cleaned or None
