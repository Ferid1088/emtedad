"""Research-bound Persian draft and owner approval workflow."""

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select

from app.content_strategy.lesson_canon import (
    LessonCanonRepository,
    LessonContentPackage,
)
from app.content_strategy.lesson_workflow import lesson_package_from_project
from app.content_strategy.models import (
    EditorialProject,
    PersianDraft,
    PersianReviewFinding,
)
from app.content_strategy.persian_pipeline import (
    PersianNativeOptimizer,
    PipelineFinding,
    PublishedMemoryReader,
    ScriptOutline,
    final_semantic_findings,
    review_bundle,
)
from app.content_strategy.persian_prompt import MASTER_PERSIAN_WRITING_PROMPT
from app.content_strategy.persian_quality import (
    PersianDraftQualityReport,
    PersianDraftQualityValidator,
    clean_source_text,
)
from app.db.session import Database
from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.llm.codex import CodexCliProvider
from app.lecture.models import LectureMasterVersion
from app.lecture.schemas import SemanticLectureMasterExport
from app.lecture.service import LectureMasterService
from app.research.models import ResearchPackage


def _word_count(text: str) -> int:
    return len(re.findall(r"[\w\u0600-\u06ff]+", text))


class _PersianDraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)


class PersianEditorialService:
    """Create immutable draft versions; owner text is never overwritten."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.masters = LectureMasterService(database)
        self.provider = CodexCliProvider()
        self.optimizer = PersianNativeOptimizer(self.provider)
        self.quality = PersianDraftQualityValidator()
        self.lesson_canon = LessonCanonRepository()

    async def generate(
        self,
        project_id: UUID,
        master_id: UUID,
        *,
        lesson_id: str,
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
        target_min = round(target_minutes * 99)
        target_max = round(target_minutes * 121)
        async with self.database.transaction() as session:
            project = await session.get(EditorialProject, project_id)
            master = await session.get(LectureMasterVersion, master_id)
            if project is None or master is None:
                raise ValueError("editorial project or semantic master not found")
            pinned_package = lesson_package_from_project(project)
            if pinned_package is not None and pinned_package.lesson_id != lesson_id:
                raise ValueError("lesson project must use its pinned canonical lesson")
            if pinned_package is not None:
                if (
                    project.semantic_master_id != master.id
                    or project.research_package_id != master.research_package_id
                ):
                    raise ValueError(
                        "lesson projects must use their own external research package"
                    )
                research_package = await session.get(
                    ResearchPackage, master.research_package_id
                )
                if (
                    research_package is None
                    or research_package.lesson_id != pinned_package.lesson_id
                    or research_package.lesson_canon_hash
                    != pinned_package.lesson_canon_hash
                ):
                    raise ValueError(
                        "external research does not match the pinned lesson canon"
                    )
            lesson_package = pinned_package or self.lesson_canon.package(lesson_id)
            if not lesson_package.canonical_lesson_explanation.strip():
                raise ValueError("LessonContentPackage is incomplete")
            project.title = lesson_package.canonical_lesson_title
            published_memory, ledger_count = await PublishedMemoryReader.load(session)
            existing_variants = int(
                await session.scalar(
                    select(
                        func.coalesce(func.max(PersianDraft.variant_index), 0)
                    ).where(PersianDraft.editorial_project_id == project.id)
                )
                or 0
            )
            project.semantic_master_id = master.id
            project.research_package_id = master.research_package_id
            project.target_duration_minutes = target_minutes
            project.owner_prompt = owner_prompt

        outline, context, evidence_texts = self._generation_context(
            export, lesson_package, target_minutes
        )
        result: list[UUID] = []
        for offset in range(1, draft_count + 1):
            raw_text = await self._generate_text(
                outline,
                context,
                owner_prompt,
                target_min,
                target_max,
                existing_variants + offset,
            )
            initial_quality = self.quality.validate(raw_text, evidence_texts)
            review = review_bundle(
                raw_text,
                lesson_package,
                external_evidence_count=len(evidence_texts),
                published=published_memory,
                ledger_entries_checked=ledger_count,
            )
            review_findings = list(review.findings)
            blocking_before_optimization = any(
                item.blocking and item.category != "NATIVE_PERSIAN"
                for item in review_findings
            )
            text = raw_text
            optimized = False
            if not blocking_before_optimization:
                text = await self.optimizer.optimize(
                    raw_text,
                    review_findings,
                    lesson_package,
                    semantic_constraints=[
                        "Do not redefine canonical lesson distinctions",
                        "Do not present external theories as Ayin",
                        "Preserve uncertainty and protected terminology",
                        "Keep one central intellectual movement",
                    ],
                    owner_style_rules=owner_prompt,
                )
                optimized = text != raw_text
            final_quality = self.quality.validate(text, evidence_texts)
            final_findings = final_semantic_findings(
                text,
                lesson_package,
                external_evidence_count=len(evidence_texts),
            )
            findings = self._pipeline_findings(
                initial_quality,
                review_findings,
                final_quality,
                final_findings,
            )
            count = _word_count(text)
            duration_in_range = target_min <= count <= target_max
            if not duration_in_range:
                findings.append(
                    PipelineFinding(
                        "DURATION_OUT_OF_RANGE",
                        "EDITORIAL_DURATION",
                        "WARNING",
                        "Der Entwurf liegt außerhalb der gewünschten Sprechdauer.",
                    )
                )
            blocking = any(item.blocking for item in findings)
            async with self.database.transaction() as session:
                project = await session.get(EditorialProject, project_id)
                if project is None:
                    raise RuntimeError("editorial project disappeared")
                draft = PersianDraft(
                    editorial_project_id=project.id,
                    semantic_master_id=master.id,
                    version_number=1,
                    variant_index=existing_variants + offset,
                    text=text,
                    status="REVIEW_REQUIRED" if blocking else "PROPOSED",
                    owner_prompt=owner_prompt,
                    target_duration_minutes=target_minutes,
                    target_word_count_min=target_min,
                    target_word_count_max=target_max,
                    actual_word_count=count,
                    estimated_duration_seconds=round(count / 110 * 60),
                    provenance={
                        "research_package_id": str(master.research_package_id),
                        "semantic_master_id": str(master.id),
                        "lesson_id": lesson_package.lesson_id,
                        "lesson_canon_hash": lesson_package.lesson_canon_hash,
                        "lesson_content_package_version": (
                            lesson_package.package_version
                        ),
                        "lesson_content_package": lesson_package.model_dump(
                            mode="json"
                        ),
                        "canonical_title": lesson_package.canonical_lesson_title,
                        "lesson_provenance_complete": (
                            lesson_package.provenance_complete
                        ),
                        "lesson_review_items": lesson_package.review_items,
                        "generation_context_roles": [
                            "CANONICAL_LESSON_CONTENT",
                            "CORE_CONCEPT_REGISTRY",
                            "EXTERNAL_RESEARCH",
                        ],
                        "review_only_roles": [
                            "CHANNEL_LEDGER",
                            "PUBLISHED_SCRIPT_ARCHIVE",
                            "LESSON_RELATIONS",
                        ],
                        "owner_prompt": owner_prompt,
                        "generator": "codex-lesson-synthesis-v3",
                        "outline": outline.model_dump(mode="json"),
                        "outline_hash": outline.content_hash,
                        "raw_draft_hash": sha256(raw_text.encode()).hexdigest(),
                        "native_optimization_applied": optimized,
                        "quality_repetition_ratio": final_quality.repetition_ratio,
                        "duration_in_target_range": duration_in_range,
                        "duration_deviation_percent": round(
                            abs(count - target_minutes * 110)
                            / max(target_minutes * 110, 1)
                            * 100,
                            1,
                        ),
                        "evidence_item_ids": [
                            str(item.get("id"))
                            for item in export.evidence
                            if str(item.get("evidence_kind", "")) == "EXTERNAL_CHUNK"
                        ],
                        "variant_index": existing_variants + offset,
                        "review_completed": True,
                        "published_archive_items_checked": (
                            review.published_items_checked
                        ),
                        "channel_ledger_entries_checked": (
                            review.ledger_entries_checked
                        ),
                        "explicit_ayin_reference_estimate": (
                            review.explicit_ayin_ratio
                        ),
                        "review_findings": [
                            self._finding_payload(item) for item in findings
                        ],
                        "final_semantic_validation": (
                            "REVIEW_REQUIRED" if blocking else "PASSED"
                        ),
                    },
                )
                session.add(draft)
                await session.flush()
                session.add_all(
                    [
                        PersianReviewFinding(
                            draft_id=draft.id,
                            code=item.code,
                            severity=item.severity,
                            message=f"[{item.category}] {item.message}",
                            blocking=item.blocking,
                        )
                        for item in findings
                    ]
                )
                project.status = "PERSIAN_REVIEW"
                result.append(draft.id)
        return result

    def _generation_context(
        self,
        export: SemanticLectureMasterExport,
        lesson_package: LessonContentPackage,
        target_minutes: int,
    ) -> tuple[ScriptOutline, str, list[str]]:
        claims = export.claims
        evidence = export.evidence
        claim_items: list[dict[str, str]] = []
        seen: set[str] = set()
        for claim in claims:
            if str(claim.get("claim_origin", "")) != "EXTERNAL":
                continue
            raw = str(
                claim.get("source_support_summary")
                or claim.get("semantic_proposition")
                or ""
            )
            cleaned = clean_source_text(raw)
            cleaned = re.sub(
                r"^(The external source provides (?:evidence|a counterpoint) "
                r"relevant to the question:\s*)",
                "",
                cleaned,
                flags=re.IGNORECASE,
            ).strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                claim_items.append(
                    {
                        "origin": str(claim.get("claim_origin", "UNKNOWN")),
                        "status": str(claim.get("epistemic_status", "UNKNOWN")),
                        "meaning": cleaned[:1000],
                    }
                )
        evidence_items: list[str] = []
        evidence_context: list[dict[str, object]] = []
        for item in evidence:
            if str(item.get("evidence_kind", "")) != "EXTERNAL_CHUNK":
                continue
            text = clean_source_text(str(item.get("text") or ""))
            if text and text not in evidence_items:
                evidence_items.append(text[:700])
                evidence_context.append(
                    {
                        "source_class": str(
                            item.get("source_class")
                            or item.get("corpus_zone")
                            or item.get("lane")
                            or item.get("evidence_role")
                            or "UNKNOWN"
                        ),
                        "authority_status": str(
                            item.get("authority_status") or "UNKNOWN"
                        ),
                        "source_title": str(item.get("source_title") or ""),
                        "creator": str(item.get("creator") or ""),
                        "source_url": str(item.get("source_url") or ""),
                        "location": {
                            "page_start": item.get("page_start"),
                            "page_end": item.get("page_end"),
                            "timestamp_start": item.get("timestamp_start"),
                            "timestamp_end": item.get("timestamp_end"),
                        },
                        "text": text[:700],
                    }
                )
        diversity = self._diversity_plan(lesson_package.lesson_id)
        counter_claim = next(
            (
                item["meaning"]
                for item in claim_items
                if item.get("status") == "COUNTEREVIDENCE"
            ),
            "Keep the strongest limitation or alternative explanation visible.",
        )
        external_perspective = (
            str(evidence_context[0].get("source_title") or "")
            if evidence_context
            else "No external perspective may be invented."
        )
        central_movement = (
            lesson_package.what_this_lesson_develops[0]
            if lesson_package.what_this_lesson_develops
            else lesson_package.central_question
            or lesson_package.canonical_lesson_title
        )
        ending = (
            lesson_package.what_should_remain_open[0]
            if lesson_package.what_should_remain_open
            else diversity["ending"]
        )
        outline = ScriptOutline(
            canonical_title=lesson_package.canonical_lesson_title,
            opening_human_situation=diversity["rhetorical_opening"],
            central_intellectual_movement=central_movement,
            ayin_contribution=(
                "Transform the canonical explanation into natural prose without "
                "redefining or recreating its Ayin core."
            ),
            external_perspective=external_perspective,
            tension_or_counterposition=counter_claim,
            example_strategy="Use one concrete example selected for this lesson only.",
            transition_logic=[
                diversity["argument_structure"],
                (
                    "Integrate external context into the argument rather than "
                    "summarizing it."
                ),
                diversity["emotional_movement"],
            ],
            ending_open_question=ending,
            diversity_profile=diversity,
        )
        context = json.dumps(
            {
                "human_question": (
                    lesson_package.central_question
                    or export.master.get("central_human_question", "")
                ),
                "target_minutes": target_minutes,
                "canonical_lesson_content": lesson_package.model_dump(
                    mode="json",
                    exclude={
                        "core_concept_registry",
                        "lesson_relations",
                        "canonical_relations_section_fa",
                        "review_items",
                    },
                ),
                "core_concept_registry": [
                    item.model_dump(mode="json")
                    for item in lesson_package.core_concept_registry
                ],
                "external_research": {
                    "claims": claim_items,
                    "evidence": evidence_context[:20],
                    "dialogue_relations": export.dialogue_relations[:10],
                },
                "diversity_plan": diversity,
                "script_outline": outline.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        return outline, context, evidence_items

    @staticmethod
    def _diversity_plan(lesson_id: str) -> dict[str, str]:
        """Select a stable combination without imposing one series-wide template."""

        openings = (
            "Open with a concrete everyday scene and delay abstraction.",
            "Open with the lesson's human question, without answering it at once.",
            "Open with a quiet contradiction the listener may recognize.",
            "Open with two contrasting responses to the same situation.",
            "Open with a precise observation about relationship, body, or history.",
            "Open by naming an honest uncertainty rather than a conclusion.",
        )
        structures = (
            "Move from scene to distinction, then test the distinction at its limit.",
            "Compare two plausible readings before developing the canonical boundary.",
            "Build through three consequences, each grounded in a different example.",
            "Follow one question as it changes from personal to relational to ethical.",
            (
                "Start with a common explanation, expose its limit, then offer "
                "the Ayin lens."
            ),
            "Develop as a dialogue between the canon and one external perspective.",
        )
        movements = (
            "Move from pressure toward clarity without promising relief.",
            "Move from familiarity toward productive strangeness and curiosity.",
            (
                "Move from individual experience toward relationship and shared "
                "conditions."
            ),
            "Move from certainty toward a more honest, bounded open question.",
            "Move from heaviness toward realistic Majal without motivational uplift.",
            "Move from conceptual tension toward compassion and responsibility.",
        )
        endings = (
            "End by returning to the opening scene with one detail newly visible.",
            "End on an unresolved question preserved by the lesson canon.",
            "End with a restrained observation, not advice or a summary.",
            "End by showing what changes when one distinction is kept intact.",
            "End with a concrete possibility that remains conditional and limited.",
            "End by widening from the self to the Other without closing the argument.",
        )
        digest = sha256(lesson_id.encode()).digest()
        return {
            "rhetorical_opening": openings[digest[0] % len(openings)],
            "argument_structure": structures[digest[1] % len(structures)],
            "emotional_movement": movements[digest[2] % len(movements)],
            "ending": endings[digest[3] % len(endings)],
        }

    async def _generate_text(
        self,
        outline: ScriptOutline,
        context: str,
        owner_prompt: str | None,
        target_min: int,
        target_max: int,
        variant: int,
    ) -> str:
        variant_styles = (
            "طرح تنوع انتخاب‌شده را با جزئیات عینی و ریتمی آرام اجرا کن.",
            "طرح تنوع انتخاب‌شده را با حرکت استدلالی روشن و مرحله‌به‌مرحله اجرا کن.",
            (
                "طرح تنوع انتخاب‌شده را با رفت‌وبرگشت میان تجربه، مفهوم و "
                "محدودیت‌ها اجرا کن."
            ),
        )
        style = variant_styles[(variant - 1) % len(variant_styles)]
        instructions = (
            MASTER_PERSIAN_WRITING_PROMPT + "\n\n"
            "یک پیش‌نویس سخنرانی فارسی طبیعی و معاصر تولید کن. خروجی فقط متن نهایی "
            "سخنرانی باشد؛ هیچ عنوان فنی، JSON، فهرست شواهد یا توضیح درباره "
            "فرایند پژوهش "
            "ننویس. "
            "فاصله‌گذاری و نیم‌فاصله‌گذاری طبیعی و درست فارسی را رعایت کن. "
            "از برچسب‌هایی مانند ResearchPackage، Semantic Master، منبع انتخاب‌شده، "
            "قطعه بازیابی‌شده، یا «منبع خارجی می‌گوید» استفاده نکن. شواهد را فقط برای "
            "فهم "
            "و ساختن استدلال به‌کار ببر و هرگز متن شواهد را پشت سر هم کپی نکن. Ayin را "
            "به‌عنوان چارچوب خودش معرفی کن؛ علم آن را اثبات نمی‌کند. ادعاهای بیرونی را "
            "فقط "
            "در صورت نیاز و با انتساب محتاطانه بیاور. تفاوت مفهومی و سؤال باز "
            "را حفظ کن. متن باید در بازه تقریبی "
            f"{target_min} تا {target_max} واژه فارسی باشد. "
            f"{style} "
            f"دستور صاحب اثر: {owner_prompt or 'بدون دستور اضافی'}\n\n"
            "طرح داخلی (هرگز آن را در خروجی بازگو نکن):\n"
            f"{json.dumps(outline.model_dump(mode='json'), ensure_ascii=False)}\n\n"
            "ورودی ساختاری شامل بسته مستقیم درس، واژه‌نامه مفاهیم و فقط پژوهش "
            "بیرونی است. آن را بازگو نکن؛ از آن برای نوشتن متن نهایی استفاده کن."
        )
        result = cast(
            _PersianDraftOutput,
            await self.provider.extract(
                StructuredExtractionRequest(
                    task="Persian editorial lecture synthesis",
                    prompt_version="phase-12-persian-synthesis-v2",
                    model="configured-default",
                    instructions=instructions,
                    input_text=context,
                    output_model=_PersianDraftOutput,
                    timeout_seconds=300,
                )
            ),
        )
        return clean_source_text(result.text)

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
        result: list[PipelineFinding] = []
        seen: set[tuple[str, str]] = set()
        for item in findings:
            key = (item.code, item.message)
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

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
        async with self.database.transaction() as session:
            draft = await session.get(PersianDraft, draft_id)
            if draft is None:
                raise ValueError("draft not found")
            project = await session.get(EditorialProject, draft.editorial_project_id)
            if project is None:
                raise ValueError("editorial project not found")
            lesson = self._lesson_package_for_review(project, draft)
            if lesson is None:
                raise ValueError("canonical lesson package is required")
            published_memory, ledger_count = await PublishedMemoryReader.load(session)
            master_id = draft.semantic_master_id
            target_minutes = draft.target_duration_minutes
            text = draft.text

        export = await self.masters.export(master_id)
        _, _, evidence_texts = self._generation_context(export, lesson, target_minutes)
        quality = self.quality.validate(text, evidence_texts)
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
                "published_archive_items_checked": review.published_items_checked,
                "channel_ledger_entries_checked": review.ledger_entries_checked,
                "explicit_ayin_reference_estimate": review.explicit_ayin_ratio,
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
