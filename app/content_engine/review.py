"""Independent critics, findings, revision, and the approval gate."""

import hashlib
import json
import logging
import time
import unicodedata
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
    ReviewRunStatus,
)
from app.content_engine.models import (
    ArgumentPlan,
    ArgumentPlanSection,
    NarrativePlan,
    NarrativePlanSection,
    ReviewCycle,
    ReviewFinding,
    ReviewRun,
    ScriptDraft,
)
from app.content_engine.service import GateBlockedError
from app.content_engine.writing.books import (
    BOOK_REFERENCE_CHECKS,
    BOOK_REFERENCE_SELECTION_INSTRUCTIONS,
    BOOK_REFERENCE_WRITER_POLICY,
    BookReference,
    BookReferenceSelection,
    allowed_book_references,
    book_reference_findings,
)
from app.content_engine.writing.diversity import ScriptDiversityValidator
from app.content_engine.writing.findings import PipelineFinding
from app.content_engine.writing.generation import validate_generation
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
    word_count,
)
from app.db.session import Database
from app.editorial_channels.models import (
    ChannelStrategyVersion,
    EditorialChannel,
)
from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.knowledge.llm.factory import resolve_llm_provider
from app.knowledge.units.models import KnowledgeUnit
from app.lecture.domain import MasterOriginType, MasterStatus
from app.lecture.models import (
    LectureClaim,
    LectureMasterVersion,
    LectureSection,
)
from app.ops.assets.models import utc_now
from app.ops.settings.service import StudioSettingsService, speech_wpm
from app.research.models import EvidenceMatrixItem
from app.topics.signature import ensure_signature_for_draft

log = logging.getLogger(__name__)

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
production. This is a SPOKEN script with a hard duration contract: the \
total must land inside the given duration band (target_duration_minutes \
× speech_wpm words per minute; the allowed word range is given as \
generation_band_words). Satisfy the semantic master and the narrative \
plan while naturally filling the allocated spoken time — deepen scenes, \
explanations, evidence context, and transitions; never pad, repeat \
conclusions, or add filler to reach length. Write approximately the \
target word count for every section — section targets are calibrated to \
spoken minutes at the channel's speech rate, so a section asking for \
300 words must not get 120. Underfilled drafts are rejected before \
review: if a section carries a target_words budget, realize it. Honor \
every must_include / must_not_claim and the brief's forbidden claims. \
Write in the requested language. Return only the script text and a \
duration estimate."""


GENERATION_CORRECTION_INSTRUCTIONS = """You are correcting a generated \
script draft that FAILED its generation contract — this happens before \
review, so only generation requirements matter. The failed checks and \
the per-section word budgets are given. Fix every failed check: expand \
underfilled sections toward their target word counts by deepening the \
existing material (scenes, explanation depth, evidence context, \
transitions, counterargument detail); tighten overlong parts by removing \
redundancy. Never pad, never repeat conclusions, never duplicate \
examples, never invent content, evidence, quotes, or sources. Keep the \
narrative order, the claims, the voice, and the language unchanged. \
Return the full corrected script text."""


CRITIC_INSTRUCTIONS = """You are the {role} critic for one editorial channel \
production. Review the script draft against the brief, the plan summaries, \
and these checks: {checks}. Report findings only — never rewrite. Each \
finding: location (quote or section ref), code, severity \
(INFO|WARNING|BLOCKER), explanation, correction_constraint."""


REVISION_INSTRUCTIONS = """Revise the script to satisfy every OPEN finding's \
correction constraint. Do not change anything else. When a finding \
reports wrong duration, move the total toward the given target word \
count by deepening or tightening the existing material — never by \
padding, repetition, or invented content. Return the full revised \
text."""


def _script_instructions(channel_slug: str, language: str) -> str:
    """Compose writer instructions: voice contracts apply to fa drafts only."""

    instructions = SCRIPT_INSTRUCTIONS + "\n\n" + BOOK_REFERENCE_WRITER_POLICY
    if language == "fa":
        instructions += "\n\n" + PERSIAN_VOICE_CONTRACT
        if channel_slug == "emtedad":
            instructions += "\n\n" + EMTEDAD_VOICE_CONTRACT
    return instructions


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _words(text: str) -> int:
    # Single counter shared with generation validation and duration
    # findings — drafts must be measured exactly once.
    return word_count(text)


async def _source_excerpts(session: AsyncSession, matrix_id: UUID) -> list[str]:
    """Raw source wording behind one EvidenceMatrix.

    Direct-quote provenance must trace to real source text — the
    KnowledgeUnit ``full_text`` reconstructed from source segments —
    not to the matrix's own generated claim text. Returns the full text
    of every unit cited as supporting/counter/alternative evidence.
    """

    items = list(
        (
            await session.scalars(
                select(EvidenceMatrixItem).where(
                    EvidenceMatrixItem.evidence_matrix_id == matrix_id
                )
            )
        ).all()
    )
    unit_ids: set[UUID] = set()
    for item in items:
        for raw in (
            *item.supporting_unit_ids,
            *item.counterevidence_unit_ids,
            *item.alternative_unit_ids,
        ):
            try:
                unit_ids.add(UUID(str(raw)))
            except ValueError:
                continue
    if not unit_ids:
        return []
    rows = await session.scalars(
        select(KnowledgeUnit.full_text).where(KnowledgeUnit.id.in_(unit_ids))
    )
    return [text for text in rows if text]


async def _current_cycle(session: AsyncSession, brief_id: UUID) -> int:
    """Latest owner-authorized review cycle; 1 when none was ever started.

    The first cycle is implicit — a ``review_cycles`` row exists only
    from cycle 2 onward, when the owner re-authorizes the bounded
    revision budget.
    """

    return int(
        (
            await session.scalar(
                select(func.coalesce(func.max(ReviewCycle.cycle_number), 1)).where(
                    ReviewCycle.content_brief_id == brief_id
                )
            )
        )
        or 1
    )


async def _channel_checks(
    session: AsyncSession, brief: ContentBrief
) -> tuple[str, ...]:
    """Review checks for the brief's channel only (§16).

    The strategy's ``agent_profile_json`` is the owner-editable source of
    truth: ``review_checks`` plus the behavioral gates (``content_rules``,
    ``always_consider``). The seeded CHANNEL_REVIEW_CHECKS map is only the
    fallback for strategies that predate the profile payload.
    """

    strategy = await session.get(ChannelStrategyVersion, brief.strategy_version_id)
    if strategy is None:
        return ()
    profile = strategy.agent_profile_json or {}
    checks: list[str] = []
    for key in ("review_checks", "content_rules", "always_consider"):
        raw = profile.get(key)
        if isinstance(raw, (list, tuple)):
            checks.extend(str(item) for item in raw)
    if checks:
        return tuple(dict.fromkeys(checks))
    channel = await session.get(EditorialChannel, strategy.editorial_channel_id)
    slug = channel.slug if channel is not None else ""
    return CHANNEL_REVIEW_CHECKS.get(slug, ())


async def _critic_context(
    session: AsyncSession, draft: ScriptDraft, brief: ContentBrief | None
) -> dict[str, object]:
    """Bounded fact-check context: brief contract + plan + evidence claims.

    The critics judge against the frozen artifacts, never the raw corpus —
    the same input firewall the writer is held to (§39).
    """

    context: dict[str, object] = {
        "allowed_book_references": draft.provenance_json.get("book_references", [])
    }
    if brief is not None:
        context["brief"] = {
            "question": brief.question,
            "thesis": brief.thesis,
            "angle": brief.angle,
            "forbidden_claims": brief.forbidden_claims_json,
        }
    if draft.narrative_plan_id is not None:
        narrative = await session.get(NarrativePlan, draft.narrative_plan_id)
        argument = (
            await session.get(ArgumentPlan, narrative.argument_plan_id)
            if narrative is not None
            else None
        )
        if narrative is not None:
            narrative_sections = list(
                await session.scalars(
                    select(NarrativePlanSection)
                    .where(NarrativePlanSection.narrative_plan_id == narrative.id)
                    .order_by(NarrativePlanSection.ordinal)
                )
            )
            context["narrative_plan"] = [
                {"role": s.narrative_role, "purpose": s.purpose}
                for s in narrative_sections
            ]
        if argument is not None:
            argument_sections = list(
                await session.scalars(
                    select(ArgumentPlanSection)
                    .where(ArgumentPlanSection.argument_plan_id == argument.id)
                    .order_by(ArgumentPlanSection.ordinal)
                )
            )
            context["argument_plan"] = [
                {"role": s.role, "purpose": s.purpose} for s in argument_sections
            ]
            items = list(
                await session.scalars(
                    select(EvidenceMatrixItem).where(
                        EvidenceMatrixItem.evidence_matrix_id
                        == argument.evidence_matrix_id
                    )
                )
            )
            context["evidence_claims"] = [
                {
                    "claim": item.claim_text,
                    "role": item.role.value,
                    "epistemic_status": item.epistemic_status,
                }
                for item in items
            ]
    return context


async def _persian_findings(
    session: AsyncSession, draft: ScriptDraft, brief: ContentBrief | None
) -> list[PipelineFinding]:
    """Deterministic Persian checks: scaffolding, nativeness, memory."""

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
            effective = await StudioSettingsService(self.database).effective()
            wpm = speech_wpm(effective, language)
            provider = self.provider or resolve_llm_provider()
            book_refs = await self._select_book_references(
                session, provider, brief, master
            )
            duration_min = float(str(effective.get("target_duration_min_minutes", 25)))
            duration_max = float(str(effective.get("target_duration_max_minutes", 30)))
            min_ratio = float(
                str(effective.get("first_draft_min_duration_ratio", 0.85))
            )
            max_ratio = float(
                str(effective.get("first_draft_max_duration_ratio", 1.15))
            )
            section_payloads: list[dict[str, object]] = [
                {
                    "ordinal": s.ordinal,
                    "role": s.role.value,
                    "narrative_role": s.rhetorical_function,
                    "purpose": s.purpose,
                    "duration_seconds": s.duration_seconds,
                    "target_minutes": round((s.duration_seconds or 0) / 60, 1),
                    "target_words": int((s.duration_seconds or 0) / 60 * wpm),
                    "transition_intent": s.transition_intent,
                    "prohibited_formulations": (s.prohibited_formulations),
                }
                for s in sections
            ]
            claim_payloads: list[dict[str, object]] = [
                {
                    "proposition": claim.semantic_proposition,
                    "epistemic_status": claim.epistemic_status.value,
                    "qualifiers": claim.required_qualifiers,
                    "prohibited": claim.prohibited_overstatements,
                    "constraints": claim.formulation_constraints,
                }
                for claim in claims
            ]
            payload: dict[str, object] = {
                "brief": {
                    "question": brief.question,
                    "thesis": brief.thesis,
                    "angle": brief.angle,
                    "target_duration_minutes": brief.target_duration_minutes,
                    "target_duration_min": duration_min,
                    "target_duration_max": duration_max,
                    "target_word_count": int(brief.target_duration_minutes * wpm),
                    "generation_band_words": [
                        round(brief.target_duration_minutes * wpm * min_ratio),
                        round(brief.target_duration_minutes * wpm * max_ratio),
                    ],
                    "speech_wpm": wpm,
                    "forbidden_claims": brief.forbidden_claims_json,
                },
                "semantic_master": {
                    "sections": section_payloads,
                    "claims": claim_payloads,
                    "uncertainty_constraints": master.uncertainty_constraints,
                    "channel_constraints": master.architecture.get(
                        "semantic_constraints", []
                    ),
                    "distinctiveness": master.architecture.get("distinctiveness", {}),
                    "ending_mode": master.ending_mode,
                },
                "style_instruction": style_instruction,
                "language": language,
                "allowed_book_references": [ref.model_dump() for ref in book_refs],
            }
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
            # Generation validation: a draft that violates the generation
            # contract (encoding, duration band, collapsed structure,
            # quality blockers) is corrected inside generation — it must
            # never consume semantic revision rounds.
            section_count = len(sections)
            max_corrections = int(
                str(effective.get("generation_max_correction_attempts", 2))
            )
            attempts: list[dict[str, object]] = []
            report = validate_generation(
                draft.text,
                language=language,
                target_minutes=brief.target_duration_minutes,
                wpm=wpm,
                section_count=section_count,
                min_ratio=min_ratio,
                max_ratio=max_ratio,
                evidence_texts=[str(item["proposition"]) for item in claim_payloads],
            )
            attempts.append(report.payload())
            while not report.passed and len(attempts) <= max_corrections:
                log.warning(
                    "script_generation_correction",
                    extra={
                        "brief_id": str(brief_id),
                        "attempt": len(attempts),
                        "failed": [c.code for c in report.checks if c.blocking],
                    },
                )
                corrected = await provider.extract(
                    StructuredExtractionRequest(
                        task="script_generation_correction",
                        prompt_version=REVISION_PROMPT_VERSION,
                        model=self.model,
                        instructions=GENERATION_CORRECTION_INSTRUCTIONS,
                        input_text=json.dumps(
                            {
                                "draft": draft.text,
                                "failed_checks": [
                                    {"code": c.code, "message": c.message}
                                    for c in report.checks
                                    if c.blocking
                                ],
                                "generation_band_words": [
                                    round(
                                        brief.target_duration_minutes * wpm * min_ratio
                                    ),
                                    round(
                                        brief.target_duration_minutes * wpm * max_ratio
                                    ),
                                ],
                                "speech_wpm": wpm,
                                "sections": section_payloads,
                            },
                            ensure_ascii=False,
                        ),
                        output_model=RevisionOutput,
                    )
                )
                revision = RevisionOutput.model_validate(corrected.model_dump())
                draft = ScriptDraftOutput(
                    text=revision.text,
                    estimated_duration_seconds=draft.estimated_duration_seconds,
                )
                report = validate_generation(
                    draft.text,
                    language=language,
                    target_minutes=brief.target_duration_minutes,
                    wpm=wpm,
                    section_count=section_count,
                    min_ratio=min_ratio,
                    max_ratio=max_ratio,
                )
                attempts.append(report.payload())
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
                    "book_references": [ref.model_dump() for ref in book_refs],
                    # Pre-review generation contract: PASSED drafts are fit
                    # for ReviewRun; FAILED means the bounded correction
                    # loop could not satisfy the generation requirements —
                    # owner sees GENERATION_REVIEW_REQUIRED, revision
                    # rounds stay untouched.
                    "generation_validation": {
                        "status": "PASSED" if report.passed else "FAILED",
                        "max_correction_attempts": max_corrections,
                        "attempts": attempts,
                        **report.payload(),
                    },
                },
                content_hash=_hash(draft.text),
                target_duration_minutes=brief.target_duration_minutes,
                actual_word_count=words,
                estimated_duration_seconds=int(words / wpm * 60),
            )
            session.add(row)
            return row

    async def _select_book_references(
        self,
        session: AsyncSession,
        provider: LLMProvider,
        brief: ContentBrief,
        master: LectureMasterVersion,
    ) -> list[BookReference]:
        """Pick real non-Persian books grounded in the frozen evidence.

        The selector reads the brief plus the EvidenceMatrix claim text —
        the same material the writer is held to — and the deterministic
        ``allowed_book_references`` gate removes anything Persian-language,
        blank, duplicated, or over the cap. Failure degrades to no
        references; a script never *needs* a book reference.
        """

        claim_texts: list[str] = []
        source_texts: list[str] = []
        if master.evidence_matrix_id is not None:
            items = await session.scalars(
                select(EvidenceMatrixItem.claim_text).where(
                    EvidenceMatrixItem.evidence_matrix_id == master.evidence_matrix_id
                )
            )
            claim_texts = [text for text in items if text][:80]
            source_texts = await _source_excerpts(session, master.evidence_matrix_id)
        if not claim_texts:
            return []
        try:
            result = await provider.extract(
                StructuredExtractionRequest(
                    task="book_reference_selection",
                    prompt_version=SCRIPT_PROMPT_VERSION,
                    model=self.model,
                    instructions=BOOK_REFERENCE_SELECTION_INSTRUCTIONS,
                    input_text=json.dumps(
                        {
                            "question": brief.question,
                            "thesis": brief.thesis,
                            "evidence_claims": claim_texts,
                            # Raw source wording — the ONLY material a
                            # verified_quote may be copied from. Claims are
                            # paraphrases and never certify a direct quote.
                            "source_excerpts": [t[:2000] for t in source_texts[:60]],
                        },
                        ensure_ascii=False,
                    ),
                    output_model=BookReferenceSelection,
                )
            )
        except Exception as exc:
            log.warning(
                "book_reference_selection_failed",
                extra={"brief_id": str(brief.id), "error": str(exc)},
            )
            return []
        selection = BookReferenceSelection.model_validate(result.model_dump())
        return list(allowed_book_references(selection, source_texts))

    async def _start_review_run(self, draft_id: UUID, provider: LLMProvider) -> UUID:
        """Open a numbered ReviewRun for the draft's exact version+hash.

        At most one active run may exist for the exact draft state —
        the DB enforces it with a partial unique index; this check
        surfaces the honest error instead of an integrity violation.
        """

        async with self.database.transaction() as session:
            draft = await session.get(ScriptDraft, draft_id)
            if draft is None:
                raise LookupError(f"Unknown script draft {draft_id}")
            active = await session.scalar(
                select(ReviewRun.id).where(
                    ReviewRun.script_draft_id == draft_id,
                    ReviewRun.draft_version == draft.version_number,
                    ReviewRun.draft_hash == draft.content_hash,
                    ReviewRun.status.in_(
                        [ReviewRunStatus.PENDING, ReviewRunStatus.RUNNING]
                    ),
                )
            )
            if active is not None:
                raise GateBlockedError(
                    "A review is already running for this draft — "
                    "wait for it to finish before starting another."
                )
            previous = (
                await session.scalar(
                    select(func.coalesce(func.max(ReviewRun.round_number), 0)).where(
                        ReviewRun.content_brief_id == draft.content_brief_id
                    )
                )
                or 0
            )
            cycle = await _current_cycle(session, draft.content_brief_id)
            deterministic = 1 + (1 if draft.language == "fa" else 0)
            run = ReviewRun(
                content_brief_id=draft.content_brief_id,
                script_draft_id=draft.id,
                draft_version=draft.version_number,
                draft_hash=draft.content_hash,
                round_number=previous + 1,
                cycle_number=cycle,
                status=ReviewRunStatus.RUNNING,
                critic_profile_version=CRITIC_PROMPT_VERSION,
                critics_requested=len(CriticRole) + deterministic,
                provider=getattr(provider, "name", "unknown"),
                model=self.model,
            )
            session.add(run)
            await session.flush()
            draft.status = DraftStatus.IN_REVIEW
            run_id: UUID = run.id
            return run_id

    async def review_draft(self, draft_id: UUID) -> list[ReviewFinding]:
        """Run every critic role inside a persisted ReviewRun.

        Findings can never prove a review happened — the run is the
        artifact. A COMPLETED run with zero findings is a truthful clean
        review; a provider failure leaves a FAILED run with its error.
        """

        provider = self.provider or resolve_llm_provider()
        run_id = await self._start_review_run(draft_id, provider)
        started = time.monotonic()
        try:
            findings = await self._critique_draft(run_id, draft_id, started, provider)
        except Exception as exc:
            async with self.database.transaction() as session:
                run = await session.get(ReviewRun, run_id)
                if run is not None:
                    run.status = ReviewRunStatus.FAILED
                    run.error = str(exc)[:2000]
                    run.latency_ms = int((time.monotonic() - started) * 1000)
                    run.completed_at = utc_now()
            raise
        return findings

    async def _critique_draft(
        self,
        run_id: UUID,
        draft_id: UUID,
        started: float,
        provider: LLMProvider,
    ) -> list[ReviewFinding]:
        async with self.database.transaction() as session:
            run = await session.get(ReviewRun, run_id)
            draft = await session.get(ScriptDraft, draft_id)
            if run is None or draft is None:
                raise LookupError(f"Unknown review run {run_id}")
            brief = await session.get(ContentBrief, draft.content_brief_id)
            checks = await _channel_checks(session, brief) if brief else ()
            context = await _critic_context(session, draft, brief)
            findings: list[ReviewFinding] = []
            completed = 0
            for role in CriticRole:
                role_checks = (
                    checks + BOOK_REFERENCE_CHECKS
                    if role is CriticRole.CHANNEL_SPECIFIC
                    else ()
                )
                result = await provider.extract(
                    StructuredExtractionRequest(
                        task="script_review",
                        prompt_version=CRITIC_PROMPT_VERSION,
                        model=self.model,
                        instructions=CRITIC_INSTRUCTIONS.format(
                            role=role.value, checks=", ".join(role_checks)
                        ),
                        input_text=json.dumps(
                            {"draft": draft.text, "context": context},
                            ensure_ascii=False,
                        ),
                        output_model=ReviewFindingsOutput,
                    )
                )
                completed += 1
                output = ReviewFindingsOutput.model_validate(result.model_dump())
                for proposal in output.findings:
                    finding = ReviewFinding(
                        script_draft_id=draft.id,
                        review_run_id=run.id,
                        critic_role=role.value,
                        severity=proposal.severity,
                        location=proposal.location,
                        code=proposal.code,
                        explanation=proposal.explanation,
                        correction_constraint=proposal.correction_constraint,
                    )
                    session.add(finding)
                    findings.append(finding)
            if brief is not None:
                # Duration compliance applies to every draft language — the
                # per-language owner setting supplies the speech rate.
                effective = await StudioSettingsService(self.database).effective()
                duration_checks, _count = duration_findings(
                    draft.text,
                    brief.target_duration_minutes,
                    wpm=speech_wpm(effective, draft.language),
                )
                for check in duration_checks:
                    finding = ReviewFinding(
                        script_draft_id=draft.id,
                        review_run_id=run.id,
                        critic_role="DURATION",
                        severity=FindingSeverity.WARNING,
                        location=check.category,
                        code=check.code,
                        explanation=check.message,
                        correction_constraint=(
                            "Adjust the draft to the target duration band by "
                            "adding only useful material (clarification, "
                            "evidence context, counterargument depth, "
                            "transitions) or removing redundancy — never "
                            "filler, repeated conclusions, duplicate "
                            "examples, or dropped evidence/limitations."
                        ),
                    )
                    session.add(finding)
                    findings.append(finding)
            # Deterministic book-reference gate: checks quoted wording
            # near attributions against verified_quote / verbatim RAW
            # SOURCE text (never generated claim text), and re-verifies
            # the allow-list language metadata.
            raw_refs = draft.provenance_json.get("book_references", [])
            book_refs = (
                [
                    BookReference.model_validate(item)
                    for item in raw_refs
                    if isinstance(item, dict)
                ]
                if isinstance(raw_refs, list)
                else []
            )
            if book_refs:
                matrix_id = await session.scalar(
                    select(ArgumentPlan.evidence_matrix_id)
                    .join(
                        NarrativePlan,
                        NarrativePlan.argument_plan_id == ArgumentPlan.id,
                    )
                    .where(NarrativePlan.id == draft.narrative_plan_id)
                )
                source_texts = (
                    await _source_excerpts(session, matrix_id)
                    if matrix_id is not None
                    else []
                )
                for book_check in book_reference_findings(
                    draft.text, book_refs, source_texts
                ):
                    finding = ReviewFinding(
                        script_draft_id=draft.id,
                        review_run_id=run.id,
                        critic_role="BOOK_POLICY",
                        severity=(
                            FindingSeverity.BLOCKER
                            if book_check.blocking
                            else FindingSeverity.WARNING
                        ),
                        location=book_check.location,
                        code=book_check.code,
                        explanation=book_check.message,
                        correction_constraint=(
                            "Remove the quotation marks and paraphrase the "
                            "idea, or reproduce the reference's "
                            "verified_quote exactly."
                        ),
                    )
                    session.add(finding)
                    findings.append(finding)
            if draft.language == "fa":
                completed += 1
                for check in await _persian_findings(session, draft, brief):
                    finding = ReviewFinding(
                        script_draft_id=draft.id,
                        review_run_id=run.id,
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
            run.critics_completed = completed
            run.finding_count = len(findings)
            run.blocking_count = sum(
                1 for f in findings if f.severity is FindingSeverity.BLOCKER
            )
            run.major_count = sum(
                1 for f in findings if f.severity is FindingSeverity.WARNING
            )
            run.minor_count = sum(
                1 for f in findings if f.severity is FindingSeverity.INFO
            )
            run.status = ReviewRunStatus.COMPLETED
            run.latency_ms = int((time.monotonic() - started) * 1000)
            run.completed_at = utc_now()
            return findings

    async def revise_draft(self, draft_id: UUID) -> ScriptDraft:
        """Create a new draft version addressing all OPEN findings.

        Automatic revision is bounded: once the configured maximum of
        completed review rounds is reached and major/blocking findings
        are still open, the loop stops at OWNER_REVIEW_REQUIRED instead
        of looping forever. The owner may still waive/approve manually.
        """

        async with self.database.transaction() as session:
            draft = await session.get(ScriptDraft, draft_id)
            if draft is None:
                raise LookupError(f"Unknown script draft {draft_id}")
            latest_run = await session.scalar(
                select(ReviewRun)
                .where(ReviewRun.script_draft_id == draft_id)
                .order_by(ReviewRun.round_number.desc())
                .limit(1)
            )
            # Revision addresses the open findings of the latest review
            # run only. Unscoped legacy findings (pre-ReviewRun history)
            # and stale-run findings stay historical — they never become
            # current-run findings, and a persisting problem is
            # re-reported by the critics on the next run.
            finding_filter = [
                ReviewFinding.script_draft_id == draft_id,
                ReviewFinding.status == FindingStatus.OPEN,
            ]
            if latest_run is not None:
                finding_filter.append(ReviewFinding.review_run_id == latest_run.id)
            else:
                # No run exists: legacy unscoped findings remain the only
                # signal and are still addressed — they can never certify
                # or gate anything since approval requires a ReviewRun.
                finding_filter.append(ReviewFinding.review_run_id.is_(None))
            open_findings = list(
                (
                    await session.scalars(select(ReviewFinding).where(*finding_filter))
                ).all()
            )
            if not open_findings:
                return draft
            major_open = [
                f
                for f in open_findings
                if f.severity in {FindingSeverity.BLOCKER, FindingSeverity.WARNING}
            ]
            cycle = await _current_cycle(session, draft.content_brief_id)
            if major_open:
                # The automatic revision budget counts REVISIONS — drafts
                # persisted by revise_draft inside this owner-authorized
                # cycle. Reviews, failed runs, duplicate reviews, retries,
                # and regenerations never consume it.
                rounds_done = int(
                    await session.scalar(
                        select(func.count(ScriptDraft.id)).where(
                            ScriptDraft.content_brief_id == draft.content_brief_id,
                            ScriptDraft.revision_cycle == cycle,
                        )
                    )
                    or 0
                )
                effective = await StudioSettingsService(self.database).effective()
                max_rounds = int(str(effective.get("max_revision_rounds", 3)))
                if rounds_done >= max_rounds:
                    raise GateBlockedError(
                        "OWNER_REVIEW_REQUIRED — maximum automatic revision "
                        f"rounds ({max_rounds}) in review cycle {cycle} "
                        f"reached with "
                        f"{len(major_open)} open major/blocking findings. "
                        "Waive findings, approve, or start a new review "
                        "cycle explicitly."
                    )
            provider = self.provider or resolve_llm_provider()
            effective = await StudioSettingsService(self.database).effective()
            revision_wpm = speech_wpm(effective, draft.language)
            brief = await session.get(ContentBrief, draft.content_brief_id)
            result = await provider.extract(
                StructuredExtractionRequest(
                    task="script_revision",
                    prompt_version=REVISION_PROMPT_VERSION,
                    model=self.model,
                    instructions=REVISION_INSTRUCTIONS,
                    input_text=json.dumps(
                        {
                            "draft": draft.text,
                            "current_word_count": _words(draft.text),
                            "target_word_count": (
                                int(brief.target_duration_minutes * revision_wpm)
                                if brief is not None
                                else None
                            ),
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
            # A revision is generation output too: replacement characters
            # must never persist as a clean-looking draft — fail honestly so
            # the provider output is retried, not reviewed.
            if "\ufffd" in revised.text or any(
                unicodedata.category(char) == "Cf" and char != "‌"
                for char in revised.text
            ):
                raise RuntimeError(
                    "ENCODING_CORRUPTION — revision output contains "
                    "replacement characters or format controls; "
                    "no draft persisted."
                )
            effective = await StudioSettingsService(self.database).effective()
            draft_wpm = speech_wpm(effective, draft.language)
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
                revision_cycle=cycle,
                provenance_json={
                    **draft.provenance_json,
                    "revised_from_draft": str(draft.id),
                    "addressed_finding_ids": [str(f.id) for f in open_findings],
                },
                content_hash=_hash(revised.text),
                target_duration_minutes=draft.target_duration_minutes,
                actual_word_count=_words(revised.text),
                estimated_duration_seconds=(int(_words(revised.text) / draft_wpm * 60)),
            )
            session.add(row)
            for finding in open_findings:
                finding.status = FindingStatus.ADDRESSED
            draft.status = DraftStatus.ARCHIVED
            return row

    async def approve_draft(self, draft_id: UUID, *, approved_by: str) -> ScriptDraft:
        """Approve only behind a completed review of THIS exact draft text.

        Approval is an owner editorial decision: ``approved_by`` records
        who authorized it so automated/agent calls are identifiable in
        provenance and cannot masquerade as owner intent.

        The gate is the ReviewRun, not finding existence: a completed run
        with finding_count=0 permits approval, while missing, stale-hash,
        or failed reviews block it. Open WARNING findings are unresolved
        majors under owner policy — waiving is the explicit override.
        """

        async with self.database.transaction() as session:
            draft = await session.get(ScriptDraft, draft_id)
            if draft is None:
                raise LookupError(f"Unknown script draft {draft_id}")
            latest_run = await session.scalar(
                select(ReviewRun)
                .where(ReviewRun.script_draft_id == draft_id)
                .order_by(ReviewRun.round_number.desc())
                .limit(1)
            )
            review_current = (
                latest_run is not None
                and latest_run.status is ReviewRunStatus.COMPLETED
                and latest_run.draft_version == draft.version_number
                and latest_run.draft_hash == draft.content_hash
            )
            if not review_current or latest_run is None:
                raise GateBlockedError(
                    "No completed review for the current draft text — "
                    "review required (or the last review failed/became stale)"
                )
            # Final duration gate: the generation band (0.85–1.15) admits a
            # draft into review; approval requires the configured editorial
            # band (default 25–30 min) — deterministic, critic-independent.
            effective = await StudioSettingsService(self.database).effective()
            approve_wpm = speech_wpm(effective, draft.language)
            final_min = float(str(effective.get("target_duration_min_minutes", 25)))
            final_max = float(str(effective.get("target_duration_max_minutes", 30)))
            minutes = _words(draft.text) / approve_wpm
            if not final_min <= minutes <= final_max:
                raise GateBlockedError(
                    f"APPROVAL_DURATION_GATE — draft is {minutes:.1f} min "
                    f"at {approve_wpm} wpm; final approval requires "
                    f"{final_min}–{final_max} min."
                )
            blocking = await session.scalar(
                select(func.count(ReviewFinding.id)).where(
                    ReviewFinding.review_run_id == latest_run.id,
                    ReviewFinding.severity.in_(
                        [FindingSeverity.BLOCKER, FindingSeverity.WARNING]
                    ),
                    ReviewFinding.status == FindingStatus.OPEN,
                )
            )
            if blocking:
                raise GateBlockedError(f"{blocking} blocking findings remain open")
            if not approved_by.strip():
                raise GateBlockedError(
                    "Approval requires an explicit approver identity"
                )
            draft.status = DraftStatus.APPROVED
            draft.provenance_json = {
                **draft.provenance_json,
                "approved_by": approved_by,
            }
            # Owner approval is the authoritative publish-boundary: record the
            # semantic signature for future distinctiveness comparisons.
            await ensure_signature_for_draft(session, draft)
            return draft

    async def start_review_cycle(
        self, brief_id: UUID, *, started_by: str = "owner"
    ) -> ReviewCycle:
        """Owner checkpoint: explicitly authorize the next bounded cycle.

        Allowed only when the current cycle's automatic revision budget is
        exhausted — this is the deliberate owner decision that turns
        OWNER_REVIEW_REQUIRED into fresh budget, never a silent reset.
        """

        async with self.database.transaction() as session:
            draft = await session.scalar(
                select(ScriptDraft).where(ScriptDraft.content_brief_id == brief_id)
            )
            if draft is None:
                raise GateBlockedError("No draft exists for this brief")
            cycle = await _current_cycle(session, brief_id)
            effective = await StudioSettingsService(self.database).effective()
            max_rounds = int(str(effective.get("max_revision_rounds", 3)))
            revisions_done = int(
                await session.scalar(
                    select(func.count(ScriptDraft.id)).where(
                        ScriptDraft.content_brief_id == brief_id,
                        ScriptDraft.revision_cycle == cycle,
                    )
                )
                or 0
            )
            if revisions_done < max_rounds:
                raise GateBlockedError(
                    f"Review cycle {cycle} still has revision budget "
                    f"({revisions_done}/{max_rounds} revisions used) — a new "
                    "cycle may only be started at the owner checkpoint."
                )
            new_cycle = ReviewCycle(
                content_brief_id=brief_id,
                cycle_number=cycle + 1,
                started_by=started_by,
            )
            session.add(new_cycle)
            await session.flush()
            await session.refresh(new_cycle)
            return new_cycle

    async def waive_finding(
        self, finding_id: UUID, *, waived_by: str, reason: str
    ) -> ReviewFinding:
        """Owner override: waive one open finding so it stops gating.

        Waiving is an editorial acceptance decision — it requires the
        owner's identity and a justification, both persisted on the
        finding. Automated agents may *recommend* a waiver (an open
        finding may carry a ``resolution_note`` recommendation) but only
        this owner path can set WAIVED.
        """

        if not waived_by.strip():
            raise ValueError("Waiving a finding requires an owner identity")
        if not reason.strip():
            raise ValueError("Waiving a finding requires a justification")
        async with self.database.transaction() as session:
            finding = await session.get(ReviewFinding, finding_id)
            if finding is None:
                raise LookupError(f"Unknown review finding {finding_id}")
            if finding.status is not FindingStatus.OPEN:
                raise ValueError(f"Finding is {finding.status}; cannot waive")
            finding.status = FindingStatus.WAIVED
            finding.resolution_actor = waived_by
            finding.resolution_note = reason
            return finding

    async def recommend_waiver(
        self, finding_id: UUID, *, recommended_by: str, reason: str
    ) -> ReviewFinding:
        """Agent path: record a waiver recommendation — never resolves.

        The finding stays OPEN and keeps gating approval; the note tells
        the owner why a waiver may be acceptable. Only ``waive_finding``
        can set WAIVED.
        """

        if not recommended_by.strip() or not reason.strip():
            raise ValueError("A recommendation needs an actor and a reason")
        async with self.database.transaction() as session:
            finding = await session.get(ReviewFinding, finding_id)
            if finding is None:
                raise LookupError(f"Unknown review finding {finding_id}")
            if finding.status is not FindingStatus.OPEN:
                raise ValueError(f"Finding is {finding.status}; cannot recommend")
            finding.resolution_actor = recommended_by
            finding.resolution_note = f"RECOMMENDATION: {reason}"
            return finding
