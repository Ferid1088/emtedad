"""Research-bound Persian draft and owner approval workflow."""

import json
import re
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from app.content_strategy.models import (
    EditorialProject,
    PersianDraft,
    PersianReviewFinding,
)
from app.content_strategy.persian_quality import (
    PersianDraftQualityValidator,
    clean_source_text,
)
from app.db.session import Database
from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.llm.codex import CodexCliProvider
from app.lecture.models import LectureMasterVersion
from app.lecture.schemas import SemanticLectureMasterExport
from app.lecture.service import LectureMasterService


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
        self.quality = PersianDraftQualityValidator()

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
        outline, context, evidence_texts = self._generation_context(
            export, target_minutes
        )
        target_min = round(target_minutes * 99)
        target_max = round(target_minutes * 121)
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
                text = await self._generate_text(
                    export,
                    outline,
                    context,
                    owner_prompt,
                    target_min,
                    target_max,
                    variant,
                )
                report = self.quality.validate(text, evidence_texts)
                if not report.valid:
                    raise ValueError(
                        "Persian draft quality validation failed: "
                        + ", ".join(item.code for item in report.findings)
                    )
                count = _word_count(text)
                duration_in_range = target_min <= count <= target_max
                draft = PersianDraft(
                    editorial_project_id=project.id,
                    semantic_master_id=master.id,
                    version_number=1,
                    variant_index=variant,
                    text=text,
                    status="PROPOSED" if duration_in_range else "REVIEW_REQUIRED",
                    owner_prompt=owner_prompt,
                    target_duration_minutes=target_minutes,
                    target_word_count_min=target_min,
                    target_word_count_max=target_max,
                    actual_word_count=count,
                    estimated_duration_seconds=round(count / 110 * 60),
                    provenance={
                        "research_package_id": str(master.research_package_id),
                        "semantic_master_id": str(master.id),
                        "owner_prompt": owner_prompt,
                        "generator": "codex-persian-synthesis-v1",
                        "outline": outline,
                        "quality_repetition_ratio": report.repetition_ratio,
                        "duration_in_target_range": duration_in_range,
                        "duration_deviation_percent": round(
                            abs(count - target_minutes * 110)
                            / max(target_minutes * 110, 1)
                            * 100,
                            1,
                        ),
                        "evidence_item_ids": [
                            str(item.get("id")) for item in export.evidence
                        ],
                        "variant_index": variant,
                    },
                )
                session.add(draft)
                await session.flush()
                result.append(draft.id)
            return result

    def _generation_context(
        self, export: SemanticLectureMasterExport, target_minutes: int
    ) -> tuple[list[dict[str, str]], str, list[str]]:
        claims = export.claims
        sections = export.sections
        evidence = export.evidence
        claim_items: list[dict[str, str]] = []
        seen: set[str] = set()
        for claim in claims:
            raw = str(
                claim.get("plain_meaning") or claim.get("semantic_proposition") or ""
            )
            cleaned = clean_source_text(raw)
            cleaned = re.sub(
                r"^(The selected Ayin Working source states the following material:"
                r"\s*)",
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
        evidence_context: list[dict[str, str]] = []
        for item in evidence:
            text = clean_source_text(str(item.get("text") or ""))
            if text and text not in evidence_items:
                evidence_items.append(text[:700])
                evidence_context.append(
                    {
                        "source_class": str(
                            item.get("source_class")
                            or item.get("lane")
                            or item.get("evidence_role")
                            or "UNKNOWN"
                        ),
                        "authority_status": str(
                            item.get("authority_status") or "UNKNOWN"
                        ),
                        "text": text[:700],
                    }
                )
        outline = [
            {
                "role": "opening",
                "intent": (
                    "Begin with a concrete everyday experience that opens "
                    "the human question."
                ),
            },
            {
                "role": "ayin_frame",
                "intent": (
                    "Explain the Ayin Working concepts in original Persian prose "
                    "and preserve their distinctions."
                ),
            },
            {
                "role": "development",
                "intent": (
                    "Develop the question through conditions, responses, "
                    "and a grounded example."
                ),
            },
            {
                "role": "dialogue_and_limit",
                "intent": (
                    "If useful, mention external material as attributed context; "
                    "do not present it as proof of Ayin."
                ),
            },
            {
                "role": "open_return",
                "intent": (
                    "Return to lived experience and leave the Semantic Master's "
                    "open question genuinely open."
                ),
            },
            {
                "role": "conclusion",
                "intent": (
                    "End with a clear, non-preachy invitation to notice "
                    "the question in life."
                ),
            },
        ]
        context = json.dumps(
            {
                "central_question": export.master.get("central_human_question", ""),
                "target_minutes": target_minutes,
                "sections": [
                    {
                        "role": str(section.get("role", "")),
                        "purpose": clean_source_text(str(section.get("purpose", ""))),
                    }
                    for section in sections
                ],
                "semantic_claims": claim_items,
                "evidence_context": evidence_context[:20],
                "authority": export.master.get("package_authority", {}),
                "dialogue_relations": export.dialogue_relations[:10],
            },
            ensure_ascii=False,
        )
        return outline, context, evidence_items

    async def _generate_text(
        self,
        export: SemanticLectureMasterExport,
        outline: list[dict[str, str]],
        context: str,
        owner_prompt: str | None,
        target_min: int,
        target_max: int,
        variant: int,
    ) -> str:
        variant_styles = (
            "با یک صحنه روزمره آغاز کن و سپس آرام‌آرام به مفهوم برس.",
            "با یک پرسش مستقیم آغاز کن و حرکت استدلالی را روشن و مرحله‌به‌مرحله نگه دار.",
            (
                "با یک تصویر رابطه‌ای آغاز کن و میان تجربه، مفهوم و محدودیت‌ها "
                "رفت‌وبرگشت ایجاد کن."
            ),
        )
        style = variant_styles[(variant - 1) % len(variant_styles)]
        instructions = (
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
            f"{json.dumps(outline, ensure_ascii=False)}\n\n"
            "زمینه پژوهشی پاک‌سازی‌شده:\n"
            f"{context}"
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
