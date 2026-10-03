"""LEGACY_PROVENANCE_ONLY: maintenance of historical Persian drafts.

The lesson production path is retired (Phase 21): this service no longer
generates drafts. New Persian scripts are produced by the generic
``app.content_engine.review.ScriptService`` from a ContentBrief-origin
Semantic Master. What remains lets the owner edit, re-review, and approve
drafts that already exist, using only persisted snapshots — no lesson
canon files, no ``LessonCanonRepository``.
"""

import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select

from app.content_engine.writing.diversity import ScriptDiversityValidator
from app.content_engine.writing.findings import PipelineFinding
from app.content_engine.writing.memory import PublishedMemoryReader
from app.content_engine.writing.native import PersianNativeReviewer
from app.content_engine.writing.quality import (
    PersianDraftQualityReport,
    PersianDraftQualityValidator,
    clean_source_text,
)
from app.content_engine.writing.text import deduplicate_findings
from app.content_strategy.lesson_canon import LessonContentPackage
from app.content_strategy.lesson_workflow import lesson_package_from_project
from app.content_strategy.models import (
    EditorialProject,
    PersianDraft,
    PersianReviewFinding,
)
from app.content_strategy.persian_pipeline import (
    final_semantic_findings,
    review_bundle,
)
from app.db.session import Database
from app.lecture.schemas import SemanticLectureMasterExport
from app.lecture.service import LectureMasterService


def _word_count(text: str) -> int:
    return len(re.findall(r"[\w\u0600-\u06ff]+", text))


class PersianEditorialService:
    """Create immutable draft versions; owner text is never overwritten."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.masters = LectureMasterService(database)
        self.quality = PersianDraftQualityValidator()

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
                provenance={
                    **original.provenance,
                    "edited_from": str(original.id),
                    "owner_edited": True,
                    "review_completed": False,
                    "final_semantic_validation": "NOT_RUN_AFTER_OWNER_EDIT",
                },
            )
            session.add(edited)
            await session.flush()
            return edited.id

    async def review(self, draft_id: UUID) -> list[UUID]:
        """Re-run the deterministic checks on a historical draft.

        The pinned lesson package is read from the project or draft
        snapshot; canon files are never consulted.
        """

        async with self.database.transaction() as session:
            draft = await session.get(PersianDraft, draft_id)
            if draft is None:
                raise ValueError("draft not found")
            project = await session.get(EditorialProject, draft.editorial_project_id)
            if project is None:
                raise ValueError("editorial project not found")
            lesson = self._lesson_package_for_review(project, draft)
            published_memory, ledger_count = await PublishedMemoryReader.load(session)
            master_id = draft.semantic_master_id
            text = draft.text

        evidence_texts = (
            self._evidence_texts(await self.masters.export(master_id))
            if master_id is not None
            else []
        )
        quality = self.quality.validate(text, evidence_texts)
        if lesson is not None:
            review = review_bundle(
                text,
                lesson,
                external_evidence_count=len(evidence_texts),
                published=published_memory,
                ledger_entries_checked=ledger_count,
            )
            final = final_semantic_findings(
                text, lesson, external_evidence_count=len(evidence_texts)
            )
            findings = self._pipeline_findings(
                quality, list(review.findings), quality, final
            )
            published_checked = review.published_items_checked
            ledger_checked = review.ledger_entries_checked
            explicit_ratio = review.explicit_ayin_ratio
        else:
            # Generic path: no pinned lesson — deterministic quality,
            # nativeness, and archive-diversity checks only.
            pipeline = [
                PipelineFinding(
                    item.code,
                    "GENERIC_QUALITY",
                    "ERROR" if item.blocking else "WARNING",
                    item.message,
                    blocking=item.blocking,
                )
                for item in quality.findings
            ]
            pipeline.extend(PersianNativeReviewer().review(text))
            pipeline.extend(ScriptDiversityValidator().validate(text, published_memory))
            findings = deduplicate_findings(pipeline)
            published_checked = len(published_memory)
            ledger_checked = ledger_count
            explicit_ratio = 0.0
        async with self.database.transaction() as session:
            draft = await session.get(PersianDraft, draft_id)
            if draft is None:
                raise ValueError("draft not found")
            await session.execute(
                delete(PersianReviewFinding).where(
                    PersianReviewFinding.draft_id == draft.id
                )
            )
            rows = [
                PersianReviewFinding(
                    draft_id=draft.id,
                    code=item.code,
                    severity=item.severity,
                    message=f"[{item.category}] {item.message}",
                    blocking=item.blocking,
                )
                for item in findings
            ]
            session.add_all(rows)
            draft.status = (
                "REVIEW_REQUIRED"
                if any(item.blocking for item in findings)
                else "REVIEWED"
            )
            draft.provenance = {
                **draft.provenance,
                "review_completed": True,
                "reviewed_at": datetime.now(UTC).isoformat(),
                "published_archive_items_checked": published_checked,
                "channel_ledger_entries_checked": ledger_checked,
                "explicit_ayin_reference_estimate": explicit_ratio,
                "review_findings": [self._finding_payload(item) for item in findings],
                "final_semantic_validation": (
                    "REVIEW_REQUIRED"
                    if any(item.blocking for item in findings)
                    else "PASSED"
                ),
            }
            project = await session.get(EditorialProject, draft.editorial_project_id)
            if project is not None:
                project.status = "PERSIAN_REVIEW"
            await session.flush()
            return [item.id for item in rows]

    @staticmethod
    def _lesson_package_for_review(
        project: EditorialProject,
        draft: PersianDraft,
    ) -> LessonContentPackage | None:
        """Use the project pin, or the draft's immutable package for legacy projects."""

        pinned = lesson_package_from_project(project)
        if pinned is not None:
            return pinned
        snapshot = draft.provenance.get("lesson_content_package")
        if not isinstance(snapshot, dict):
            return None
        return LessonContentPackage.model_validate(snapshot)

    async def approve(self, draft_id: UUID) -> None:
        async with self.database.transaction() as session:
            draft = await session.get(PersianDraft, draft_id)
            if draft is None:
                raise ValueError("draft not found")
            if draft.provenance.get("review_completed") is not True:
                raise ValueError("Persian review must be completed before approval")
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
            project = await session.get(EditorialProject, draft.editorial_project_id)
            if project is not None:
                lesson = lesson_package_from_project(project)
                if lesson is not None:
                    project.title = lesson.canonical_lesson_title
                project.status = "PERSIAN_APPROVED"

    @staticmethod
    def _evidence_texts(export: SemanticLectureMasterExport) -> list[str]:
        """External evidence texts from a master export — input, not prose."""

        items: list[str] = []
        for item in export.evidence:
            if str(item.get("evidence_kind", "")) != "EXTERNAL_CHUNK":
                continue
            text = clean_source_text(str(item.get("text") or ""))
            if text and text not in items:
                items.append(text[:700])
        return items

    @staticmethod
    def _pipeline_findings(
        initial_quality: PersianDraftQualityReport,
        review_findings: list[PipelineFinding],
        final_quality: PersianDraftQualityReport,
        final_findings: list[PipelineFinding],
    ) -> list[PipelineFinding]:
        findings = list(review_findings) + list(final_findings)
        for stage, report in (
            ("INITIAL_QUALITY", initial_quality),
            ("FINAL_QUALITY", final_quality),
        ):
            findings.extend(
                PipelineFinding(
                    item.code,
                    stage,
                    "ERROR" if item.blocking else "WARNING",
                    item.message,
                    blocking=item.blocking,
                )
                for item in report.findings
            )
        return deduplicate_findings(findings)

    @staticmethod
    def _finding_payload(item: PipelineFinding) -> dict[str, object]:
        return {
            "code": item.code,
            "category": item.category,
            "severity": item.severity,
            "message": item.message,
            "blocking": item.blocking,
            "metadata": item.metadata,
        }
