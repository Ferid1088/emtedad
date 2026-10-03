"""Independent critics, findings, revision, and the approval gate."""

import hashlib
import json
import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.briefs.models import ContentBrief
from app.content_engine.domain import (
    CRITIC_PROMPT_VERSION,
    REVISION_PROMPT_VERSION,
    SCRIPT_PROMPT_VERSION,
    CriticRole,
    DraftStatus,
    FindingSeverity,
    FindingStatus,
)
from app.content_engine.models import (
    ArgumentPlan,
    NarrativePlan,
    ReviewFinding,
    ScriptDraft,
)
from app.content_engine.service import GateBlockedError
from app.content_engine.writing.diversity import ScriptDiversityValidator
from app.content_engine.writing.findings import PipelineFinding
from app.content_engine.writing.memory import (
    PublishedMemoryItem,
    PublishedMemoryReader,
    ScriptDraftMemoryReader,
)
from app.content_engine.writing.native import PersianNativeReviewer
from app.content_engine.writing.prompts import (
    EMTEDAD_VOICE_CONTRACT,
    PERSIAN_VOICE_CONTRACT,
)
from app.content_engine.writing.quality import (
    PersianDraftQualityValidator,
    duration_findings,
)
from app.db.session import Database
from app.editorial_channels.models import (
    ChannelStrategyVersion,
    EditorialChannel,
)
from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.knowledge.llm.factory import resolve_llm_provider
from app.lecture.domain import MasterOriginType, MasterStatus
from app.lecture.models import (
    LectureClaim,
    LectureMasterVersion,
    LectureSection,
)
from app.research.models import EvidenceMatrixItem
from app.topics.signature import ensure_signature_for_draft

# Channel-specific review packs (§16): only the selected channel's checks run.
CHANNEL_REVIEW_CHECKS: dict[str, tuple[str, ...]] = {
    "emtedad": (
        "conceptual continuity",
        "meaning/interpretation boundary",
        "Ayin source fidelity when Ayin is explicitly used",
    ),
    "science-mystery": (
        "epistemic status check",
        "overclaim check",
        "alternative explanation check",
        "science/philosophy boundary check",
    ),
    "history-human-stories": (
        "timeline consistency",
        "source conflict",
        "causal overclaim",
        "anachronism check",
    ),
    "pop-psychology-relationships": (
        "evidence strength",
        "overgeneralization",
        "practical advice safety",
        "gender stereotype check",
    ),
    "psychology-evolution": (
        "adaptationism check",
        "culture/biology alternative",
        "individual-differences check",
    ),
}


class FindingProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str = Field(min_length=1)
    code: str = Field(min_length=1, max_length=128)
    severity: FindingSeverity
    explanation: str = Field(min_length=1)
    correction_constraint: str = ""


class ReviewFindingsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[FindingProposal] = Field(default_factory=list)


class ScriptDraftOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    estimated_duration_seconds: int = Field(default=0, ge=0)


class RevisionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)


SCRIPT_INSTRUCTIONS = """Write a complete script draft for the given channel \
production. Follow the narrative plan order and target seconds. Honor every \
must_include / must_not_claim and the brief's forbidden claims. Write in \
the requested language. Return only the script text and a duration \
estimate."""


CRITIC_INSTRUCTIONS = """You are the {role} critic for one editorial channel \
production. Review the script draft against the brief, the plan summaries, \
and these checks: {checks}. Report findings only — never rewrite. Each \
finding: location (quote or section ref), code, severity \
(INFO|WARNING|BLOCKER), explanation, correction_constraint."""


REVISION_INSTRUCTIONS = """Revise the script to satisfy every OPEN finding's \
correction constraint. Do not change anything else. Return the full \
revised text."""


def _script_instructions(channel_slug: str, language: str) -> str:
    """Compose writer instructions: voice contracts apply to fa drafts only."""

    instructions = SCRIPT_INSTRUCTIONS
    if language == "fa":
        instructions += "\n\n" + PERSIAN_VOICE_CONTRACT
        if channel_slug == "emtedad":
            instructions += "\n\n" + EMTEDAD_VOICE_CONTRACT
    return instructions


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _words(text: str) -> int:
    return len(re.findall(r"\S+", text))


async def _channel_checks(
    session: AsyncSession, brief: ContentBrief
) -> tuple[str, ...]:
    """Review checks for the brief's channel only (§16)."""

    strategy = await session.get(ChannelStrategyVersion, brief.strategy_version_id)
    if strategy is None:
        return ()
    channel = await session.get(EditorialChannel, strategy.editorial_channel_id)
    slug = channel.slug if channel is not None else ""
    return CHANNEL_REVIEW_CHECKS.get(slug, ())


async def _persian_findings(
    session: AsyncSession, draft: ScriptDraft, brief: ContentBrief | None
) -> list[PipelineFinding]:
    """Deterministic Persian checks: scaffolding, nativeness, duration, memory."""

    evidence_texts: list[str] = []
    if draft.narrative_plan_id is not None:
        narrative = await session.get(NarrativePlan, draft.narrative_plan_id)
        argument = (
            await session.get(ArgumentPlan, narrative.argument_plan_id)
            if narrative is not None
            else None
        )
        if argument is not None:
            items = list(
                await session.scalars(
                    select(EvidenceMatrixItem).where(
                        EvidenceMatrixItem.evidence_matrix_id
                        == argument.evidence_matrix_id
                    )
                )
            )
            evidence_texts = [item.claim_text for item in items]
    findings = [
        PipelineFinding(
            item.code,
            "DRAFT_QUALITY",
            "ERROR" if item.blocking else "WARNING",
            item.message,
            blocking=item.blocking,
        )
        for item in PersianDraftQualityValidator()
        .validate(draft.text, evidence_texts)
        .findings
    ]
    findings.extend(PersianNativeReviewer().review(draft.text))
    published, _ = await PublishedMemoryReader.load(session)
    memory: list[PublishedMemoryItem] = [
        item for item in published if item.text != draft.text
    ]
    memory.extend(
        await ScriptDraftMemoryReader.load(
            session, exclude_brief_id=draft.content_brief_id
        )
    )
    findings.extend(ScriptDiversityValidator().validate(draft.text, memory))
    if brief is not None:
        duration, _count = duration_findings(draft.text, brief.target_duration_minutes)
        findings.extend(duration)
    return findings


class ScriptService:
    """Generic Phase 14/15 pipeline: draft → critics → revise → approve."""

    def __init__(
        self,
        database: Database,
        *,
        provider: LLMProvider | None = None,
        model: str = "configured-default",
    ) -> None:
        self.database = database
        self.provider = provider
        self.model = model

    async def build_script(
        self,
        brief_id: UUID,
        *,
        language: str = "fa",
        style_instruction: str | None = None,
    ) -> ScriptDraft:
        """Write a new draft — gated on a READY generic Semantic Master."""

        async with self.database.transaction() as session:
            brief = await session.get(ContentBrief, brief_id)
            if brief is None:
                raise LookupError(f"Unknown content brief {brief_id}")
            channel = await session.get(EditorialChannel, brief.editorial_channel_id)
            channel_slug = channel.slug if channel is not None else ""
            master = await session.scalar(
                select(LectureMasterVersion)
                .where(
                    LectureMasterVersion.content_brief_id == brief_id,
                    LectureMasterVersion.origin_type == MasterOriginType.CONTENT_BRIEF,
                    LectureMasterVersion.status == MasterStatus.READY,
                )
                .order_by(LectureMasterVersion.version_number.desc())
                .limit(1)
            )
            if master is None:
                raise GateBlockedError("Cannot build script: no ready Semantic Master")
            plan = await session.get(NarrativePlan, master.narrative_plan_id)
            if plan is None:
                raise GateBlockedError(
                    "Cannot build script: master has no NarrativePlan"
                )
            sections = list(
                (
                    await session.scalars(
                        select(LectureSection)
                        .where(LectureSection.lecture_master_version_id == master.id)
                        .order_by(LectureSection.ordinal)
                    )
                ).all()
            )
            claims = list(
                (
                    await session.scalars(
                        select(LectureClaim)
                        .where(LectureClaim.lecture_master_version_id == master.id)
                        .order_by(LectureClaim.sequence)
                    )
                ).all()
            )
            payload = {
                "brief": {
                    "question": brief.question,
                    "thesis": brief.thesis,
                    "angle": brief.angle,
                    "target_duration_minutes": brief.target_duration_minutes,
                    "forbidden_claims": brief.forbidden_claims_json,
                },
                "semantic_master": {
                    "sections": [
                        {
                            "ordinal": s.ordinal,
                            "role": s.role.value,
                            "narrative_role": s.rhetorical_function,
                            "purpose": s.purpose,
                            "duration_seconds": s.duration_seconds,
                            "transition_intent": s.transition_intent,
                            "prohibited_formulations": (s.prohibited_formulations),
                        }
                        for s in sections
                    ],
                    "claims": [
                        {
                            "proposition": claim.semantic_proposition,
                            "epistemic_status": claim.epistemic_status.value,
                            "qualifiers": claim.required_qualifiers,
                            "prohibited": claim.prohibited_overstatements,
                            "constraints": claim.formulation_constraints,
                        }
                        for claim in claims
                    ],
                    "uncertainty_constraints": master.uncertainty_constraints,
                    "channel_constraints": master.architecture.get(
                        "semantic_constraints", []
                    ),
                    "distinctiveness": master.architecture.get("distinctiveness", {}),
                    "ending_mode": master.ending_mode,
                },
                "style_instruction": style_instruction,
                "language": language,
            }
            provider = self.provider or resolve_llm_provider()
            result = await provider.extract(
                StructuredExtractionRequest(
                    task="script_draft",
                    prompt_version=SCRIPT_PROMPT_VERSION,
                    model=self.model,
                    instructions=_script_instructions(channel_slug, language),
                    input_text=json.dumps(payload, ensure_ascii=False),
                    output_model=ScriptDraftOutput,
                )
            )
            draft = ScriptDraftOutput.model_validate(result.model_dump())
            version = (
                await session.scalar(
                    select(
                        func.coalesce(func.max(ScriptDraft.version_number), 0)
                    ).where(
                        ScriptDraft.content_brief_id == brief_id,
                        ScriptDraft.language == language,
                    )
                )
                or 0
            ) + 1
            words = _words(draft.text)
            row = ScriptDraft(
                content_brief_id=brief_id,
                narrative_plan_id=plan.id,
                lecture_master_version_id=master.id,
                language=language,
                version_number=version,
                text=draft.text,
                status=DraftStatus.DRAFT,
                provenance_json={
                    "model": self.model,
                    "narrative_plan_version": plan.version_number,
                    "lecture_master_version": master.version_number,
                    "style_instruction": style_instruction,
                },
                content_hash=_hash(draft.text),
                target_duration_minutes=brief.target_duration_minutes,
                actual_word_count=words,
                estimated_duration_seconds=(
                    draft.estimated_duration_seconds or int(words / 2.5)
                ),
            )
            session.add(row)
            return row

    async def review_draft(self, draft_id: UUID) -> list[ReviewFinding]:
        """Run every critic role; persist findings. Critics never rewrite."""

        async with self.database.transaction() as session:
            draft = await session.get(ScriptDraft, draft_id)
            if draft is None:
                raise LookupError(f"Unknown script draft {draft_id}")
            brief = await session.get(ContentBrief, draft.content_brief_id)
            checks = await _channel_checks(session, brief) if brief else ()
            provider = self.provider or resolve_llm_provider()
            findings: list[ReviewFinding] = []
            for role in CriticRole:
                role_checks = checks if role is CriticRole.CHANNEL_SPECIFIC else ()
                result = await provider.extract(
                    StructuredExtractionRequest(
                        task="script_review",
                        prompt_version=CRITIC_PROMPT_VERSION,
                        model=self.model,
                        instructions=CRITIC_INSTRUCTIONS.format(
                            role=role.value, checks=", ".join(role_checks)
                        ),
                        input_text=json.dumps(
                            {"draft": draft.text}, ensure_ascii=False
                        ),
                        output_model=ReviewFindingsOutput,
                    )
                )
                output = ReviewFindingsOutput.model_validate(result.model_dump())
                for proposal in output.findings:
                    finding = ReviewFinding(
                        script_draft_id=draft.id,
                        critic_role=role.value,
                        severity=proposal.severity,
                        location=proposal.location,
                        code=proposal.code,
                        explanation=proposal.explanation,
                        correction_constraint=proposal.correction_constraint,
                    )
                    session.add(finding)
                    findings.append(finding)
            if draft.language == "fa":
                for check in await _persian_findings(session, draft, brief):
                    finding = ReviewFinding(
                        script_draft_id=draft.id,
                        critic_role=CriticRole.PERSIAN_QUALITY.value,
                        severity=(
                            FindingSeverity.BLOCKER
                            if check.blocking
                            else (
                                FindingSeverity.WARNING
                                if check.severity in {"WARNING", "ERROR"}
                                else FindingSeverity.INFO
                            )
                        ),
                        location=check.category,
                        code=check.code,
                        explanation=check.message,
                        correction_constraint=(
                            "Rewrite or correct the flagged passage; do not "
                            "change claims or structure."
                        ),
                    )
                    session.add(finding)
                    findings.append(finding)
            draft.status = DraftStatus.IN_REVIEW
            return findings

    async def revise_draft(self, draft_id: UUID) -> ScriptDraft:
        """Create a new draft version addressing all OPEN findings."""

        async with self.database.transaction() as session:
            draft = await session.get(ScriptDraft, draft_id)
            if draft is None:
                raise LookupError(f"Unknown script draft {draft_id}")
            open_findings = list(
                (
                    await session.scalars(
                        select(ReviewFinding).where(
                            ReviewFinding.script_draft_id == draft_id,
                            ReviewFinding.status == FindingStatus.OPEN,
                        )
                    )
                ).all()
            )
            if not open_findings:
                return draft
            provider = self.provider or resolve_llm_provider()
            result = await provider.extract(
                StructuredExtractionRequest(
                    task="script_revision",
                    prompt_version=REVISION_PROMPT_VERSION,
                    model=self.model,
                    instructions=REVISION_INSTRUCTIONS,
                    input_text=json.dumps(
                        {
                            "draft": draft.text,
                            "findings": [
                                {
                                    "location": f.location,
                                    "code": f.code,
                                    "correction_constraint": (f.correction_constraint),
                                }
                                for f in open_findings
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    output_model=RevisionOutput,
                )
            )
            revised = RevisionOutput.model_validate(result.model_dump())
            row = ScriptDraft(
                content_brief_id=draft.content_brief_id,
                narrative_plan_id=draft.narrative_plan_id,
                lecture_master_version_id=draft.lecture_master_version_id,
                editorial_project_id=draft.editorial_project_id,
                language=draft.language,
                version_number=draft.version_number + 1,
                variant_index=draft.variant_index,
                text=revised.text,
                status=DraftStatus.REVISED,
                provenance_json={
                    **draft.provenance_json,
                    "revised_from_draft": str(draft.id),
                    "addressed_finding_ids": [str(f.id) for f in open_findings],
                },
                content_hash=_hash(revised.text),
                target_duration_minutes=draft.target_duration_minutes,
                actual_word_count=_words(revised.text),
                estimated_duration_seconds=int(_words(revised.text) / 2.5),
            )
            session.add(row)
            for finding in open_findings:
                finding.status = FindingStatus.ADDRESSED
            draft.status = DraftStatus.ARCHIVED
            return row

    async def approve_draft(self, draft_id: UUID) -> ScriptDraft:
        """Approve only when no OPEN blocking findings exist."""

        async with self.database.transaction() as session:
            draft = await session.get(ScriptDraft, draft_id)
            if draft is None:
                raise LookupError(f"Unknown script draft {draft_id}")
            blocking = await session.scalar(
                select(func.count(ReviewFinding.id)).where(
                    ReviewFinding.script_draft_id == draft_id,
                    ReviewFinding.severity == FindingSeverity.BLOCKER,
                    ReviewFinding.status == FindingStatus.OPEN,
                )
            )
            if blocking:
                raise GateBlockedError(f"{blocking} blocking findings remain open")
            draft.status = DraftStatus.APPROVED
            # Owner approval is the authoritative publish-boundary: record the
            # semantic signature for future distinctiveness comparisons.
            await ensure_signature_for_draft(session, draft)
            return draft
