"""Real language realization from standalone Semantic Master exports."""

import json
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.ayin.domain import LanguageCode
from app.db.session import Database
from app.knowledge.llm.base import LLMProvider, StructuredExtractionRequest
from app.knowledge.llm.factory import resolve_llm_provider
from app.knowledge.llm.roles import AgentRole
from app.lecture.domain import PublicationLanguage
from app.lecture.models import LectureMasterVersion, LectureProject
from app.lecture.service import LectureMasterService
from app.localization.domain import (
    LocalizationStatus,
    PronunciationCriticality,
    PronunciationLexiconStatus,
    PronunciationStatus,
    SemanticValidationStatus,
)
from app.localization.gate import require_approved_persian_draft
from app.localization.models import (
    LocalizationProject,
    LocalizationStatement,
    LocalizationVersion,
    PronunciationLexiconEntry,
)
from app.localization.prompts import (
    duration_adjustment_instruction,
    native_realization_instruction,
)
from app.localization.pronunciation import prepare_pronunciation
from app.localization.validators import LocalizationQualityGate
from app.ops.settings.service import StudioSettingsService, speech_wpm


class _Realization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: UUID
    display_text: str = Field(min_length=1)


class _RealizationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statements: list[_Realization]


class LocalizationService:
    """Generate and validate one independent localization from one master."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.master_service = LectureMasterService(database)
        # Resolved lazily per call so tests/operators can inject a stub and
        # construction never hides an LLM side effect.
        self.provider: LLMProvider | None = None

    async def create(
        self,
        master_id: UUID,
        language: PublicationLanguage,
        *,
        created_by: str = "operator",
    ) -> UUID:
        async with self.database.transaction() as session:
            master = await session.get(LectureMasterVersion, master_id)
            if master is None:
                raise ValueError("lecture master not found")
            brief_id = master.content_brief_id
        if brief_id is not None:
            await require_approved_persian_draft(self.database, brief_id)
        else:
            raise ValueError(
                "localization requires a content-brief master with an "
                "owner-approved Persian script"
            )
        export = await self.master_service.export(master_id)
        if export.master.get("status") != "READY":
            raise ValueError("localization requires a READY Semantic Master")
        claims = [
            {
                "id": claim.get("id"),
                "semantic_proposition": claim.get("semantic_proposition"),
                "plain_meaning": claim.get("plain_meaning"),
                "epistemic_status": claim.get("epistemic_status"),
                "certainty": claim.get("certainty"),
                "required_qualifiers": claim.get("required_qualifiers", []),
                "prohibited_overstatements": claim.get("prohibited_overstatements", []),
            }
            for claim in export.claims
        ]
        effective = await StudioSettingsService(self.database).effective()
        provider = self.provider or resolve_llm_provider(
            role=AgentRole.NATIVE_RECONSTRUCTION, effective=effective
        )
        wpm = speech_wpm(effective, language.value)
        target_seconds = 0
        for section in export.sections:
            raw_seconds = section.get("duration_seconds")
            if isinstance(raw_seconds, (int, float)):
                target_seconds += int(raw_seconds)
        target_words = int(target_seconds / 60 * wpm) if target_seconds else 0
        prompt = (
            native_realization_instruction(language)
            + "\n\nReturn exactly one native statement for every claim ID, "
            "with no omissions. "
            "Preserve the claim IDs as metadata, never as visible prose."
        )
        if target_words:
            prompt += (
                f"\nThe finished spoken piece targets about "
                f"{target_seconds // 60} minutes — roughly {target_words} "
                f"{language.value} words in total. Pace every statement "
                "toward that shared budget; do not write each one at "
                "maximal length."
            )
        result = cast(
            _RealizationBatch,
            await provider.extract(
                StructuredExtractionRequest(
                    task="semantic lecture localization",
                    prompt_version="phase-9.1-real-v1",
                    model="configured-default",
                    instructions=prompt,
                    input_text=json.dumps(
                        {
                            "human_question": export.master.get(
                                "central_human_question"
                            ),
                            "sections": export.sections,
                            "claims": claims,
                            "terms": export.terminology_references,
                        },
                        ensure_ascii=False,
                    ),
                    output_model=_RealizationBatch,
                    timeout_seconds=300,
                ),
            ),
        )
        by_id = {item.claim_id: item.display_text for item in result.statements}
        master_ids = {UUID(str(item["id"])) for item in claims}
        if set(by_id) != master_ids:
            raise ValueError("localizer did not return exactly the master claim set")

        async with self.database.transaction() as session:
            master = await session.get(LectureMasterVersion, master_id)
            if master is None:
                raise ValueError("lecture master not found")
            project = LocalizationProject(
                lecture_master_version_id=master_id,
                language=language,
                status=LocalizationStatus.DRAFT,
                created_by=created_by,
            )
            session.add(project)
            await session.flush()
            version = LocalizationVersion(
                localization_project_id=project.id,
                version_number=1,
                display_language=LanguageCode(language.value),
                status=LocalizationStatus.DRAFT,
                semantic_validation_status=SemanticValidationStatus.NOT_VALIDATED,
                pronunciation_status=PronunciationStatus.NOT_PREPARED,
            )
            session.add(version)
            await session.flush()
            lexicon = self._lexicon(export.terminology_references, language)
            for entry in lexicon:
                session.add(
                    PronunciationLexiconEntry(
                        term_id=None,
                        language=LanguageCode(language.value),
                        written_form=entry["written_form"],
                        preferred_pronunciation=entry["preferred_pronunciation"],
                        criticality=PronunciationCriticality(str(entry["criticality"])),
                        status=PronunciationLexiconStatus.APPROVED,
                        version=1,
                        reviewer_notes=(
                            "Phase 9.1 pronunciation preparation; acoustic "
                            "validation is external/future."
                        ),
                    )
                )
            for sequence, claim in enumerate(export.claims, start=1):
                claim_id = UUID(str(claim["id"]))
                display = by_id[claim_id]
                prepared = prepare_pronunciation(
                    language,
                    display,
                    lexicon,
                    lexicon_version=1,
                )
                session.add(
                    LocalizationStatement(
                        localization_version_id=version.id,
                        lecture_claim_id=claim_id,
                        sequence=sequence,
                        display_text=prepared.display_text,
                        voice_text=prepared.voice_text,
                        claim_metadata={
                            "master_claim_id": str(claim_id),
                            "epistemic_status": claim["epistemic_status"],
                            "certainty": claim["certainty"],
                            "citation_ids": [
                                str(citation["id"])
                                for citation in export.citations
                                if citation.get("claim_id") == claim_id
                            ],
                            "dialogue_review_status": self._dialogue_status(
                                claim_id, export.dialogue_relations, export.evidence
                            ),
                        },
                    )
                )
            await session.flush()
            statements = [
                {
                    "master_claim_id": str(claim["id"]),
                    "epistemic_status": claim["epistemic_status"],
                    "certainty": claim["certainty"],
                    "display_text": by_id[UUID(str(claim["id"]))],
                    "voice_text": by_id[UUID(str(claim["id"]))],
                }
                for claim in export.claims
            ]
            findings = LocalizationQualityGate().validate(
                language, claims, statements, lexicon
            )
            if findings:
                version.status = LocalizationStatus.FAILED
                version.semantic_validation_status = SemanticValidationStatus.FAILED
                version.pronunciation_status = PronunciationStatus.FAILED
                project.status = LocalizationStatus.FAILED
            else:
                version.status = LocalizationStatus.READY_FOR_VOICE
                version.semantic_validation_status = SemanticValidationStatus.PASSED
                version.pronunciation_status = PronunciationStatus.VALIDATED
                project.status = LocalizationStatus.READY_FOR_VOICE
            await session.flush()
            return version.id

    async def adjust_duration(
        self, version_id: UUID, *, created_by: str = "operator"
    ) -> UUID:
        """Correct a version's spoken length toward the project target.

        If the version is already within ±10 % of target, returns it
        unchanged. Otherwise a bounded duration pass rewrites the
        statement set in place (condense or elaborate — never drop or
        add claims), persists it as the next version, and re-runs the
        same quality gate.
        """

        async with self.database.transaction() as session:
            version = await session.get(LocalizationVersion, version_id)
            if version is None:
                raise LookupError(f"Unknown localization version {version_id}")
            project = await session.get(
                LocalizationProject, version.localization_project_id
            )
            if project is None:
                raise LookupError("localization project not found")
            master = await session.get(
                LectureMasterVersion, project.lecture_master_version_id
            )
            if master is None:
                raise LookupError("lecture master not found")
            statements = list(
                (
                    await session.scalars(
                        select(LocalizationStatement)
                        .where(
                            LocalizationStatement.localization_version_id == version.id
                        )
                        .order_by(LocalizationStatement.sequence)
                    )
                ).all()
            )
            language = project.language
            master_id = master.id
            lecture_project_id = master.lecture_project_id
            project_id = project.id
            next_number = version.version_number + 1
            statement_rows = [
                (item.lecture_claim_id, item.display_text) for item in statements
            ]

        async with self.database.transaction() as session:
            lecture_project = await session.get(LectureProject, lecture_project_id)
            target_seconds = (
                lecture_project.target_duration_seconds
                if lecture_project is not None
                else None
            )
        effective = await StudioSettingsService(self.database).effective()
        provider = self.provider or resolve_llm_provider(
            role=AgentRole.DURATION_ADJUSTMENT, effective=effective
        )
        wpm = speech_wpm(effective, language.value)
        if not target_seconds:
            target_seconds = int(
                float(effective["target_duration_default_minutes"]) * 60
            )
        target_words = target_seconds / 60 * wpm
        current_words = sum(len(text.split()) for _claim_id, text in statement_rows)
        if (
            target_words > 0
            and abs(current_words - target_words) / target_words <= 0.10
        ):
            return version_id

        direction = "condense" if current_words > target_words else "expand"
        # The duration pass must stay anchored to the approved master —
        # expanding/condensing may only reword existing claim meaning,
        # never invent content the source does not contain.
        export = await self.master_service.export(master_id)
        source_claims = [
            {
                "id": claim.get("id"),
                "semantic_proposition": claim.get("semantic_proposition"),
                "plain_meaning": claim.get("plain_meaning"),
                "epistemic_status": claim.get("epistemic_status"),
                "required_qualifiers": claim.get("required_qualifiers", []),
                "prohibited_overstatements": claim.get("prohibited_overstatements", []),
            }
            for claim in export.claims
        ]
        result = cast(
            _RealizationBatch,
            await provider.extract(
                StructuredExtractionRequest(
                    task="localization duration adjustment",
                    prompt_version="phase-7-duration-v2",
                    model="configured-default",
                    instructions=duration_adjustment_instruction(
                        language, direction, int(target_words)
                    ),
                    input_text=json.dumps(
                        {
                            "source_claims": source_claims,
                            "statements": [
                                {
                                    "claim_id": str(claim_id),
                                    "display_text": text,
                                }
                                for claim_id, text in statement_rows
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    output_model=_RealizationBatch,
                    timeout_seconds=300,
                ),
            ),
        )
        by_id = {item.claim_id: item.display_text for item in result.statements}
        expected = {claim_id for claim_id, _text in statement_rows}
        if set(by_id) != expected:
            raise ValueError(
                "duration adjustment did not return exactly the same claim set"
            )
        export = await self.master_service.export(master_id)
        claims = list(export.claims)

        async with self.database.transaction() as session:
            project = await session.get(LocalizationProject, project_id)
            if project is None:
                raise LookupError("localization project not found")
            new_version = LocalizationVersion(
                localization_project_id=project_id,
                version_number=next_number,
                display_language=LanguageCode(language.value),
                status=LocalizationStatus.DRAFT,
                semantic_validation_status=SemanticValidationStatus.NOT_VALIDATED,
                pronunciation_status=PronunciationStatus.NOT_PREPARED,
            )
            session.add(new_version)
            await session.flush()
            lexicon = self._lexicon(export.terminology_references, language)
            for sequence, (claim_id, _old) in enumerate(statement_rows, start=1):
                display = by_id[claim_id]
                prepared = prepare_pronunciation(
                    language, display, lexicon, lexicon_version=1
                )
                claim = next(c for c in claims if UUID(str(c["id"])) == claim_id)
                session.add(
                    LocalizationStatement(
                        localization_version_id=new_version.id,
                        lecture_claim_id=claim_id,
                        sequence=sequence,
                        display_text=prepared.display_text,
                        voice_text=prepared.voice_text,
                        claim_metadata={
                            "master_claim_id": str(claim_id),
                            "epistemic_status": claim["epistemic_status"],
                            "certainty": claim["certainty"],
                            "duration_adjusted": True,
                            "adjustment_direction": direction,
                        },
                    )
                )
            await session.flush()
            gate_statements = [
                {
                    "master_claim_id": str(claim_id),
                    "epistemic_status": next(
                        c for c in claims if UUID(str(c["id"])) == claim_id
                    )["epistemic_status"],
                    "certainty": next(
                        c for c in claims if UUID(str(c["id"])) == claim_id
                    )["certainty"],
                    "display_text": by_id[claim_id],
                    "voice_text": by_id[claim_id],
                }
                for claim_id, _old in statement_rows
            ]
            findings = LocalizationQualityGate().validate(
                language, claims, gate_statements, lexicon
            )
            if findings:
                new_version.status = LocalizationStatus.FAILED
                new_version.semantic_validation_status = SemanticValidationStatus.FAILED
                new_version.pronunciation_status = PronunciationStatus.FAILED
                project.status = LocalizationStatus.FAILED
            else:
                new_version.status = LocalizationStatus.READY_FOR_VOICE
                new_version.semantic_validation_status = SemanticValidationStatus.PASSED
                new_version.pronunciation_status = PronunciationStatus.VALIDATED
                project.status = LocalizationStatus.READY_FOR_VOICE
            await session.flush()
            return new_version.id

    @staticmethod
    def _lexicon(
        terms: list[dict[str, object]], language: PublicationLanguage
    ) -> list[dict[str, object]]:
        critical_forms = {"emtedad", "bon", "jan", "majal", "tahigah", "between"}
        entries: list[dict[str, object]] = []
        for term in terms:
            form = str(term.get("source_form", "")).strip()
            if not form:
                continue
            entries.append(
                {
                    "written_form": form,
                    "preferred_pronunciation": form,
                    "criticality": (
                        PronunciationCriticality.CRITICAL.value
                        if form.lower() in critical_forms
                        else PronunciationCriticality.IMPORTANT.value
                    ),
                    "status": PronunciationLexiconStatus.APPROVED.value,
                    "language": language.value,
                }
            )
        return entries

    @staticmethod
    def _dialogue_status(
        claim_id: UUID,
        relations: list[dict[str, object]],
        evidence: list[dict[str, object]],
    ) -> str | None:
        relation_ids = {
            str(item.get("evidence_item_id"))
            for item in evidence
            if item.get("evidence_kind") == "DIALOGUE_RELATION"
            and str(item.get("claim_id")) == str(claim_id)
        }
        for relation in relations:
            if str(relation.get("relation_id")) in relation_ids:
                return str(relation.get("review_status", "PROPOSED"))
        return None
