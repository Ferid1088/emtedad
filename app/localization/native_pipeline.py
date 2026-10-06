"""Native target-language script production (§30–45).

Each language derives independently from one shared
``LocalizationSemanticPackage`` anchored to the owner-approved Persian
script. The run record persists truthful stages; intermediate artifacts
live in ``work_json`` and are never publishable.

    PENDING → SEMANTIC_ALIGNED → COVERAGE_TRANSLATED → NATIVE_DRAFTED
    → NATIVE_REVIEW → FIDELITY_REVIEW → (targeted corrections, loop ≤3)
    → premium final edit → FINAL_FIDELITY → DURATION_READY
    → READY_FOR_VOICE   |  BLOCKED / STALE_SOURCE / FAILED

APIMaster exposes no batch API, so the premium final edit runs
synchronously on the configured premium model.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.content_engine.domain import DraftStatus, FindingSeverity, FindingStatus
from app.content_engine.models import (
    NarrativePlanSection,
    ReviewFinding,
    ScriptDraft,
)
from app.content_engine.patching import (
    PatchOp,
    PatchResult,
    PatchSetOutput,
    ScriptSection,
    SectionBudget,
    apply_patches,
    budget_map,
    build_section_plan,
    candidate_rank,
    is_better_candidate,
    join_sections,
    labeled_script,
    length_repair_plan,
    restore_sections,
    section_provenance,
    sections_from_output,
    sections_from_paragraph_groups,
)
from app.content_engine.service import GateBlockedError
from app.core.config import get_settings
from app.db.session import Database
from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.knowledge.llm.context import assert_no_secrets, guard_payload
from app.knowledge.llm.factory import resolve_llm_provider
from app.knowledge.llm.roles import (
    AGENT_TO_MODEL_ROLE,
    AgentRole,
    model_for_role,
)
from app.knowledge.llm.telemetry import DatabaseLLMRecorder
from app.lecture.domain import PublicationLanguage
from app.localization.domain import LocalizationPipelineStage
from app.localization.gate import (
    LocalizationEligibility,
    evaluate_localization_eligibility,
    package_is_current,
)
from app.localization.models import (
    LocalizationPipelineRun,
    LocalizationSemanticPackage,
)
from app.localization.native_prompts import (
    PIPELINE_PROMPT_VERSION,
    audience_critic_instructions,
    coverage_translation_instructions,
    fidelity_critic_instructions,
    final_editor_instructions,
    length_repair_instructions,
    narrative_editor_instructions,
    native_critic_instructions,
    native_reconstruction_instructions,
    patch_repair_instructions,
    profile_payload,
)
from app.localization.native_quality import validate_target_script
from app.localization.validators import ProtectedTerminologyValidator
from app.ops.assets.models import utc_now
from app.ops.settings.service import StudioSettingsService, speech_wpm

MAX_REVIEW_LOOPS = 3
MAX_POST_PREMIUM_REPAIRS = 1


class ScriptTextOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)


class PipelineFindingProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str = Field(min_length=1)
    # Stable plan-section id owning the defect ("" = spans the script).
    section_id: str = ""
    code: str = Field(min_length=1)
    severity: FindingSeverity
    explanation: str = Field(min_length=1)
    correction_constraint: str = ""


class PipelineFindingsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[PipelineFindingProposal] = Field(default_factory=list)


class ScriptSectionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ScriptSectionsOutput(BaseModel):
    """Writer/editor contract: exactly one entry per plan section."""

    model_config = ConfigDict(extra="forbid")

    sections: list[ScriptSectionItem]


ProviderFor = Callable[..., LLMProvider]


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()


def _dump(result: BaseModel) -> dict[str, object]:
    return result.model_dump(mode="json")


def _supported_material(package_payload: dict[str, object]) -> list[object]:
    """The package's explicit 'what the source supports' surface.

    ``claim_ledger`` is honestly empty for packages built without an
    upstream ledger, so repair models also get the thesis, causal
    constraints, counterarguments, and story facts — the fields the
    fidelity critic itself judges against.
    """

    material: list[object] = []
    ledger = package_payload.get("claim_ledger")
    if isinstance(ledger, list):
        material.extend(ledger)
    for key in (
        "causal_constraints",
        "counterarguments",
        "story_facts",
        "unresolved_ambiguities",
    ):
        value = package_payload.get(key)
        if isinstance(value, list):
            material.extend(value)
    thesis = package_payload.get("thesis")
    if thesis:
        material.insert(0, {"thesis": thesis})
    return material


class NativeLocalizationPipeline:
    """Stage-persisted native production for one target language."""

    def __init__(
        self,
        database: Database,
        *,
        provider_for: ProviderFor | None = None,
        model: str = "configured-default",
        effective_overrides: dict[str, object] | None = None,
        run_scope: str = "production",
    ) -> None:
        self.database = database
        self.provider_for = provider_for
        self.model = model
        # Dry-run/benchmark hooks: in-memory setting overlays that never
        # touch owner_settings — production callers leave both defaults.
        self.effective_overrides = effective_overrides or {}
        self.run_scope = run_scope

    # ---------------------------------------------------------------
    # helpers
    # ---------------------------------------------------------------

    def _provider(
        self,
        role: AgentRole,
        effective: dict[str, object],
        recorder: DatabaseLLMRecorder,
    ) -> LLMProvider:
        if self.provider_for is not None:
            return self.provider_for(role)
        return resolve_llm_provider(role=role, effective=effective, recorder=recorder)

    async def _extract(
        self,
        role: AgentRole,
        task: str,
        instructions: str,
        payload: dict[str, object],
        output_model: type[BaseModel],
        *,
        timeout_seconds: int = 600,
        run: LocalizationPipelineRun | None = None,
    ) -> BaseModel:
        """Guarded structured call: allowlist + secret scan, then extract."""

        guard_payload(role, payload)
        input_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        assert_no_secrets(input_text)
        effective = await StudioSettingsService(self.database).effective()
        effective.update(self.effective_overrides)
        brief_id: UUID | None = None
        if run is not None:
            async with self.database.transaction() as session:
                package = await session.get(
                    LocalizationSemanticPackage, run.semantic_package_id
                )
                if package is not None:
                    brief_id = package.content_brief_id
        recorder = DatabaseLLMRecorder(
            self.database,
            run_scope=self.run_scope,
            content_brief_id=brief_id,
            language=run.language.value if run is not None else None,
        )
        provider = self._provider(role, effective, recorder)
        return await provider.extract(
            StructuredExtractionRequest(
                task=task,
                prompt_version=PIPELINE_PROMPT_VERSION,
                model=self.model,
                instructions=instructions,
                input_text=input_text,
                output_model=output_model,
                timeout_seconds=timeout_seconds,
            )
        )

    async def _duration_contract(
        self, language: PublicationLanguage
    ) -> dict[str, object]:
        """Spoken-length contract mirrored by the deterministic gate.

        Writers otherwise compress long-form argument into summary; the
        gate then rejects the draft on duration. The contract makes the
        target explicit upstream instead of discovering it at the gate.
        """

        effective = await StudioSettingsService(self.database).effective()
        effective.update(self.effective_overrides)
        wpm = speech_wpm(effective, language.value)
        min_minutes = float(str(effective.get("target_duration_min_minutes", 25)))
        max_minutes = float(str(effective.get("target_duration_max_minutes", 30)))
        return {
            "min_minutes": min_minutes,
            "max_minutes": max_minutes,
            "wpm": wpm,
            "target_words_min": int(min_minutes * wpm),
            "target_words_max": int(max_minutes * wpm),
        }

    async def _load_run(self, run_id: UUID) -> LocalizationPipelineRun:
        async with self.database.transaction() as session:
            run = await session.get(LocalizationPipelineRun, run_id)
            if run is None:
                raise LookupError(f"Unknown localization run {run_id}")
            session.expunge(run)
            return run

    async def _set_stage(
        self,
        run_id: UUID,
        stage: LocalizationPipelineStage,
        *,
        error: str | None = None,
        work: dict[str, object] | None = None,
        **fields: object,
    ) -> LocalizationPipelineRun:
        async with self.database.transaction() as session:
            run = await session.get(LocalizationPipelineRun, run_id)
            if run is None:
                raise LookupError(f"Unknown localization run {run_id}")
            run.stage = stage
            if error is not None:
                run.error = error[:2000]
            if work:
                run.work_json = {**run.work_json, **work}
            for key, value in fields.items():
                setattr(run, key, value)
            run.updated_at = utc_now()
            await session.flush()
            await session.refresh(run)
            return run

    async def _require_current(self, run: LocalizationPipelineRun) -> None:
        async with self.database.transaction() as session:
            package = await session.get(
                LocalizationSemanticPackage, run.semantic_package_id
            )
            if package is None:
                raise LookupError("semantic package not found")
            current = await package_is_current(session, package)
            source = await session.get(ScriptDraft, package.script_draft_id)
            if source is not None:
                session.expunge(source)
        if not current:
            await self._set_stage(
                run.id,
                LocalizationPipelineStage.STALE_SOURCE,
                error="source Persian draft changed after approval",
            )
            raise GateBlockedError(
                "STALE_SOURCE — the locked Persian source changed; this "
                "localization run must be regenerated from a new package."
            )
        if source is not None:
            eligible = await self._eligibility(source)
            if not eligible.eligible:
                await self._set_stage(
                    run.id,
                    LocalizationPipelineStage.BLOCKED,
                    error="LOCALIZATION_RECERTIFICATION_REQUIRED — "
                    + "; ".join(eligible.reasons),
                )
                raise GateBlockedError(
                    "LOCALIZATION_RECERTIFICATION_REQUIRED — the Persian "
                    "master no longer meets current localization policy: "
                    + "; ".join(eligible.reasons)
                )

    async def _fail(self, run_id: UUID, error: str) -> LocalizationPipelineRun:
        return await self._set_stage(
            run_id, LocalizationPipelineStage.FAILED, error=error[:1900]
        )

    async def _eligibility(self, draft: ScriptDraft) -> LocalizationEligibility:
        """Current-policy localization check on the pinned source draft.

        Approval is historical truth and stays untouched; eligibility is
        derived per run (§31–33).
        """

        effective = await StudioSettingsService(self.database).effective()
        effective.update(self.effective_overrides)
        return evaluate_localization_eligibility(
            draft,
            min_minutes=float(str(effective.get("target_duration_min_minutes", 25))),
            max_minutes=float(str(effective.get("target_duration_max_minutes", 30))),
            wpm=speech_wpm(effective, draft.language),
        )

    # ---------------------------------------------------------------
    # stage 1: create run + coverage translation
    # ---------------------------------------------------------------

    async def start(
        self, package_id: UUID, language: PublicationLanguage
    ) -> LocalizationPipelineRun:
        if language is PublicationLanguage.FA:
            raise ValueError("fa is the master language, not a target")
        async with self.database.transaction() as session:
            package = await session.get(LocalizationSemanticPackage, package_id)
            if package is None:
                raise LookupError(f"Unknown semantic package {package_id}")
            if not await package_is_current(session, package):
                raise GateBlockedError(
                    "STALE_SOURCE — package no longer matches the approved "
                    "Persian draft"
                )
            source = await session.get(ScriptDraft, package.script_draft_id)
            if source is not None:
                session.expunge(source)
        if source is not None:
            eligible = await self._eligibility(source)
            if not eligible.eligible:
                raise GateBlockedError(
                    "LOCALIZATION_RECERTIFICATION_REQUIRED — the approved "
                    "Persian master does not meet current localization "
                    "policy ("
                    + "; ".join(eligible.reasons)
                    + "). Owner options: re-review the existing Persian "
                    "draft, regenerate it under the current pipeline, or "
                    "keep the historical artifact without localization."
                )
        async with self.database.transaction() as session:
            existing = await session.scalar(
                select(LocalizationPipelineRun).where(
                    LocalizationPipelineRun.semantic_package_id == package_id,
                    LocalizationPipelineRun.language == language,
                )
            )
            if existing is not None:
                return existing
            run = LocalizationPipelineRun(
                semantic_package_id=package_id,
                language=language,
                stage=LocalizationPipelineStage.SEMANTIC_ALIGNED,
            )
            session.add(run)
            await session.flush()
            await session.refresh(run)
            return run

    async def coverage_translate(self, run_id: UUID) -> LocalizationPipelineRun:
        run = await self._load_run(run_id)
        if run.stage is not LocalizationPipelineStage.SEMANTIC_ALIGNED:
            raise GateBlockedError(
                f"coverage requires SEMANTIC_ALIGNED, got {run.stage}"
            )
        await self._require_current(run)
        duration_contract = await self._duration_contract(run.language)
        async with self.database.transaction() as session:
            package = await session.get(
                LocalizationSemanticPackage, run.semantic_package_id
            )
            if package is None:
                raise LookupError("semantic package not found")
            source = await session.get(ScriptDraft, package.script_draft_id)
            payload: dict[str, object] = {
                "package": package.payload,
                "source_script": source.text if source is not None else "",
                "language_profile": profile_payload(run.language),
                "duration_contract": duration_contract,
                "language": run.language.value,
            }
        result = await self._extract(
            AgentRole.COVERAGE_TRANSLATION,
            "localization_coverage_translation",
            coverage_translation_instructions(run.language),
            payload,
            ScriptTextOutput,
            run=run,
        )
        text = ScriptTextOutput.model_validate(_dump(result)).text
        return await self._set_stage(
            run_id,
            LocalizationPipelineStage.COVERAGE_TRANSLATED,
            work={"coverage_text": text},
        )

    async def _load_plan_sections(
        self, run: LocalizationPipelineRun
    ) -> list[dict[str, object]]:
        """Narrative-plan sections of the pinned source draft's plan.

        These carry the stable identity (ordinal, role, target_seconds)
        that section word budgets and patch repairs are anchored to.
        """

        async with self.database.transaction() as session:
            package = await session.get(
                LocalizationSemanticPackage, run.semantic_package_id
            )
            source = (
                await session.get(ScriptDraft, package.script_draft_id)
                if package is not None
                else None
            )
            if source is None or source.narrative_plan_id is None:
                return []
            rows = await session.scalars(
                select(NarrativePlanSection)
                .where(
                    NarrativePlanSection.narrative_plan_id == source.narrative_plan_id
                )
                .order_by(NarrativePlanSection.ordinal)
            )
            return [
                {
                    "narrative_role": s.narrative_role,
                    "purpose": s.purpose,
                    "target_seconds": s.target_seconds,
                }
                for s in rows
            ]

    async def _sections_output(
        self,
        role: AgentRole,
        task: str,
        instructions: str,
        payload: dict[str, object],
        budgets: list[SectionBudget],
        *,
        run: LocalizationPipelineRun,
    ) -> list[ScriptSection]:
        """Sectioned writer call with one bounded id-contract retry.

        The writer must return exactly one entry per plan section_id.
        A mismatch is not a schema error — it is a contract violation the
        model gets exactly one chance to repair before the run fails.
        """

        expected = [b.section_id for b in budgets]
        titles = {b.section_id: b.title for b in budgets}
        for attempt in range(2):
            result = await self._extract(
                role, task, instructions, payload, ScriptSectionsOutput, run=run
            )
            output = ScriptSectionsOutput.model_validate(_dump(result))
            ids = [s.section_id for s in output.sections]
            # Contract: exactly one entry per plan section, in order.
            if not expected or ids == expected:
                return sections_from_output(
                    [(s.section_id, s.text) for s in output.sections],
                    titles=titles,
                )
            if attempt == 0:
                payload = {
                    **payload,
                    "section_budgets": [
                        {
                            **b.model_dump(),
                            "note": (
                                "previous output violated the section "
                                "contract — return exactly one entry per "
                                "section_id, in order"
                            ),
                        }
                        for b in budgets
                    ],
                }
        await self._fail(
            run.id,
            "SECTION_ID_MISMATCH — writer returned section ids that do "
            "not match the narrative plan exactly",
        )
        raise GateBlockedError(
            "SECTION_ID_MISMATCH — writer returned section ids that do "
            "not match the narrative plan exactly"
        )

    async def native_draft(self, run_id: UUID) -> LocalizationPipelineRun:
        run = await self._load_run(run_id)
        if run.stage is not LocalizationPipelineStage.COVERAGE_TRANSLATED:
            raise GateBlockedError(
                f"native reconstruction requires COVERAGE_TRANSLATED, got {run.stage}"
            )
        await self._require_current(run)
        async with self.database.transaction() as session:
            package = await session.get(
                LocalizationSemanticPackage, run.semantic_package_id
            )
            package_payload = package.payload if package is not None else {}
            source = (
                await session.get(ScriptDraft, package.script_draft_id)
                if package is not None
                else None
            )
            source_text = source.text if source is not None else ""
        duration_contract = await self._duration_contract(run.language)
        plan_rows = await self._load_plan_sections(run)
        budgets = build_section_plan(
            narrative_sections=plan_rows,
            source_text=source_text,
            target_min=int(str(duration_contract["target_words_min"])),
            target_max=int(str(duration_contract["target_words_max"])),
            wpm=int(str(duration_contract["wpm"])),
        )
        budget_payload = [b.model_dump() for b in budgets]
        payload: dict[str, object] = {
            "package": package_payload,
            "coverage_translation": str(run.work_json.get("coverage_text", "")),
            "language_profile": profile_payload(run.language),
            "duration_contract": duration_contract,
            "section_budgets": budget_payload,
            "language": run.language.value,
        }
        sections = await self._sections_output(
            AgentRole.NATIVE_RECONSTRUCTION,
            "localization_native_reconstruction",
            native_reconstruction_instructions(run.language),
            payload,
            budgets,
            run=run,
        )
        # Narrative edit strengthens flow within the same editorial pass —
        # same section ids, budgets still apply.
        edit_payload: dict[str, object] = {
            "package": package_payload,
            "native_draft": labeled_script(sections),
            "language_profile": profile_payload(run.language),
            "duration_contract": duration_contract,
            "section_budgets": budget_payload,
            "language": run.language.value,
        }
        native_text = join_sections(sections)
        sections = await self._sections_output(
            AgentRole.LANGUAGE_NARRATIVE_EDITOR,
            "localization_narrative_edit",
            narrative_editor_instructions(run.language),
            edit_payload,
            budgets,
            run=run,
        )
        # §15 pre-review length gate: never burn critic loops on a draft
        # whose spoken length misses the band — repair it section-wise
        # first (max two deterministic length passes).
        length_repairs = 0
        for attempt in range(3):
            total = sum(s.words for s in sections)
            if (
                int(str(duration_contract["target_words_min"]))
                <= total
                <= int(str(duration_contract["target_words_max"]))
            ):
                break
            if attempt == 2:
                return await self._fail(
                    run_id,
                    f"GENERATION_LENGTH_FAILED — {total} words remains "
                    "outside the generation band after 2 length repairs",
                )
            sections, _ = await self._length_repair(
                run, sections, budget_map(budgets), package_payload
            )
            length_repairs += 1
        edited_text = join_sections(sections)
        await self._persist_draft(
            run, edited_text, kind="native_draft", sections=sections
        )
        return await self._set_stage(
            run_id,
            LocalizationPipelineStage.NATIVE_DRAFTED,
            work={
                "section_plan": budget_payload,
                "native_text": native_text,
                "generation_length_repairs": length_repairs,
            },
        )

    async def _persist_draft(
        self,
        run: LocalizationPipelineRun,
        text: str,
        *,
        kind: str,
        sections: list[ScriptSection] | None = None,
        extra_provenance: dict[str, object] | None = None,
    ) -> ScriptDraft:
        if sections is None:
            # Every localized draft carries a stable section map — patch
            # repair must be able to address any artifact section-wise.
            sections = sections_from_paragraph_groups(text)
        async with self.database.transaction() as session:
            package = await session.get(
                LocalizationSemanticPackage, run.semantic_package_id
            )
            source = (
                await session.get(ScriptDraft, package.script_draft_id)
                if package is not None
                else None
            )
            if package is None or source is None:
                raise LookupError("package or source draft missing")
            version = (
                await session.scalar(
                    select(
                        func.coalesce(func.max(ScriptDraft.version_number), 0)
                    ).where(
                        ScriptDraft.content_brief_id == source.content_brief_id,
                        ScriptDraft.language == run.language.value,
                        ScriptDraft.lineage == "localized",
                    )
                )
                or 0
            ) + 1
            effective = await StudioSettingsService(self.database).effective()
            effective.update(self.effective_overrides)
            wpm = speech_wpm(effective, run.language.value)
            words = len(text.split())
            # Truthful provenance: record the model resolved for the role
            # that produced this artifact, not a placeholder.
            kind_role = _KIND_TO_ROLE.get(kind)
            model_used = (
                model_for_role(
                    AGENT_TO_MODEL_ROLE[kind_role],
                    get_settings(),
                    effective=effective,
                )
                if kind_role is not None
                else self.model
            )
            draft = ScriptDraft(
                content_brief_id=source.content_brief_id,
                narrative_plan_id=source.narrative_plan_id,
                lecture_master_version_id=source.lecture_master_version_id,
                language=run.language.value,
                lineage="localized",
                version_number=version,
                text=text,
                status=DraftStatus.DRAFT,
                provenance_json={
                    "localization_run_id": str(run.id),
                    "semantic_package_id": str(package.id),
                    "source_draft_id": str(source.id),
                    "source_draft_hash": package.source_draft_hash,
                    "kind": kind,
                    "model": model_used,
                    "sections": section_provenance(sections),
                    **(extra_provenance or {}),
                },
                content_hash=_hash(text),
                target_duration_minutes=source.target_duration_minutes,
                actual_word_count=words,
                estimated_duration_seconds=int(words / wpm * 60),
            )
            session.add(draft)
            await session.flush()
            run_row = await session.get(LocalizationPipelineRun, run.id)
            if run_row is not None:
                run_row.script_draft_id = draft.id
                run_row.updated_at = utc_now()
            await session.flush()
            await session.refresh(draft)
            return draft

    # ---------------------------------------------------------------
    # stage 2: native + fidelity critique (one review loop)
    # ---------------------------------------------------------------

    async def review(self, run_id: UUID) -> list[ReviewFinding]:
        """Run native/audience (editorial) + fidelity (reasoning) critics."""

        run = await self._load_run(run_id)
        if run.stage is not LocalizationPipelineStage.NATIVE_DRAFTED:
            raise GateBlockedError(f"review requires NATIVE_DRAFTED, got {run.stage}")
        await self._require_current(run)
        async with self.database.transaction() as session:
            package = await session.get(
                LocalizationSemanticPackage, run.semantic_package_id
            )
            draft = (
                await session.get(ScriptDraft, run.script_draft_id)
                if run.script_draft_id
                else None
            )
            if package is None or draft is None:
                raise LookupError("package or localized draft missing")
            package_payload = package.payload
            draft_text = draft.text
            draft_id = draft.id
            draft_sections = restore_sections(
                (draft.provenance_json or {}).get("sections"), draft.text
            )

        language = run.language
        # Critics see section labels so findings route to the right
        # patch target; audience-facing prose never contains them.
        labeled = labeled_script(draft_sections)
        findings_payloads: list[dict[str, object]] = []
        # Native spoken critic — language-model family owns native judgment.
        native = await self._extract(
            AgentRole.NATIVE_SPOKEN_CRITIC,
            "localization_native_critic",
            native_critic_instructions(language),
            {
                "target_script": labeled,
                "language_profile": profile_payload(language),
                "language": language.value,
            },
            PipelineFindingsOutput,
            run=run,
        )
        for item in PipelineFindingsOutput.model_validate(_dump(native)).findings:
            findings_payloads.append({"critic_role": "NATIVE_SPOKEN", **_dump(item)})
        # Audience retention — quality is more than grammar.
        audience = await self._extract(
            AgentRole.AUDIENCE_RETENTION_CRITIC,
            "localization_audience_critic",
            audience_critic_instructions(language),
            {
                "target_script": labeled,
                "language_profile": profile_payload(language),
                "language": language.value,
            },
            PipelineFindingsOutput,
            run=run,
        )
        for item in PipelineFindingsOutput.model_validate(_dump(audience)).findings:
            findings_payloads.append(
                {"critic_role": "AUDIENCE_RETENTION", **_dump(item)}
            )
        # Fidelity critic — reasoning model owns semantic truth.
        fidelity = await self._extract(
            AgentRole.FIDELITY_CRITIC,
            "localization_fidelity_critic",
            fidelity_critic_instructions(language),
            {
                "package": package_payload,
                "target_script": labeled,
                "language": language.value,
            },
            PipelineFindingsOutput,
            run=run,
        )
        fidelity_findings = PipelineFindingsOutput.model_validate(
            _dump(fidelity)
        ).findings
        for item in fidelity_findings:
            findings_payloads.append({"critic_role": "FIDELITY", **_dump(item)})
        # Deterministic duration check inside the review loop — the final
        # gate would block on length anyway; surfacing it here lets the
        # bounded correction expand/trim using package material only.
        contract = await self._duration_contract(language)
        words = len(draft_text.split())
        wpm = int(str(contract["wpm"]))
        target_min = int(str(contract["target_words_min"]))
        target_max = int(str(contract["target_words_max"]))
        if words < target_min:
            findings_payloads.append(
                {
                    "critic_role": "DURATION",
                    "severity": FindingSeverity.BLOCKER.value,
                    "code": "DURATION_TOO_SHORT",
                    "location": "whole script",
                    "explanation": (
                        f"{words} words ≈ {words / wpm:.1f} min at {wpm} wpm — "
                        f"below the {contract['min_minutes']}-min floor "
                        f"({target_min} words)."
                    ),
                    "correction_constraint": (
                        "Expand ONLY by deepening claims, story facts, "
                        "qualifiers and evidence already present in the "
                        "semantic package — never new claims, anecdotes, "
                        "numbers, or certainty. Prefer elaborating existing "
                        "passages over adding sections."
                    ),
                }
            )
        elif words > target_max:
            findings_payloads.append(
                {
                    "critic_role": "DURATION",
                    "severity": FindingSeverity.BLOCKER.value,
                    "code": "DURATION_TOO_LONG",
                    "location": "whole script",
                    "explanation": (
                        f"{words} words ≈ {words / wpm:.1f} min at {wpm} wpm — "
                        f"above the {contract['max_minutes']}-min ceiling "
                        f"({target_max} words)."
                    ),
                    "correction_constraint": (
                        "Trim by merging repeated passages and tightening "
                        "phrasing — never remove claims, qualifiers, "
                        "evidence references, or load-bearing caveats."
                    ),
                }
            )

        async with self.database.transaction() as session:
            draft = await session.get(ScriptDraft, draft_id)
            run_row = await session.get(LocalizationPipelineRun, run_id)
            if draft is None or run_row is None:
                raise LookupError("run or draft vanished")
            loop = run_row.review_loop + 1
            run_row.review_loop = loop
            findings: list[ReviewFinding] = []
            for fitem in findings_payloads:
                finding = ReviewFinding(
                    script_draft_id=draft.id,
                    review_run_id=None,
                    critic_role=str(fitem["critic_role"]),
                    severity=FindingSeverity(str(fitem["severity"])),
                    location=str(fitem["location"]),
                    section_id=str(fitem.get("section_id") or ""),
                    code=str(fitem["code"]),
                    explanation=str(fitem["explanation"]),
                    correction_constraint=str(fitem["correction_constraint"]),
                )
                session.add(finding)
                findings.append(finding)

            # ---- monotonic best-candidate retention (§2–4) ----
            # The reviewed draft is a CANDIDATE; a newer revision may
            # only replace the best when it is strictly better under the
            # hard ordering. A rejected candidate restores the best and
            # reopens the findings its repair was meant to address.
            contract = await self._duration_contract(language)
            target_min = int(str(contract["target_words_min"]))
            target_max = int(str(contract["target_words_max"]))
            draft_words = len(draft_text.split())
            rank = candidate_rank(
                blockers=sum(
                    1 for f in findings if f.severity is FindingSeverity.BLOCKER
                ),
                warnings=sum(
                    1 for f in findings if f.severity is FindingSeverity.WARNING
                ),
                fidelity_failed=any(
                    f.critic_role == "FIDELITY"
                    and f.severity is FindingSeverity.BLOCKER
                    for f in findings
                ),
                duration_in_band=target_min <= draft_words <= target_max,
                encoding_clean="\ufffd" not in draft_text,
                total_findings=len(findings),
            )
            work = dict(run_row.work_json)
            best_raw = work.get("best")
            best = best_raw if isinstance(best_raw, dict) else None
            decisions_raw = work.get("candidate_decisions")
            decisions = list(decisions_raw) if isinstance(decisions_raw, list) else []
            decision_entry: dict[str, object] = {
                "loop": loop,
                "candidate_draft_id": str(draft.id),
                "rank": list(rank),
            }
            best_rank_raw = best.get("rank") if best else None
            incumbent = (
                tuple(int(x) for x in best_rank_raw)
                if isinstance(best_rank_raw, (list, tuple))
                else tuple(rank)
            )
            if best is None:
                work["best"] = {"draft_id": str(draft.id), "rank": list(rank)}
                decision_entry["decision"] = "seeded"
                decision_entry["reason"] = "first reviewed candidate"
            elif is_better_candidate(tuple(rank), incumbent):
                work["best"] = {"draft_id": str(draft.id), "rank": list(rank)}
                decision_entry["decision"] = "promoted"
                decision_entry["reason"] = "strictly better under the hard ordering"
            else:
                # Reject: the repair churned unrelated text. Restore the
                # best draft and reopen the findings this candidate was
                # produced to address — they still stand.
                repairs_raw = work.get("repairs")
                repairs = list(repairs_raw) if isinstance(repairs_raw, list) else []
                addressed: list[UUID] = []
                for entry in repairs:
                    if isinstance(entry, dict) and entry.get(
                        "candidate_draft_id"
                    ) == str(draft.id):
                        entry_addressed = entry.get("addressed") or []
                        addressed = [
                            UUID(str(fid))
                            for fid in entry_addressed
                            if isinstance(fid, str)
                        ]
                if addressed:
                    reopened = list(
                        await session.scalars(
                            select(ReviewFinding).where(ReviewFinding.id.in_(addressed))
                        )
                    )
                    for f in reopened:
                        f.status = FindingStatus.OPEN
                        f.resolution_note = "candidate rejected — finding reopened"
                best_id = UUID(str(best["draft_id"]))
                run_row.script_draft_id = best_id
                decision_entry["decision"] = "rejected"
                decision_entry["reason"] = (
                    "not strictly better — previous best restored"
                )
                decision_entry["reopened_findings"] = len(addressed)
            decisions.append(decision_entry)
            work["candidate_decisions"] = decisions
            work[f"findings_loop_{loop}"] = [
                {
                    "critic_role": f.critic_role,
                    "severity": f.severity.value,
                    "code": f.code,
                    "location": f.location,
                    "section_id": f.section_id,
                }
                for f in findings
            ]
            run_row.work_json = work

            # Statuses reflect the draft now current (the best after a
            # possible rollback), not the rejected candidate.
            current_open = list(
                await session.scalars(
                    select(ReviewFinding).where(
                        ReviewFinding.script_draft_id == run_row.script_draft_id,
                        ReviewFinding.status == FindingStatus.OPEN,
                    )
                )
            )
            current_blocking = [
                f for f in current_open if f.severity is FindingSeverity.BLOCKER
            ]
            run_row.native_status = (
                "FAILED"
                if any(
                    f.critic_role in ("NATIVE_SPOKEN", "AUDIENCE_RETENTION")
                    and f.severity is FindingSeverity.BLOCKER
                    for f in current_open
                )
                else "PASSED"
            )
            run_row.fidelity_status = (
                "FAILED"
                if any(
                    f.critic_role == "FIDELITY"
                    and f.severity is FindingSeverity.BLOCKER
                    for f in current_open
                )
                else "PASSED"
            )
            run_row.stage = (
                LocalizationPipelineStage.FIDELITY_REVIEW
                if not current_blocking
                else LocalizationPipelineStage.NATIVE_REVIEW
            )
            run_row.updated_at = utc_now()
            await session.flush()
            return findings

    def _resolve_section(
        self, finding: ReviewFinding, sections: list[ScriptSection]
    ) -> str:
        """Map a persisted finding to the owning section id ("" = global).

        The critic-supplied section_id wins; otherwise the finding's
        location string is matched verbatim against section text. No
        fuzzy matching — an unresolvable finding stays global rather
        than guessing at a target.
        """

        ids = {s.section_id for s in sections}
        if finding.section_id in ids:
            return finding.section_id
        location = (finding.location or "").strip()
        if location:
            needle = " ".join(location.split())
            for s in sections:
                if needle and needle in " ".join(s.text.split()):
                    return s.section_id
        return ""

    async def _patch_repair_call(
        self,
        run: LocalizationPipelineRun,
        role: AgentRole,
        task: str,
        instructions: str,
        payload: dict[str, object],
    ) -> PatchSetOutput:
        result = await self._extract(
            role, task, instructions, payload, PatchSetOutput, run=run
        )
        return PatchSetOutput.model_validate(_dump(result))

    @staticmethod
    def _word_budget_entry(
        section: ScriptSection, budgets: dict[str, SectionBudget]
    ) -> dict[str, object]:
        """The section's length contract for the patch model.

        Without it a repair that removes unsupported content shrinks the
        section silently and the candidate fails the duration band —
        the model must rebuild at comparable length instead of deleting.
        """

        budget = budgets.get(section.section_id)
        entry: dict[str, object] = {"current_words": section.words}
        if budget is not None:
            entry.update(
                {
                    "min_words": budget.min_words,
                    "target_words": budget.target_words,
                    "max_words": budget.max_words,
                }
            )
        return entry

    async def _section_patch_call(
        self,
        run: LocalizationPipelineRun,
        sections: list[ScriptSection],
        findings: list[ReviewFinding],
        package_payload: dict[str, object],
        *,
        idx: int,
        section_id: str,
        budgets: dict[str, SectionBudget] | None = None,
    ) -> PatchSetOutput:
        """One scoped patch call for the findings of a single section."""

        section = next(s for s in sections if s.section_id == section_id)
        pos = idx
        neighbor_context: dict[str, object] = {}
        if pos > 0:
            neighbor_context["before"] = sections[pos - 1].text[:400]
        if pos < len(sections) - 1:
            neighbor_context["after"] = sections[pos + 1].text[:400]
        semantic = any(
            f.critic_role in ("FIDELITY", "FINAL_FIDELITY_GATE") for f in findings
        )
        role = (
            AgentRole.SEMANTIC_PATCH_REPAIR
            if semantic
            else AgentRole.TARGETED_LOCALIZATION_REPAIR
        )
        payload: dict[str, object] = {
            "package": package_payload,
            "target_sections": [
                {
                    "section_id": section.section_id,
                    "sha256": section.sha256,
                    "text": section.text,
                    "word_budget": self._word_budget_entry(section, budgets or {}),
                }
            ],
            "neighbor_context": neighbor_context,
            # What the source supports — the repair model must be able to
            # see it without excavating the whole package (claim_ledger
            # is legitimately empty for some packages).
            "relevant_claims": _supported_material(package_payload),
            "findings": [
                {
                    "location": f.location,
                    "code": f.code,
                    "severity": f.severity.value,
                    "explanation": f.explanation,
                    "correction_constraint": f.correction_constraint,
                }
                for f in findings
            ],
            "language_profile": profile_payload(run.language),
            "language": run.language.value,
        }
        return await self._patch_repair_call(
            run,
            role,
            "localization_section_patch",
            patch_repair_instructions(run.language),
            payload,
        )

    async def _global_patch_call(
        self,
        run: LocalizationPipelineRun,
        sections: list[ScriptSection],
        findings: list[ReviewFinding],
        package_payload: dict[str, object],
        *,
        budgets: dict[str, SectionBudget] | None = None,
    ) -> PatchSetOutput:
        """Patch call for findings that span the whole script."""

        semantic = any(
            f.critic_role in ("FIDELITY", "FINAL_FIDELITY_GATE") for f in findings
        )
        role = (
            AgentRole.SEMANTIC_PATCH_REPAIR
            if semantic
            else AgentRole.TARGETED_LOCALIZATION_REPAIR
        )
        payload: dict[str, object] = {
            "target_script": labeled_script(sections),
            "package": package_payload,
            "section_budgets": [
                {
                    "section_id": s.section_id,
                    "word_budget": self._word_budget_entry(s, budgets or {}),
                }
                for s in sections
            ],
            "findings": [
                {
                    "location": f.location,
                    "code": f.code,
                    "severity": f.severity.value,
                    "explanation": f.explanation,
                    "correction_constraint": f.correction_constraint,
                }
                for f in findings
            ],
            "language_profile": profile_payload(run.language),
            "language": run.language.value,
        }
        return await self._patch_repair_call(
            run,
            role,
            "localization_global_patch",
            patch_repair_instructions(run.language),
            payload,
        )

    async def _length_repair(
        self,
        run: LocalizationPipelineRun,
        sections: list[ScriptSection],
        budgets: dict[str, SectionBudget],
        package_payload: dict[str, object],
    ) -> tuple[list[ScriptSection], int]:
        """Deterministic length repair — explicit per-section word targets.

        Compression goes to the multilingual editorial model; expansion
        is semantic work (restoring compressed package material) and
        goes to professional reasoning (§16–18). Returns the patched
        sections and how many patches were applied.
        """

        contract = await self._duration_contract(run.language)
        plan = length_repair_plan(
            sections,
            budgets,
            target_min=int(str(contract["target_words_min"])),
            target_max=int(str(contract["target_words_max"])),
        )
        applied = 0
        if not plan:
            return sections, applied
        for direction in ("compress", "expand"):
            targets = [t for t in plan if t.direction == direction]
            if not targets:
                continue
            target_sections = [
                {
                    "section_id": t.section_id,
                    "sha256": next(
                        s.sha256 for s in sections if s.section_id == t.section_id
                    ),
                    "text": next(
                        s.text for s in sections if s.section_id == t.section_id
                    ),
                }
                for t in targets
            ]
            role = (
                AgentRole.DURATION_ADJUSTMENT
                if direction == "compress"
                else AgentRole.SEMANTIC_PATCH_REPAIR
            )
            payload: dict[str, object] = {
                "package": package_payload,
                "target_sections": target_sections,
                "section_targets": [t.model_dump() for t in targets],
                "relevant_claims": _supported_material(package_payload),
                "language_profile": profile_payload(run.language),
                "duration_contract": contract,
                "language": run.language.value,
            }
            output = await self._patch_repair_call(
                run,
                role,
                f"localization_length_{direction}",
                length_repair_instructions(run.language),
                payload,
            )
            result = apply_patches(sections, output)
            sections = result.sections
            applied += len(result.applied)
        return sections, applied

    async def correct(self, run_id: UUID) -> LocalizationPipelineRun:
        """Patch-based correction of open findings — never a blind rewrite.

        Findings are grouped by owning section; each section's findings
        go to one scoped patch call, hash-verified and deterministically
        spliced (§6–11). The result is a CANDIDATE — review decides
        whether it beats the retained best.
        """

        run = await self._load_run(run_id)
        if run.stage not in (
            LocalizationPipelineStage.NATIVE_REVIEW,
            LocalizationPipelineStage.FIDELITY_REVIEW,
        ):
            raise GateBlockedError(f"correction requires a review, got {run.stage}")
        await self._require_current(run)
        async with self.database.transaction() as session:
            draft_id = run.script_draft_id
            draft = (
                await session.get(ScriptDraft, draft_id)
                if draft_id is not None
                else None
            )
            if draft is None:
                raise LookupError("localized draft missing")
            open_findings = list(
                await session.scalars(
                    select(ReviewFinding).where(
                        ReviewFinding.script_draft_id == draft.id,
                        ReviewFinding.status == FindingStatus.OPEN,
                    )
                )
            )
            package = await session.get(
                LocalizationSemanticPackage, run.semantic_package_id
            )
            package_payload = package.payload if package is not None else {}
            sections = restore_sections(
                (draft.provenance_json or {}).get("sections"), draft.text
            )
        majors = [
            f
            for f in open_findings
            if f.severity in (FindingSeverity.BLOCKER, FindingSeverity.WARNING)
        ]
        duration_only_pass = False
        if run.review_loop > MAX_REVIEW_LOOPS:
            # The quality-loop budget is spent, but a draft whose only
            # remaining blocker is the deterministic length contract gets
            # exactly one dedicated duration pass — bounded, re-verified
            # by a full review afterwards, never a waiver.
            blockers = [
                f for f in open_findings if f.severity is FindingSeverity.BLOCKER
            ]
            duration_repairs = int(str(run.work_json.get("duration_only_repairs") or 0))
            if (
                not blockers
                or any(f.critic_role != "DURATION" for f in blockers)
                or duration_repairs >= 1
            ):
                return await self._set_stage(
                    run_id,
                    LocalizationPipelineStage.BLOCKED,
                    error="review loop budget exhausted",
                )
            majors = blockers
            duration_only_pass = True
        if not majors:
            return await self._set_stage(
                run_id, LocalizationPipelineStage.FIDELITY_REVIEW
            )

        # DURATION findings repair by explicit word-target patches, not
        # by open-ended correction instructions.
        duration_findings = [f for f in majors if f.critic_role == "DURATION"]
        semantic_findings = [f for f in majors if f.critic_role != "DURATION"]
        budgets_raw = run.work_json.get("section_plan")
        budgets = budget_map(
            [
                SectionBudget.model_validate(b)
                for b in (budgets_raw if isinstance(budgets_raw, list) else [])
            ]
        )

        patches: list[PatchOp] = []
        rejected_ops: list[dict[str, object]] = []
        rewrite_required = False
        # Group resolvable findings by section; unresolvable ones get a
        # single scoped-global patch call on the labeled script.
        by_section: dict[str, list[ReviewFinding]] = {}
        global_findings: list[ReviewFinding] = []
        for f in semantic_findings:
            sid = self._resolve_section(f, sections)
            if sid:
                by_section.setdefault(sid, []).append(f)
            else:
                global_findings.append(f)
        for sid, group in by_section.items():
            idx = next(i for i, s in enumerate(sections) if s.section_id == sid)
            output = await self._section_patch_call(
                run,
                sections,
                group,
                package_payload,
                idx=idx,
                section_id=sid,
                budgets=budgets,
            )
            rewrite_required = rewrite_required or output.full_rewrite_required
            patches.extend(output.patches)
        if global_findings:
            output = await self._global_patch_call(
                run, sections, global_findings, package_payload, budgets=budgets
            )
            rewrite_required = rewrite_required or output.full_rewrite_required
            patches.extend(output.patches)
        # §11: a model may declare the architecture genuinely broken —
        # at most once per run, via the premium targeted-revision role.
        if rewrite_required and not run.work_json.get("full_rewrite_used"):
            rewrite = await self._full_rewrite(
                run, sections, semantic_findings, package_payload, budgets
            )
            if rewrite is not None:
                new_draft = await self._persist_draft(
                    run,
                    join_sections(rewrite),
                    kind="full_rewrite_candidate",
                    sections=rewrite,
                    extra_provenance={
                        "parent_draft_id": str(draft.id),
                        "candidate": True,
                    },
                )
                await self._mark_addressed(
                    run_id, open_findings, new_draft.id, "full rewrite applied"
                )
                return await self._set_stage(
                    run_id,
                    LocalizationPipelineStage.NATIVE_DRAFTED,
                    work={"full_rewrite_used": True},
                )

        # Apply semantic patches first; the length plan is then derived
        # on the patched text so its hash checks stay truthful.
        result = apply_patches(sections, PatchSetOutput(patches=patches))
        rejected_ops.extend(
            {"section_id": r.section_id, "reason": r.reason} for r in result.rejected
        )
        applied = len(result.applied)
        if patches and applied == 0:
            # One retry: stale/malformed hashes get a second attempt
            # before the loop re-reviews unchanged text.
            retry_patches: list[PatchOp] = []
            for sid, group in by_section.items():
                idx = next(i for i, s in enumerate(sections) if s.section_id == sid)
                output = await self._section_patch_call(
                    run,
                    sections,
                    group,
                    package_payload,
                    idx=idx,
                    section_id=sid,
                    budgets=budgets,
                )
                retry_patches.extend(output.patches)
            if global_findings:
                output = await self._global_patch_call(
                    run, sections, global_findings, package_payload, budgets=budgets
                )
                retry_patches.extend(output.patches)
            result = apply_patches(sections, PatchSetOutput(patches=retry_patches))
            applied = len(result.applied)

        if duration_findings:
            length_sections, length_applied = await self._length_repair(
                run, result.sections, budgets, package_payload
            )
            result = PatchResult(
                sections=length_sections,
                applied=result.applied,
                rejected=result.rejected,
            )
            applied += length_applied

        if applied == 0:
            # Nothing the model returned could be applied — do not fake a
            # repair or persist an identical candidate. The unchanged
            # draft is re-reviewed so the loop stays honest and budgeted.
            return await self._set_stage(
                run_id,
                LocalizationPipelineStage.NATIVE_DRAFTED,
                work={
                    "last_patch": {
                        "applied": [],
                        "rejected": rejected_ops,
                        "note": "no applicable patches returned",
                    }
                },
            )

        new_draft = await self._persist_draft(
            run,
            join_sections(result.sections),
            kind="targeted_patch",
            sections=result.sections,
            extra_provenance={
                "parent_draft_id": str(draft.id),
                "candidate": True,
                "patch": {
                    "applied": [
                        {
                            "section_id": a.section_id,
                            "finding_ids": list(a.finding_ids),
                            "reason": a.reason,
                        }
                        for a in result.applied
                    ],
                    "rejected": rejected_ops,
                },
            },
        )
        await self._mark_addressed(
            run_id,
            open_findings,
            new_draft.id,
            "duration-only patch applied"
            if duration_only_pass
            else "targeted patch applied",
        )
        if duration_only_pass:
            await self._set_stage(
                run_id,
                LocalizationPipelineStage.NATIVE_DRAFTED,
                work={
                    "duration_only_repairs": int(
                        str(run.work_json.get("duration_only_repairs") or 0)
                    )
                    + 1
                },
            )
        return await self._set_stage(run_id, LocalizationPipelineStage.NATIVE_DRAFTED)

    async def _mark_addressed(
        self,
        run_id: UUID,
        findings: list[ReviewFinding],
        candidate_draft_id: UUID,
        note: str,
    ) -> None:
        """Mark findings ADDRESSED and record the repair provenance.

        The `repairs` work_json entry lets review() reopen exactly these
        findings if the candidate they produced is rejected.
        """

        addressed_ids = [str(f.id) for f in findings]
        async with self.database.transaction() as session:
            rows = list(
                await session.scalars(
                    select(ReviewFinding).where(
                        ReviewFinding.id.in_([f.id for f in findings])
                    )
                )
            )
            for f in rows:
                f.status = FindingStatus.ADDRESSED
                f.resolution_actor = "pipeline"
                f.resolution_note = note
            run_row = await session.get(LocalizationPipelineRun, run_id)
            if run_row is not None:
                repairs_raw = run_row.work_json.get("repairs")
                repairs = list(repairs_raw) if isinstance(repairs_raw, list) else []
                repairs.append(
                    {
                        "candidate_draft_id": str(candidate_draft_id),
                        "addressed": addressed_ids,
                    }
                )
                run_row.work_json = {**run_row.work_json, "repairs": repairs}
            await session.flush()

    async def _full_rewrite(
        self,
        run: LocalizationPipelineRun,
        sections: list[ScriptSection],
        findings: list[ReviewFinding],
        package_payload: dict[str, object],
        budgets: dict[str, SectionBudget],
    ) -> list[ScriptSection] | None:
        """One classified FULL_REWRITE via the premium revision role (§11).

        Fires only when a patch model declared section-wise repair
        impossible. Returns None when the rewrite also violates the
        section contract — the findings stay open.
        """

        contract = await self._duration_contract(run.language)
        payload: dict[str, object] = {
            "package": package_payload,
            "target_script": labeled_script(sections),
            "section_budgets": [b.model_dump() for b in budgets.values()],
            "findings": [
                {
                    "location": f.location,
                    "code": f.code,
                    "severity": f.severity.value,
                    "explanation": f.explanation,
                    "correction_constraint": f.correction_constraint,
                }
                for f in findings
            ],
            "language_profile": profile_payload(run.language),
            "duration_contract": contract,
            "language": run.language.value,
        }
        result = await self._extract(
            AgentRole.PREMIUM_TARGETED_REVISION,
            "localization_full_rewrite",
            (
                "The section-wise repair model declared this script's "
                "architecture genuinely broken (FULL_REWRITE_REQUIRED). "
                "Rewrite it completely — keep every section_id and stay "
                "inside each section's word budget. The semantic package "
                "is the sole authority: never add claims, evidence, "
                "examples, numbers, or stronger certainty. Output only "
                "audience-facing prose per section."
            ),
            payload,
            ScriptSectionsOutput,
            run=run,
        )
        output = ScriptSectionsOutput.model_validate(_dump(result))
        expected = [s.section_id for s in sections]
        ids = [s.section_id for s in output.sections]
        if expected and ids != expected:
            return None
        return sections_from_output(
            [(s.section_id, s.text) for s in output.sections],
            titles={s.section_id: s.title for s in sections},
        )

    # ---------------------------------------------------------------
    # stage 3: premium final edit (synchronous — APIMaster has no batch API)
    # ---------------------------------------------------------------

    async def premium_final(self, run_id: UUID) -> LocalizationPipelineRun:
        """Premium final edit on the configured premium model, then gate."""

        run = await self._load_run(run_id)
        if run.stage is not LocalizationPipelineStage.FIDELITY_REVIEW:
            raise GateBlockedError(
                f"premium final requires FIDELITY_REVIEW, got {run.stage}"
            )
        await self._require_current(run)
        duration_contract = await self._duration_contract(run.language)
        async with self.database.transaction() as session:
            run_draft_id = run.script_draft_id
            draft = (
                await session.get(ScriptDraft, run_draft_id)
                if run_draft_id is not None
                else None
            )
            package = await session.get(
                LocalizationSemanticPackage, run.semantic_package_id
            )
            if draft is None:
                raise LookupError("localized draft missing")
            fidelity_findings = [
                {
                    "code": f.code,
                    "severity": f.severity.value,
                    "location": f.location,
                    "correction_constraint": f.correction_constraint,
                }
                for f in await session.scalars(
                    select(ReviewFinding).where(
                        ReviewFinding.script_draft_id == draft.id,
                        ReviewFinding.critic_role == "FIDELITY",
                    )
                )
            ]
            native_findings = [
                {
                    "code": f.code,
                    "severity": f.severity.value,
                    "location": f.location,
                    "correction_constraint": f.correction_constraint,
                }
                for f in await session.scalars(
                    select(ReviewFinding).where(
                        ReviewFinding.script_draft_id == draft.id,
                        ReviewFinding.critic_role.in_(
                            ["NATIVE_SPOKEN", "AUDIENCE_RETENTION"]
                        ),
                    )
                )
            ]
            payload: dict[str, object] = {
                "native_draft": draft.text,
                "package": package.payload if package is not None else {},
                "fidelity_findings": fidelity_findings,
                "native_findings": native_findings,
                "language_profile": profile_payload(run.language),
                "duration_contract": duration_contract,
                "language": run.language.value,
            }

        result = await self._extract(
            AgentRole.TARGET_FINAL_EDITOR,
            "localization_final_edit",
            final_editor_instructions(run.language),
            payload,
            ScriptTextOutput,
            timeout_seconds=600,
            run=run,
        )
        text = ScriptTextOutput.model_validate(_dump(result)).text
        # §21: the premium edit is a CANDIDATE. finalize() compares it
        # against the pre-Astra best under the same hard ordering — a
        # regression restores the better version instead of losing it.
        await self._persist_draft(
            run,
            text,
            kind="premium_candidate",
            extra_provenance={
                "parent_draft_id": str(run_draft_id),
                "candidate": True,
            },
        )
        return await self._set_stage(
            run_id,
            LocalizationPipelineStage.FINAL_FIDELITY,
            work={"pre_astra_draft_id": str(run_draft_id)},
        )

    # ---------------------------------------------------------------
    # stage 4: final fidelity + deterministic gates → READY_FOR_VOICE
    # ---------------------------------------------------------------

    async def finalize(self, run_id: UUID) -> LocalizationPipelineRun:
        run = await self._load_run(run_id)
        if run.stage is not LocalizationPipelineStage.FINAL_FIDELITY:
            raise GateBlockedError(f"finalize requires FINAL_FIDELITY, got {run.stage}")
        await self._require_current(run)
        async with self.database.transaction() as session:
            package = await session.get(
                LocalizationSemanticPackage, run.semantic_package_id
            )
            run_draft_id = run.script_draft_id
            draft = (
                await session.get(ScriptDraft, run_draft_id)
                if run_draft_id is not None
                else None
            )
            package_payload = package.payload if package is not None else {}
            source_text = ""
            if package is not None:
                source = await session.get(ScriptDraft, package.script_draft_id)
                source_text = source.text if source is not None else ""
            draft_text = draft.text if draft is not None else ""
            draft_id = draft.id if draft is not None else None

        gate = await self._extract(
            AgentRole.FINAL_FIDELITY_GATE,
            "localization_final_fidelity",
            fidelity_critic_instructions(run.language),
            {
                "package": package_payload,
                "target_script": draft_text,
                "language": run.language.value,
            },
            PipelineFindingsOutput,
            run=run,
        )
        gate_findings = PipelineFindingsOutput.model_validate(_dump(gate)).findings
        semantic_blockers = [
            f for f in gate_findings if f.severity is FindingSeverity.BLOCKER
        ]
        persisted_blockers: list[ReviewFinding] = []
        async with self.database.transaction() as session:
            run_row = await session.get(LocalizationPipelineRun, run_id)
            if run_row is None:
                raise LookupError("run vanished")
            run_row.fidelity_status = "FAILED" if semantic_blockers else "PASSED"
            if semantic_blockers and draft_id is not None:
                for item in semantic_blockers:
                    finding = ReviewFinding(
                        script_draft_id=draft_id,
                        review_run_id=None,
                        critic_role="FINAL_FIDELITY_GATE",
                        severity=item.severity,
                        location=item.location,
                        section_id=item.section_id,
                        code=item.code,
                        explanation=item.explanation,
                        correction_constraint=item.correction_constraint,
                    )
                    session.add(finding)
                    persisted_blockers.append(finding)
            await session.flush()
            for finding in persisted_blockers:
                session.expunge(finding)

        if semantic_blockers:
            repairs = int(str(run.work_json.get("post_premium_repairs") or 0))
            if repairs < MAX_POST_PREMIUM_REPAIRS:
                # A few localized defects after the premium edit do not
                # justify regenerating the whole script — patch repair,
                # then the caller re-runs finalize for a fresh gate pass.
                await self._post_premium_repair(
                    run,
                    draft_id,
                    package_payload,
                    persisted_blockers,
                )
                async with self.database.transaction() as session:
                    run_row = await session.get(LocalizationPipelineRun, run_id)
                    if run_row is None:
                        raise LookupError("run vanished")
                    run_row.work_json = {
                        **run_row.work_json,
                        "post_premium_repairs": repairs + 1,
                    }
                    await session.flush()
                return await self._set_stage(
                    run_id, LocalizationPipelineStage.FINAL_FIDELITY
                )
            return await self._reject_or_block(
                run_id,
                run,
                "final fidelity gate: blocking semantic findings",
            )
        effective = await StudioSettingsService(self.database).effective()
        wpm = speech_wpm(effective, run.language.value)
        findings, words, minutes = validate_target_script(
            draft_text,
            run.language,
            min_minutes=float(str(effective.get("target_duration_min_minutes", 25))),
            max_minutes=float(str(effective.get("target_duration_max_minutes", 30))),
            wpm=wpm,
        )
        # Only the package's explicit term lists scope canonical
        # enforcement — free prose (notes, claims) can mention a Persian
        # form incidentally without meaning the canonical term.
        term_lists: list[object] = []
        for key in ("protected_terms", "terminology_references"):
            raw_terms = package_payload.get(key)
            if isinstance(raw_terms, list):
                term_lists.extend(raw_terms)
        flagged_terms = [
            json.dumps(item, ensure_ascii=False, default=str) for item in term_lists
        ]
        term_findings = ProtectedTerminologyValidator().validate(
            run.language,
            source_text,
            draft_text,
            flagged_terms=flagged_terms,
        )
        blocking = [f for f in findings + list(term_findings) if f.blocking]
        async with self.database.transaction() as session:
            run_row = await session.get(LocalizationPipelineRun, run_id)
            if run_row is None:
                raise LookupError("run vanished")
            run_row.work_json = {
                **run_row.work_json,
                "final_gate": {
                    "words": words,
                    "minutes": round(minutes, 1),
                    "wpm": wpm,
                    "deterministic_findings": [
                        {"code": f.code, "message": f.message} for f in findings
                    ],
                    "terminology_findings": [
                        {"code": f.code, "message": f.message} for f in term_findings
                    ],
                },
            }
            await session.flush()
        if blocking:
            duration_codes = {"DURATION_TOO_SHORT", "DURATION_TOO_LONG"}
            final_duration_repairs = int(
                str(run.work_json.get("final_duration_repairs") or 0)
            )
            if (
                all(f.code in duration_codes for f in blocking)
                and draft_id is not None
                and final_duration_repairs < 1
            ):
                # The premium draft is semantically clean; its only
                # defect is spoken length. Exactly one bounded duration
                # repair, then the whole finalize path re-gates the
                # result — a repair chance, never a waiver.
                await self._final_duration_repair(run, draft_id, package_payload)
                async with self.database.transaction() as session:
                    run_row = await session.get(LocalizationPipelineRun, run_id)
                    if run_row is None:
                        raise LookupError("run vanished")
                    run_row.work_json = {
                        **run_row.work_json,
                        "final_duration_repairs": final_duration_repairs + 1,
                    }
                    await session.flush()
                return await self._set_stage(
                    run_id, LocalizationPipelineStage.FINAL_FIDELITY
                )
            return await self._reject_or_block(
                run_id,
                run,
                "deterministic gates failed: " + ", ".join(f.code for f in blocking),
            )
        await self._set_stage(run_id, LocalizationPipelineStage.DURATION_READY)
        return await self._set_stage(run_id, LocalizationPipelineStage.READY_FOR_VOICE)

    async def _reject_or_block(
        self,
        run_id: UUID,
        run: LocalizationPipelineRun,
        error: str,
    ) -> LocalizationPipelineRun:
        """Reject a failed premium candidate or block honestly (§21).

        When the draft being gated is the premium candidate and the
        pre-Astra best has not yet been evaluated at the final gate,
        restore the best and re-gate it — a worse premium edit may never
        overwrite a better candidate. When the best itself fails, the
        run blocks.
        """

        pre_astra = run.work_json.get("pre_astra_draft_id")
        rejected = bool(run.work_json.get("premium_rejected"))
        current = str(run.script_draft_id)
        if pre_astra and not rejected and str(pre_astra) != current:
            return await self._set_stage(
                run_id,
                LocalizationPipelineStage.FINAL_FIDELITY,
                script_draft_id=UUID(str(pre_astra)),
                work={
                    "premium_rejected": True,
                    "premium_rejected_reason": error,
                },
            )
        return await self._set_stage(
            run_id,
            LocalizationPipelineStage.BLOCKED,
            error=error,
        )

    async def _post_premium_repair(
        self,
        run: LocalizationPipelineRun,
        draft_id: UUID | None,
        package_payload: dict[str, object],
        blockers: list[ReviewFinding],
    ) -> None:
        """One bounded post-premium patch repair (§19/§23).

        Repairs only the sections the final gate flagged, on the premium
        draft itself — never a full regeneration. The repaired draft is
        persisted as a candidate; ``finalize`` re-gates it.
        """

        if draft_id is None:
            return
        async with self.database.transaction() as session:
            draft = await session.get(ScriptDraft, draft_id)
            if draft is None:
                return
            sections = restore_sections(
                (draft.provenance_json or {}).get("sections"), draft.text
            )
        budgets_raw = run.work_json.get("section_plan")
        budgets = budget_map(
            [
                SectionBudget.model_validate(b)
                for b in (budgets_raw if isinstance(budgets_raw, list) else [])
            ]
        )
        by_section: dict[str, list[ReviewFinding]] = {}
        global_findings: list[ReviewFinding] = []
        for f in blockers:
            sid = self._resolve_section(f, sections)
            if sid:
                by_section.setdefault(sid, []).append(f)
            else:
                global_findings.append(f)
        patches: list[PatchOp] = []
        for sid, group in by_section.items():
            idx = next(i for i, s in enumerate(sections) if s.section_id == sid)
            output = await self._section_patch_call(
                run,
                sections,
                group,
                package_payload,
                idx=idx,
                section_id=sid,
                budgets=budgets,
            )
            patches.extend(output.patches)
        if global_findings:
            output = await self._global_patch_call(
                run, sections, global_findings, package_payload, budgets=budgets
            )
            patches.extend(output.patches)
        result = apply_patches(sections, PatchSetOutput(patches=patches))
        if not result.applied:
            return
        new_draft = await self._persist_draft(
            run,
            join_sections(result.sections),
            kind="post_premium_repair",
            sections=result.sections,
            extra_provenance={
                "parent_draft_id": str(draft_id),
                "candidate": True,
                "patch": {
                    "applied": [{"section_id": a.section_id} for a in result.applied],
                    "rejected": [
                        {"section_id": r.section_id, "reason": r.reason}
                        for r in result.rejected
                    ],
                },
            },
        )
        await self._mark_addressed(
            run.id,
            blockers,
            new_draft.id,
            "post-premium patch repair applied",
        )

    async def _final_duration_repair(
        self,
        run: LocalizationPipelineRun,
        draft_id: UUID | None,
        package_payload: dict[str, object],
    ) -> None:
        """One bounded duration-only patch repair on the premium draft.

        Fires only when the deterministic gate's sole blocker is spoken
        length; ``finalize`` re-runs the complete gate path on the
        repaired draft (final fidelity + native quality + duration +
        terminology), so the repair can never bypass a semantic check.
        """

        if draft_id is None:
            return
        async with self.database.transaction() as session:
            draft = await session.get(ScriptDraft, draft_id)
            run_row = await session.get(LocalizationPipelineRun, run.id)
            if draft is None or run_row is None:
                return
            sections = restore_sections(
                (draft.provenance_json or {}).get("sections"), draft.text
            )
            budgets_raw = run_row.work_json.get("section_plan")
        budgets = budget_map(
            [
                SectionBudget.model_validate(b)
                for b in (budgets_raw if isinstance(budgets_raw, list) else [])
            ]
        )
        new_sections, applied = await self._length_repair(
            run, sections, budgets, package_payload
        )
        if not applied:
            return
        await self._persist_draft(
            run,
            join_sections(new_sections),
            kind="final_duration_repair",
            sections=new_sections,
            extra_provenance={"parent_draft_id": str(draft_id), "candidate": True},
        )


_KIND_TO_ROLE: dict[str, AgentRole] = {
    "coverage_draft": AgentRole.COVERAGE_TRANSLATION,
    "native_draft": AgentRole.NATIVE_RECONSTRUCTION,
    "targeted_patch": AgentRole.SEMANTIC_PATCH_REPAIR,
    "full_rewrite_candidate": AgentRole.PREMIUM_TARGETED_REVISION,
    "premium_candidate": AgentRole.TARGET_FINAL_EDITOR,
    "post_premium_repair": AgentRole.SEMANTIC_PATCH_REPAIR,
    "final_duration_repair": AgentRole.DURATION_ADJUSTMENT,
    # Legacy kinds kept so provenance replay on old drafts still resolves.
    "targeted_correction": AgentRole.TARGETED_LOCALIZATION_REPAIR,
    "premium_final": AgentRole.TARGET_FINAL_EDITOR,
}
