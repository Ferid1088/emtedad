"""Research-bound Persian draft and owner approval workflow."""

import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select

from app.content_strategy.models import (
    EditorialProject,
    PersianDraft,
    PersianReviewFinding,
)
from app.db.session import Database
from app.lecture.models import LectureMasterVersion
from app.lecture.service import LectureMasterService


def _word_count(text: str) -> int:
    return len(re.findall(r"[\w\u0600-\u06ff]+", text))


def _fit_duration(text: str, target_words: int) -> str:
    words = text.split()
    if _word_count(text) <= target_words:
        return text
    end = min(target_words, len(words))
    while end > 1 and _word_count(" ".join(words[:end])) > target_words:
        end -= 1
    return " ".join(words[:end]).rstrip("،؛,.؟") + " …"


class PersianEditorialService:
    """Create immutable draft versions; owner text is never overwritten."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.masters = LectureMasterService(database)

    async def generate(
        self,
        project_id: UUID,
        master_id: UUID,
        *,
        target_minutes: int,
        draft_count: int,
        owner_prompt: str | None,
    ) -> list[UUID]:
        if not 1 <= target_minutes <= 180 or draft_count not in {1, 2, 3, 5}:
            raise ValueError("invalid duration or draft count")
        export = await self.masters.export(master_id)
        if export.master.get("status") != "READY":
            raise ValueError(
                "Persisch kann erst aus einem READY Semantic Master entstehen"
            )
        claims = [
            str(c.get("semantic_proposition") or c.get("plain_meaning") or "")
            for c in export.claims
        ]
        claims = [c for c in claims if c]
        if not claims:
            raise ValueError("Semantic Master enthält keine semantischen Claims")
        text = (
            "در چارچوب آیین امتداد، این پرسش را با دقت و بدون ادعای اثبات "
            "علمی دنبال می‌کنیم.\n\n" + "\n\n".join(claims)
        )
        target_words = target_minutes * 110
        text = _fit_duration(text, target_words)
        count = _word_count(text)
        async with self.database.transaction() as session:
            project = await session.get(EditorialProject, project_id)
            master = await session.get(LectureMasterVersion, master_id)
            if project is None or master is None:
                raise ValueError("editorial project or semantic master not found")
            project.semantic_master_id = master.id
            project.research_package_id = master.research_package_id
            project.target_duration_minutes = target_minutes
            project.owner_prompt = owner_prompt
            result: list[UUID] = []
            for variant in range(1, draft_count + 1):
                draft = PersianDraft(
                    editorial_project_id=project.id,
                    semantic_master_id=master.id,
                    version_number=1,
                    variant_index=variant,
                    text=text,
                    owner_prompt=owner_prompt,
                    target_duration_minutes=target_minutes,
                    target_word_count_min=round(target_words * 0.9),
                    target_word_count_max=round(target_words * 1.1),
                    actual_word_count=count,
                    estimated_duration_seconds=round(count / 110 * 60),
                    provenance={
                        "research_package_id": str(master.research_package_id),
                        "semantic_master_id": str(master.id),
                        "owner_prompt": owner_prompt,
                        "generator": "grounded-baseline-v1",
                        "variant_index": variant,
                    },
                )
                session.add(draft)
                await session.flush()
                result.append(draft.id)
            return result

    async def edit(self, draft_id: UUID, text: str) -> UUID:
        async with self.database.transaction() as session:
            original = await session.get(PersianDraft, draft_id)
            if original is None:
                raise ValueError("draft not found")
            latest = await session.scalar(
                select(PersianDraft)
                .where(
                    PersianDraft.editorial_project_id == original.editorial_project_id
                )
                .order_by(PersianDraft.version_number.desc())
            )
            count = _word_count(text)
            edited = PersianDraft(
                editorial_project_id=original.editorial_project_id,
                parent_draft_id=original.id,
                semantic_master_id=original.semantic_master_id,
                version_number=(latest.version_number + 1 if latest else 2),
                variant_index=original.variant_index,
                text=text,
                status="USER_EDITED",
                owner_prompt=original.owner_prompt,
                target_duration_minutes=original.target_duration_minutes,
                target_word_count_min=original.target_word_count_min,
                target_word_count_max=original.target_word_count_max,
                actual_word_count=count,
                estimated_duration_seconds=round(count / 110 * 60),
                provenance={**original.provenance, "edited_from": str(original.id)},
            )
            session.add(edited)
            await session.flush()
            return edited.id

    async def review(self, draft_id: UUID) -> list[UUID]:
        async with self.database.transaction() as session:
            draft = await session.get(PersianDraft, draft_id)
            if draft is None:
                raise ValueError("draft not found")
            await session.execute(
                delete(PersianReviewFinding).where(
                    PersianReviewFinding.draft_id == draft.id
                )
            )
            if any(
                term in draft.text
                for term in ("علم ثابت کرده", "علم اثبات کرده", "science proves")
            ):
                finding = PersianReviewFinding(
                    draft_id=draft.id,
                    code="AYIN_PRESENTED_AS_SCIENTIFIC_FACT",
                    severity="ERROR",
                    message="Ayin-Rahmenaussage klingt wie wissenschaftlich bewiesen.",
                    blocking=True,
                )
                session.add(finding)
                await session.flush()
                return [finding.id]
            return []

    async def approve(self, draft_id: UUID) -> None:
        async with self.database.transaction() as session:
            draft = await session.get(PersianDraft, draft_id)
            if draft is None:
                raise ValueError("draft not found")
            blocking = await session.scalar(
                select(PersianReviewFinding.id).where(
                    PersianReviewFinding.draft_id == draft.id,
                    PersianReviewFinding.blocking.is_(True),
                )
            )
            if blocking is not None:
                raise ValueError("blocking Persian review findings remain")
            draft.status = "PERSIAN_APPROVED"
            draft.provenance = {
                **draft.provenance,
                "approved_at": datetime.now(UTC).isoformat(),
            }
