"""Published memory: read-only review input, never a writing source.

Two readers share one item shape:

* ``PublishedMemoryReader`` reads the historical ``EditorialProject`` /
  ``PersianDraft`` / ``ChannelLedgerEntry`` tables. Entries may carry legacy
  ``lesson_id`` provenance; nothing here requires it.
* ``ScriptDraftMemoryReader`` reads approved generic ``ScriptDraft`` rows and
  joins them to their ``ContentBrief`` for channel/question metadata — the
  ContentBrief-origin production path.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.briefs.models import ContentBrief
from app.content_engine.domain import DraftStatus
from app.content_engine.models import ScriptDraft
from app.content_engine.writing.text import (
    extract_examples,
    extract_open_promises,
)
from app.content_strategy.models import (
    ChannelLedgerEntry,
    EditorialProject,
    PersianDraft,
)


@dataclass(frozen=True, slots=True)
class PublishedMemoryItem:
    project_id: UUID
    title: str
    text: str
    lesson_id: str | None  # LEGACY_PROVENANCE_ONLY — None for generic items
    concept_keys: tuple[str, ...]
    examples: tuple[str, ...]
    open_promises: tuple[str, ...]


class PublishedMemoryReader:
    """Read only published projects; drafts never become memory implicitly."""

    @staticmethod
    async def load(session: AsyncSession) -> tuple[list[PublishedMemoryItem], int]:
        ledger_rows = list(await session.scalars(select(ChannelLedgerEntry)))
        ledgers = {item.editorial_project_id: item for item in ledger_rows}
        projects = list(
            await session.scalars(
                select(EditorialProject).where(EditorialProject.status == "PUBLISHED")
            )
        )
        memory: list[PublishedMemoryItem] = []
        for project in projects:
            draft = await session.scalar(
                select(PersianDraft)
                .where(
                    PersianDraft.editorial_project_id == project.id,
                    PersianDraft.status == "PERSIAN_APPROVED",
                )
                .order_by(PersianDraft.version_number.desc())
            )
            if draft is None:
                continue
            ledger = ledgers.get(project.id)
            snapshot = project.strategy_topic_snapshot or {}
            package = snapshot.get("lesson_content_package_snapshot", {})
            package = package if isinstance(package, dict) else {}
            concept_keys = (
                tuple(str(item) for item in ledger.concept_keys)
                if ledger
                else tuple(str(item) for item in package.get("core_concepts", []))
            )
            memory.append(
                PublishedMemoryItem(
                    project_id=project.id,
                    title=ledger.published_title if ledger else project.title,
                    text=draft.text,
                    lesson_id=(
                        ledger.lesson_id
                        if ledger
                        else str(snapshot.get("lesson_id") or "") or None
                    ),
                    concept_keys=concept_keys,
                    examples=(
                        tuple(str(item) for item in ledger.examples) if ledger else ()
                    ),
                    open_promises=(
                        tuple(
                            str(item.get("text", ""))
                            for item in ledger.open_promises
                            if isinstance(item, dict) and item.get("text")
                        )
                        if ledger
                        else ()
                    ),
                )
            )
        return memory, len(ledger_rows)


class ScriptDraftMemoryReader:
    """Published memory for the generic ContentBrief-origin production path."""

    @staticmethod
    async def load(
        session: AsyncSession, *, exclude_brief_id: UUID | None = None
    ) -> list[PublishedMemoryItem]:
        statement = (
            select(ScriptDraft, ContentBrief)
            .join(
                ContentBrief,
                ContentBrief.id == ScriptDraft.content_brief_id,
            )
            .where(ScriptDraft.status == DraftStatus.APPROVED.value)
            .order_by(ScriptDraft.created_at.desc())
        )
        if exclude_brief_id is not None:
            statement = statement.where(
                ScriptDraft.content_brief_id != exclude_brief_id
            )
        rows = (await session.execute(statement)).all()
        return [
            PublishedMemoryItem(
                project_id=draft.id,
                title=brief.question,
                text=draft.text,
                lesson_id=None,
                concept_keys=tuple(
                    str(item) for item in (brief.primary_concepts_json or [])
                ),
                examples=tuple(extract_examples(draft.text)),
                open_promises=tuple(
                    str(item.get("text", ""))
                    for item in extract_open_promises(draft.text)
                ),
            )
            for draft, brief in rows
        ]
