"""Real language realization from standalone Semantic Master exports."""

import json
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.ayin.domain import LanguageCode
from app.db.session import Database
from app.knowledge.llm.base import StructuredExtractionRequest
from app.knowledge.llm.codex import CodexCliProvider
from app.lecture.domain import PublicationLanguage
from app.lecture.models import LectureMasterVersion
from app.lecture.service import LectureMasterService
from app.localization.domain import (
    LocalizationStatus,
    PronunciationCriticality,
    PronunciationLexiconStatus,
    PronunciationStatus,
    SemanticValidationStatus,
)
from app.localization.models import (
    LocalizationProject,
    LocalizationStatement,
    LocalizationVersion,
    PronunciationLexiconEntry,
)
from app.localization.prompts import native_realization_instruction
from app.localization.pronunciation import prepare_pronunciation
from app.localization.validators import LocalizationQualityGate


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
        self.provider = CodexCliProvider()

    async def create(
        self,
        master_id: UUID,
        language: PublicationLanguage,
        *,
        created_by: str = "operator",
    ) -> UUID:
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
        prompt = (
            native_realization_instruction(language)
            + "\n\nReturn exactly one native statement for every claim ID, "
            "with no omissions. "
            "Preserve the claim IDs as metadata, never as visible prose."
        )
        result = cast(
            _RealizationBatch,
            await self.provider.extract(
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
