"""Shared LocalizationSemanticPackage (§27–28).

Built once per owner-approved Persian script draft, shared by every
target language. The reasoning model derives the claim ledger and
narrative semantics; deterministic validation then proves the package
cannot drift from the locked master: every claim ID must exist upstream
and every epistemic status must match exactly.
"""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.briefs.models import ContentBrief
from app.content_engine.domain import DraftStatus
from app.content_engine.models import ScriptDraft
from app.content_engine.service import GateBlockedError
from app.db.session import Database
from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.knowledge.llm.context import assert_no_secrets, guard_payload
from app.knowledge.llm.factory import resolve_llm_provider
from app.knowledge.llm.roles import AgentRole
from app.knowledge.llm.telemetry import DatabaseLLMRecorder
from app.lecture.service import LectureMasterService
from app.localization.domain import LocalizationPipelineStage
from app.localization.gate import (
    approved_persian_draft,
    package_is_current,
    require_approved_persian_draft,
)
from app.localization.models import (
    LocalizationPipelineRun,
    LocalizationSemanticPackage,
)

PACKAGE_PROMPT_VERSION = "semantic_package_v1"


class PackageClaimItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: UUID
    semantic_proposition: str = Field(min_length=1)
    epistemic_status: str = Field(min_length=1)
    qualifiers: list[str] = Field(default_factory=list)
    prohibited_overstatements: list[str] = Field(default_factory=list)
    argument_role: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class SemanticPackageOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thesis: str = Field(min_length=1)
    conclusion: str = Field(min_length=1)
    claim_ledger: list[PackageClaimItem]
    causal_constraints: list[str] = Field(default_factory=list)
    counterarguments: list[str] = Field(default_factory=list)
    story_facts: list[str] = Field(default_factory=list)
    emotional_beats: list[str] = Field(default_factory=list)
    protected_terms: list[str] = Field(default_factory=list)
    localization_notes: list[str] = Field(default_factory=list)
    unresolved_ambiguities: list[str] = Field(default_factory=list)


_PACKAGE_INSTRUCTIONS = """
Build the shared localization semantic package for one approved Persian
script. This package is the single semantic contract for German, English,
and Arabic native productions.

Return a claim ledger: one entry per upstream claim ID, with the claim's
exact epistemic status, its required qualifiers, prohibited
overstatements, argument role, and the evidence references that ground
it. Then record the causal constraints, counterarguments, story facts,
emotional beats, protected Ayin terms, localization notes, and any
unresolved ambiguities the target writers must preserve.

Never invent claims, weaken uncertainty, promote speculation to fact, or
add evidence/books not present in the supplied material.
""".strip()


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()


class SemanticPackageService:
    """Create and keep current the shared localization semantic package."""

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
        self.master_service = LectureMasterService(database)

    async def create_for_draft(
        self, draft_id: UUID, *, created_by: str = "pipeline"
    ) -> LocalizationSemanticPackage:
        """Derive and persist the package for one APPROVED Persian draft."""

        async with self.database.transaction() as session:
            draft = await session.get(ScriptDraft, draft_id)
            if draft is None:
                raise LookupError(f"Unknown script draft {draft_id}")
            if draft.language != "fa" or draft.lineage != "primary":
                raise GateBlockedError(
                    "Semantic packages are built only from the primary "
                    "Persian script draft"
                )
            if draft.status is not DraftStatus.APPROVED:
                raise GateBlockedError(
                    "LOCALIZATION_GATE — the Persian draft is not owner-approved"
                )
            latest = await approved_persian_draft(session, draft.content_brief_id)
            if latest is None or latest.id != draft.id:
                raise GateBlockedError(
                    "STALE_SOURCE — a newer approved Persian draft exists; "
                    "build the package from the current master"
                )
            draft_text = draft.text
            draft_hash = draft.content_hash
            brief_id = draft.content_brief_id
            master_id = draft.lecture_master_version_id
            book_refs = draft.provenance_json.get("book_references", [])
            approved_by = str(draft.provenance_json.get("approved_by", ""))

        export = (
            await self.master_service.export(master_id)
            if master_id is not None
            else None
        )
        async with self.database.transaction() as session:
            brief = await session.get(ContentBrief, brief_id)
            question = brief.question if brief is not None else ""
            thesis = brief.thesis if brief is not None else ""
        payload_input = {
            "source_script": draft_text,
            "master_export": (
                export.model_dump(mode="json") if export is not None else {}
            ),
            "book_references": book_refs,
            "language": "fa",
        }
        guard_payload(AgentRole.SEMANTIC_PACKAGE, payload_input)
        input_text = json.dumps(payload_input, ensure_ascii=False, sort_keys=True)
        assert_no_secrets(input_text)
        provider = self.provider or resolve_llm_provider(
            role=AgentRole.SEMANTIC_PACKAGE,
            recorder=DatabaseLLMRecorder(
                self.database,
                run_scope="semantic_package",
                content_brief_id=brief_id,
            ),
        )
        result = await provider.extract(
            StructuredExtractionRequest(
                task="localization_semantic_package",
                prompt_version=PACKAGE_PROMPT_VERSION,
                model=self.model,
                instructions=_PACKAGE_INSTRUCTIONS,
                input_text=input_text,
                output_model=SemanticPackageOutput,
                timeout_seconds=300,
            )
        )
        output = SemanticPackageOutput.model_validate(result.model_dump())
        self._validate_against_master(output, export)
        package_payload: dict[str, object] = {
            "thesis": output.thesis,
            "brief_question": question,
            "brief_thesis": thesis,
            "conclusion": output.conclusion,
            "claim_ledger": [
                item.model_dump(mode="json") for item in output.claim_ledger
            ],
            "causal_constraints": output.causal_constraints,
            "counterarguments": output.counterarguments,
            "story_facts": output.story_facts,
            "emotional_beats": output.emotional_beats,
            "protected_terms": output.protected_terms,
            "localization_notes": output.localization_notes,
            "unresolved_ambiguities": output.unresolved_ambiguities,
            "book_references": book_refs,
            "terminology_references": (
                export.terminology_references if export is not None else []
            ),
            "citations": export.citations if export is not None else [],
            "sections": export.sections if export is not None else [],
            "source": {
                "script_draft_id": str(draft_id),
                "source_draft_hash": draft_hash,
                "lecture_master_version_id": (
                    str(master_id) if master_id is not None else None
                ),
                "approved_by": approved_by,
            },
        }
        async with self.database.transaction() as session:
            version = (
                await session.scalar(
                    select(
                        func.coalesce(
                            func.max(LocalizationSemanticPackage.version_number), 0
                        )
                    ).where(LocalizationSemanticPackage.script_draft_id == draft_id)
                )
                or 0
            ) + 1
            package = LocalizationSemanticPackage(
                script_draft_id=draft_id,
                content_brief_id=brief_id,
                lecture_master_version_id=master_id,
                version_number=version,
                source_draft_hash=draft_hash,
                payload=package_payload,
                content_hash=_hash(package_payload),
                provenance_json={
                    "model": self.model,
                    "prompt_version": PACKAGE_PROMPT_VERSION,
                    "agent_role": AgentRole.SEMANTIC_PACKAGE.value,
                },
                created_by=created_by,
            )
            session.add(package)
            await session.flush()
            await session.refresh(package)
            return package

    @staticmethod
    def _validate_against_master(
        output: SemanticPackageOutput, export: object | None
    ) -> None:
        """The package may organize claims but never drift from them."""

        if export is None:
            return
        master_claims = {
            str(claim.get("id")): claim
            for claim in export.claims  # type: ignore[attr-defined]
        }
        seen: set[str] = set()
        for item in output.claim_ledger:
            claim_id = str(item.claim_id)
            if claim_id not in master_claims:
                raise ValueError(
                    f"semantic package references unknown claim {claim_id}"
                )
            expected = str(master_claims[claim_id].get("epistemic_status", ""))
            if expected and item.epistemic_status != expected:
                raise ValueError(
                    f"semantic package changed epistemic status of claim "
                    f"{claim_id}: {item.epistemic_status} != {expected}"
                )
            seen.add(claim_id)
        missing = set(master_claims) - seen
        if missing:
            raise ValueError(f"semantic package omitted {len(missing)} master claims")

    async def staleness_sweep(self, package_id: UUID) -> int:
        """Mark dependent runs STALE_SOURCE when the Persian text changed."""

        async with self.database.transaction() as session:
            package = await session.get(LocalizationSemanticPackage, package_id)
            if package is None:
                raise LookupError(f"Unknown semantic package {package_id}")
            current = await package_is_current(session, package)
            if current:
                return 0
            runs = list(
                await session.scalars(
                    select(LocalizationPipelineRun).where(
                        LocalizationPipelineRun.semantic_package_id == package_id,
                        LocalizationPipelineRun.stage.notin_(
                            [
                                LocalizationPipelineStage.STALE_SOURCE,
                                LocalizationPipelineStage.FAILED,
                            ]
                        ),
                    )
                )
            )
            for run in runs:
                run.stage = LocalizationPipelineStage.STALE_SOURCE
                run.error = (
                    "Source Persian draft changed after approval — the "
                    "semantic package no longer matches the approved text."
                )
            return len(runs)

    async def approved_draft_for_brief(self, brief_id: UUID) -> ScriptDraft | None:
        async with self.database.transaction() as session:
            return await approved_persian_draft(session, brief_id)

    async def require_gate(self, brief_id: UUID) -> ScriptDraft:
        return await require_approved_persian_draft(self.database, brief_id)
