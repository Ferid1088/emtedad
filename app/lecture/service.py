"""Writer-isolated Phase 8 Semantic Lecture Master orchestration."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ayin.models import (
    AyinConcept,
    AyinConceptVersion,
    AyinDistinctionVersion,
    AyinOpenQuestionVersion,
    AyinPrincipleVersion,
    CanonPassage,
)
from app.db.session import Database
from app.lecture.domain import (
    SUPPORTED_PUBLICATION_LANGUAGES,
    CitationKind,
    ClaimEpistemicStatus,
    ClaimOrigin,
    DiscourseType,
    EvidenceBindingRole,
    EvidenceKind,
    LectureProjectStatus,
    MasterStatus,
    SectionRole,
)
from app.lecture.models import (
    LectureCitation,
    LectureClaim,
    LectureClaimEvidence,
    LectureMasterVersion,
    LectureProject,
    LectureRitualLink,
    LectureSection,
    MasterExport,
    ValidationFinding,
    ValidationRun,
)
from app.lecture.schemas import (
    LectureBuildResult,
    LectureMasterRead,
    LectureProjectCreate,
    LectureProjectRead,
    LectureValidationRead,
    SemanticLectureMasterExport,
)
from app.lecture.validator import LectureFinding, LectureValidator
from app.research.domain import PackageStatus
from app.research.models import (
    ResearchPackage,
    ResearchPackageAyinConcept,
    ResearchPackageAyinDistinction,
    ResearchPackageAyinOpenQuestion,
    ResearchPackageAyinPassage,
    ResearchPackageAyinPrinciple,
    ResearchPackageRitualVersion,
)


def _hash(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


class LectureMasterService:
    """Build and validate semantic structure using only a frozen package."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.validator = LectureValidator()

    async def create_project(self, request: LectureProjectCreate) -> LectureProjectRead:
        async with self.database.transaction() as session:
            package = await session.get(ResearchPackage, request.research_package_id)
            if package is None or package.status is not PackageStatus.FROZEN:
                raise ValueError("lecture projects require a frozen ResearchPackage")
            project = LectureProject(**request.model_dump())
            session.add(project)
            await session.flush()
            return LectureProjectRead.model_validate(project)

    async def projects(self) -> list[LectureProjectRead]:
        async with self.database.transaction() as session:
            rows = await session.scalars(
                select(LectureProject).order_by(LectureProject.created_at)
            )
            return [LectureProjectRead.model_validate(row) for row in rows]

    async def architect(
        self, project_id: UUID, created_by: str = "operator"
    ) -> LectureMasterRead:
        async with self.database.transaction() as session:
            project = await session.get(LectureProject, project_id)
            if project is None:
                raise ValueError("lecture project not found")
            package = await session.get(ResearchPackage, project.research_package_id)
            if package is None or package.status is not PackageStatus.FROZEN:
                raise ValueError(
                    "lecture architecture requires a frozen ResearchPackage"
                )
            version = int(
                await session.scalar(
                    select(
                        func.coalesce(func.max(LectureMasterVersion.version_number), 0)
                        + 1
                    ).where(LectureMasterVersion.lecture_project_id == project.id)
                )
                or 1
            )
            master = LectureMasterVersion(
                lecture_project_id=project.id,
                version_number=version,
                research_package_id=package.id,
                research_package_version=package.package_version,
                research_package_content_hash=package.content_hash,
                canon_version_id=package.canon_version_id,
                package_authority=self._authority(package),
                central_human_question=self._human_question(package),
                ending_mode="OPEN",
                architecture=(
                    {
                        "writer_isolation": (
                            "PINNED_LESSON_PACKAGE_PLUS_FROZEN_EXTERNAL_RESEARCH"
                        ),
                        "lesson_id": package.lesson_id,
                        "lesson_canon_hash": package.lesson_canon_hash,
                        "full_ayin_book_rag": False,
                        "published_archive_role": "POST_DRAFT_REVIEW_ONLY",
                    }
                    if package.lesson_id is not None
                    else {"writer_isolation": "FROZEN_RESEARCH_PACKAGE_ONLY"}
                ),
                prohibited_conflations=self._prohibited(package),
                uncertainty_constraints=[
                    "Never present PROPOSED dialogue relations as approved",
                    "Never present optional metaphysics as scientific fact",
                ],
                status=MasterStatus.ARCHITECTED,
                input_hash=_hash(
                    [package.id, package.content_hash, project.lecture_type.value]
                ),
                created_by=created_by,
            )
            session.add(master)
            await session.flush()
            sections = await self._sections(session, master, project, package)
            await self._claims(session, master, sections, package)
            await self._ritual_links(session, master, package)
            project.status = LectureProjectStatus.ARCHITECTED
            await session.flush()
            return LectureMasterRead.model_validate(master)

    async def validate(self, master_id: UUID) -> LectureBuildResult:
        async with self.database.transaction() as session:
            master = await session.get(LectureMasterVersion, master_id)
            if master is None:
                raise ValueError("lecture master not found")
            payload = await self._payload(session, master)
            findings = self.validator.validate(payload)
            run = ValidationRun(
                lecture_master_version_id=master.id,
                valid=not any(item.blocking for item in findings),
            )
            session.add(run)
            await session.flush()
            for finding in findings:
                session.add(
                    ValidationFinding(
                        validation_run_id=run.id,
                        dimension=finding.dimension,
                        code=finding.code,
                        severity=finding.severity,
                        message=finding.message,
                        blocking=finding.blocking,
                    )
                )
            master.status = MasterStatus.READY if not findings else MasterStatus.FAILED
            await session.flush()
            return LectureBuildResult(
                master=LectureMasterRead.model_validate(master),
                validation=self._validation_read(findings),
            )

    async def freeze(self, master_id: UUID) -> LectureMasterRead:
        async with self.database.transaction() as session:
            master = await session.get(LectureMasterVersion, master_id)
            if master is None:
                raise ValueError("lecture master not found")
            payload = await self._payload(session, master)
            findings = self.validator.validate(payload)
            if findings:
                raise ValueError("lecture master validation failed")
            master.status = MasterStatus.READY
            master.frozen_at = datetime.now(UTC)
            await session.flush()
            return LectureMasterRead.model_validate(master)

    async def export(self, master_id: UUID) -> SemanticLectureMasterExport:
        async with self.database.transaction() as session:
            master = await session.get(LectureMasterVersion, master_id)
            if master is None:
                raise ValueError("lecture master not found")
            payload = await self._payload(session, master)
            findings = self.validator.validate(payload)
            validation = self._validation_read(findings)
            result = SemanticLectureMasterExport(
                export_version="1",
                supported_languages=list(SUPPORTED_PUBLICATION_LANGUAGES),
                master=payload["master"],
                sections=payload["sections"],
                claims=payload["claims"],
                evidence=payload["evidence"],
                citations=payload["citations"],
                ritual_links=payload["ritual_links"],
                dialogue_relations=payload["dialogue_relations"],
                terminology_references=self._terminology_references(
                    payload["sections"]
                ),
                validation=validation,
            )
            content_hash = _hash(result.model_dump(mode="json"))
            session.add(
                MasterExport(
                    lecture_master_version_id=master.id,
                    payload=result.model_dump(mode="json"),
                    content_hash=content_hash,
                )
            )
            return result

    async def master(self, master_id: UUID) -> LectureMasterRead:
        async with self.database.transaction() as session:
            master = await session.get(LectureMasterVersion, master_id)
            if master is None:
                raise ValueError("lecture master not found")
            return LectureMasterRead.model_validate(master)

    async def _sections(
        self,
        session: AsyncSession,
        master: LectureMasterVersion,
        project: LectureProject,
        package: ResearchPackage,
    ) -> list[LectureSection]:
        roles = [
            SectionRole.HUMAN_ENTRY,
            SectionRole.AYIN_FRAME,
            SectionRole.EXTERNAL_DIALOGUE,
            SectionRole.COUNTERARGUMENT,
            SectionRole.LIFE_RETURN,
        ]
        if project.lecture_type.value == "RITUAL_COMPANION":
            roles.insert(-1, SectionRole.RITUAL_BRIDGE)
        sections: list[LectureSection] = []
        terminology = await self._terminology_for_package(session, package.id)
        for ordinal, role in enumerate(roles, start=1):
            section = LectureSection(
                lecture_master_version_id=master.id,
                ordinal=ordinal,
                role=role,
                purpose=self._section_purpose(role, package),
                rhetorical_function=role.value.lower().replace("_", " "),
                duration_seconds=(
                    project.target_duration_seconds // len(roles)
                    if project.target_duration_seconds
                    else None
                ),
                required_terminology=terminology,
            )
            session.add(section)
            sections.append(section)
        await session.flush()
        return sections

    async def _claims(
        self,
        session: AsyncSession,
        master: LectureMasterVersion,
        sections: list[LectureSection],
        package: ResearchPackage,
    ) -> None:
        snapshot: Any = package.retrieval_snapshot
        package_items = self._snapshot_items(snapshot)
        ayin_ids = await self._ayin_ids(session, package.id)
        sequence = 1
        for kind, item_id in ayin_ids:
            semantic = await self._ayin_semantic(session, kind, item_id, package_items)
            claim = LectureClaim(
                lecture_master_version_id=master.id,
                section_id=sections[1].id,
                stable_key=f"ayin_{kind.lower()}_{sequence}",
                sequence=sequence,
                claim_intent=semantic["semantic_proposition"],
                semantic_proposition=semantic["semantic_proposition"],
                plain_meaning=semantic["plain_meaning"],
                required_concepts=semantic["required_concepts"],
                required_qualifiers=["Ayin Working material; not Canon"],
                prohibited_overstatements=[
                    "Do not present external evidence as proof of this Ayin statement"
                ],
                source_support_summary=semantic["source_support_summary"],
                source_evidence=semantic["source_evidence"],
                claim_origin=ClaimOrigin.AYIN,
                discourse_type=DiscourseType.CONCEPTUAL,
                epistemic_status=ClaimEpistemicStatus.AYIN_DEFINITION,
                formulation_constraints=[
                    "Preserve exact Ayin distinctions and authority state"
                ],
            )
            session.add(claim)
            await session.flush()
            session.add(
                LectureClaimEvidence(
                    claim_id=claim.id,
                    evidence_kind=kind,
                    evidence_item_id=str(item_id),
                    package_id=package.id,
                    binding_role=EvidenceBindingRole.PRIMARY,
                    provenance={"package_id": str(package.id)},
                )
            )
            session.add(
                LectureCitation(
                    lecture_master_version_id=master.id,
                    claim_id=claim.id,
                    kind=CitationKind.AYIN,
                    package_id=package.id,
                    citation_data=semantic["citation"],
                )
            )
            sequence += 1
        seen: set[str] = set()
        for query in snapshot.get("queries", []):
            if not isinstance(query, dict):
                continue
            qkind = str(query.get("kind"))
            for item in query.get("results", []):
                if not isinstance(item, dict):
                    continue
                chunk_id = str(item.get("chunk_id"))
                if chunk_id in seen:
                    continue
                seen.add(chunk_id)
                counter = qkind == "COUNTEREVIDENCE"
                status = (
                    ClaimEpistemicStatus.COUNTEREVIDENCE
                    if counter
                    else ClaimEpistemicStatus.EXTERNAL_EMPIRICAL_CLAIM
                )
                text = str(item.get("text", "")).strip()
                proposition = (
                    "The external source provides a counterpoint relevant to the "
                    "question: "
                    if counter
                    else "The external source provides evidence relevant to the "
                    "question: "
                ) + text
                claim = LectureClaim(
                    lecture_master_version_id=master.id,
                    section_id=sections[3].id if counter else sections[2].id,
                    stable_key=f"external_{sequence}",
                    sequence=sequence,
                    claim_intent=proposition,
                    semantic_proposition=proposition,
                    plain_meaning=(
                        "This is a source-attributed counterpoint, not an Ayin "
                        "conclusion."
                        if counter
                        else "This is source-attributed external evidence, not "
                        "Ayin's own statement."
                    ),
                    required_qualifiers=[
                        "Preserve source attribution",
                        "Do not strengthen the source's certainty",
                    ],
                    prohibited_overstatements=["Do not say research proves Ayin"],
                    source_support_summary=text,
                    source_evidence=[
                        {
                            "text": text,
                            "chunk_id": chunk_id,
                            "provenance": item.get("provenance", {}),
                        }
                    ],
                    claim_origin=ClaimOrigin.EXTERNAL,
                    epistemic_status=status,
                    discourse_type=DiscourseType.DESCRIPTIVE
                    if not counter
                    else DiscourseType.CONCEPTUAL,
                )
                session.add(claim)
                await session.flush()
                provenance = item.get("provenance", {})
                session.add(
                    LectureClaimEvidence(
                        claim_id=claim.id,
                        evidence_kind=EvidenceKind.EXTERNAL_CHUNK,
                        evidence_item_id=chunk_id,
                        package_id=package.id,
                        binding_role=EvidenceBindingRole.COUNTEREVIDENCE
                        if counter
                        else EvidenceBindingRole.PRIMARY,
                        provenance=provenance if isinstance(provenance, dict) else {},
                    )
                )
                session.add(
                    LectureCitation(
                        lecture_master_version_id=master.id,
                        claim_id=claim.id,
                        kind=CitationKind.EXTERNAL,
                        package_id=package.id,
                        citation_data=provenance
                        if isinstance(provenance, dict)
                        else {},
                    )
                )
                sequence += 1
        for relation in snapshot.get("dialogue_relations", []):
            if not isinstance(relation, dict):
                continue
            relation_type = str(relation.get("relation_type"))
            status = (
                ClaimEpistemicStatus.NON_EQUIVALENCE
                if relation_type == "NOT_EQUIVALENT_TO"
                else ClaimEpistemicStatus.CONCEPTUAL_PARALLEL
            )
            explanation = str(relation.get("explanation", "")).strip()
            proposition = (
                f"The external dialogue item is classified as {relation_type} "
                f"within {relation.get('scope', 'UNSPECIFIED')} scope. "
                "The classification remains "
                f"{relation.get('review_status', 'PROPOSED')}: {explanation}"
            )
            claim = LectureClaim(
                lecture_master_version_id=master.id,
                section_id=sections[2].id,
                stable_key=f"dialogue_{sequence}",
                sequence=sequence,
                claim_intent=proposition,
                semantic_proposition=proposition,
                plain_meaning=(
                    "This relation is a reviewable dialogue classification, "
                    "not an identity or proof claim."
                ),
                required_qualifiers=[
                    f"Review status is {relation.get('review_status', 'PROPOSED')}",
                    "Preserve non-equivalence where present",
                ],
                prohibited_overstatements=[
                    "Do not call the relation established, confirmed, or approved"
                ],
                source_support_summary=explanation,
                source_evidence=[
                    {
                        "relation_id": str(relation.get("relation_id")),
                        "explanation": explanation,
                    }
                ],
                claim_origin=ClaimOrigin.EXTERNAL,
                epistemic_status=status,
                discourse_type=DiscourseType.CONCEPTUAL,
                formulation_constraints=["Keep review status PROPOSED visible"],
            )
            session.add(claim)
            await session.flush()
            session.add(
                LectureClaimEvidence(
                    claim_id=claim.id,
                    evidence_kind=EvidenceKind.DIALOGUE_RELATION,
                    evidence_item_id=str(relation.get("relation_id")),
                    package_id=package.id,
                    binding_role=EvidenceBindingRole.CONTEXT,
                    provenance=relation,
                )
            )
            sequence += 1

    async def _ritual_links(
        self,
        session: AsyncSession,
        master: LectureMasterVersion,
        package: ResearchPackage,
    ) -> None:
        rows = await session.scalars(
            select(ResearchPackageRitualVersion).where(
                ResearchPackageRitualVersion.package_id == package.id
            )
        )
        for row in rows:
            session.add(
                LectureRitualLink(
                    lecture_master_version_id=master.id,
                    package_id=package.id,
                    ritual_version_id=row.ritual_version_id,
                    relation_type="EXPERIENTIAL_COMPANION",
                    optional=True,
                    safety_metadata={
                        "selection_role": row.selection_role.value,
                        "authority": "MANASEK_WORKING",
                    },
                )
            )

    async def _payload(
        self, session: AsyncSession, master: LectureMasterVersion
    ) -> dict[str, Any]:
        claims = list(
            await session.scalars(
                select(LectureClaim)
                .where(LectureClaim.lecture_master_version_id == master.id)
                .order_by(LectureClaim.sequence)
            )
        )
        evidence = (
            list(
                await session.scalars(
                    select(LectureClaimEvidence).where(
                        LectureClaimEvidence.claim_id.in_([c.id for c in claims])
                    )
                )
            )
            if claims
            else []
        )
        citations = list(
            await session.scalars(
                select(LectureCitation).where(
                    LectureCitation.lecture_master_version_id == master.id
                )
            )
        )
        sections = list(
            await session.scalars(
                select(LectureSection)
                .where(LectureSection.lecture_master_version_id == master.id)
                .order_by(LectureSection.ordinal)
            )
        )
        rituals = list(
            await session.scalars(
                select(LectureRitualLink).where(
                    LectureRitualLink.lecture_master_version_id == master.id
                )
            )
        )
        package = await session.get(ResearchPackage, master.research_package_id)
        relations = (
            package.retrieval_snapshot.get("dialogue_relations", []) if package else []
        )
        snapshot_items = (
            self._snapshot_items(package.retrieval_snapshot) if package else {}
        )
        evidence_payload: list[dict[str, object]] = []
        for row in evidence:
            value = self._row_dict(row) | {"claim_id": str(row.claim_id)}
            item = snapshot_items.get(str(row.evidence_item_id))
            if item:
                value["text"] = item.get("text", "")
                value["language"] = item.get("language")
                value["content_hash"] = item.get("content_hash")
                package_provenance = item.get("provenance", {})
                value["package_provenance"] = package_provenance
                if isinstance(package_provenance, dict):
                    for field in (
                        "corpus_zone",
                        "lane",
                        "source_type",
                        "source_title",
                        "creator",
                        "source_url",
                        "page_start",
                        "page_end",
                        "timestamp_start",
                        "timestamp_end",
                    ):
                        value[field] = package_provenance.get(field)
            evidence_payload.append(value)
        return {
            "master": LectureMasterRead.model_validate(master).model_dump(mode="json"),
            "sections": [self._row_dict(s) for s in sections],
            "claims": [self._row_dict(c) for c in claims],
            "evidence": evidence_payload,
            "citations": [self._row_dict(c) for c in citations],
            "ritual_links": [self._row_dict(r) for r in rituals],
            "dialogue_relations": relations,
        }

    @staticmethod
    def _terminology_references(
        sections: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        references: list[dict[str, object]] = []
        seen: set[str] = set()
        for section in sections:
            values = section.get("required_terminology", [])
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, dict):
                    continue
                term_id = str(value.get("term_id", value.get("stable_key", "")))
                if term_id and term_id not in seen:
                    references.append(value)
                    seen.add(term_id)
        return references

    @staticmethod
    def _snapshot_items(snapshot: Any) -> dict[str, dict[str, object]]:
        items: dict[str, dict[str, object]] = {}
        for query in snapshot.get("queries", []) if isinstance(snapshot, dict) else []:
            if not isinstance(query, dict):
                continue
            for item in query.get("results", []):
                if not isinstance(item, dict):
                    continue
                chunk_id = str(item.get("chunk_id", ""))
                if chunk_id:
                    items[chunk_id] = item
                provenance = item.get("provenance", {})
                if isinstance(provenance, dict):
                    for record_id in provenance.get("record_ids", []):
                        items[str(record_id)] = item
        return items

    async def _ayin_semantic(
        self,
        session: AsyncSession,
        kind: EvidenceKind,
        item_id: UUID,
        snapshot_items: dict[str, dict[str, object]],
    ) -> dict[str, object]:
        source_text = ""
        proposition = "The selected Ayin Working source states the following material: "
        citation: dict[str, object] = {
            "evidence_item_id": str(item_id),
            "authority_status": "AYIN_WORKING",
        }
        if kind is EvidenceKind.AYIN_CONCEPT:
            row: Any = await session.get(AyinConceptVersion, item_id)
            if row:
                parent = await session.get(AyinConcept, row.concept_id)
                source_text = row.definition
                citation.update(
                    {
                        "concept_id": str(row.concept_id),
                        "stable_key": parent.stable_key if parent else None,
                        "source_passage_id": str(row.source_passage_id),
                        "version": row.version_number,
                    }
                )
        elif kind is EvidenceKind.AYIN_PRINCIPLE:
            row = await session.get(AyinPrincipleVersion, item_id)
            if row:
                source_text = row.statement
                citation.update(
                    {
                        "source_passage_id": str(row.source_passage_id),
                        "version": row.version_number,
                    }
                )
        elif kind is EvidenceKind.AYIN_DISTINCTION:
            row = await session.get(AyinDistinctionVersion, item_id)
            if row:
                source_text = row.explanation
                citation.update(
                    {
                        "source_passage_id": str(row.source_passage_id),
                        "relation": row.relation.value,
                        "version": row.version_number,
                    }
                )
        elif kind is EvidenceKind.AYIN_OPEN_QUESTION:
            row = await session.get(AyinOpenQuestionVersion, item_id)
            if row:
                source_text = f"{row.question}\n{row.context}"
                proposition = (
                    "The Ayin source preserves this as an open question, not a "
                    "resolved conclusion: "
                )
                citation.update(
                    {
                        "source_passage_id": str(row.source_passage_id),
                        "version": row.version_number,
                    }
                )
        elif kind is EvidenceKind.AYIN_PASSAGE:
            row = await session.get(CanonPassage, item_id)
            if row:
                source_text = row.raw_text
                citation.update(
                    {
                        "source_passage_id": str(row.id),
                        "page": row.page_number,
                        "heading_path": row.heading_path,
                        "language": row.language.value,
                    }
                )
        item = snapshot_items.get(str(item_id))
        if item and not source_text:
            source_text = str(item.get("text", ""))
        source_text = source_text.strip() or (
            "Source text is unavailable in the frozen package; retain the item "
            "as unresolved."
        )
        return {
            "semantic_proposition": proposition + source_text,
            "plain_meaning": source_text,
            "required_concepts": [str(citation.get("stable_key"))]
            if citation.get("stable_key")
            else [],
            "source_support_summary": source_text,
            "source_evidence": [
                {
                    "text": source_text,
                    "evidence_item_id": str(item_id),
                    "authority_status": "AYIN_WORKING",
                }
            ],
            "citation": citation,
        }

    async def _terminology_for_package(
        self, session: AsyncSession, package_id: UUID
    ) -> list[dict[str, object]]:
        refs: list[dict[str, object]] = []
        rows = await session.scalars(
            select(ResearchPackageAyinConcept).where(
                ResearchPackageAyinConcept.package_id == package_id
            )
        )
        for link in rows:
            version = await session.get(AyinConceptVersion, link.concept_version_id)
            if version is None:
                continue
            concept = await session.get(AyinConcept, version.concept_id)
            if concept is None:
                continue
            refs.append(
                {
                    "term_id": str(concept.id),
                    "source_form": concept.stable_key,
                    "definition": version.definition,
                    "usage_constraints": [
                        "Preserve Ayin Working meaning and do not replace with "
                        "a misleading equivalent"
                    ],
                    "prohibited_equivalents": [],
                    "review_status": "WORKING",
                    "available_language_forms": {},
                }
            )
        if refs:
            return refs
        package = await session.get(ResearchPackage, package_id)
        snapshot = package.lesson_content_package_snapshot if package else None
        if not isinstance(snapshot, dict):
            return refs
        registry = snapshot.get("core_concept_registry", [])
        if not isinstance(registry, list):
            return refs
        for item in registry:
            if not isinstance(item, dict):
                continue
            lesson_id = str(item.get("lesson_id", "")).strip()
            title = str(item.get("title_fa", "")).strip()
            definition = str(item.get("locked_definition_fa", "")).strip()
            if lesson_id and title and definition:
                refs.append(
                    {
                        "term_id": f"lesson:{lesson_id}",
                        "source_form": title,
                        "definition": definition,
                        "usage_constraints": [
                            "Preserve the locked Lesson Canon meaning",
                            "Do not auto-translate protected Ayin terminology",
                        ],
                        "prohibited_equivalents": [],
                        "review_status": "CANONICAL_LESSON",
                        "available_language_forms": {"fa": title},
                    }
                )
        return refs

    @staticmethod
    def _row_dict(row: Any) -> dict[str, object]:
        return {
            column.name: (
                getattr(row, column.name).value
                if hasattr(getattr(row, column.name), "value")
                else str(getattr(row, column.name))
                if isinstance(getattr(row, column.name), UUID)
                else getattr(row, column.name)
            )
            for column in row.__table__.columns
        }

    @staticmethod
    def _validation_read(findings: list[LectureFinding]) -> LectureValidationRead:
        return LectureValidationRead(
            valid=not findings,
            findings=[
                {
                    "dimension": f.dimension,
                    "code": f.code,
                    "severity": f.severity,
                    "message": f.message,
                    "blocking": f.blocking,
                }
                for f in findings
            ],
        )

    @staticmethod
    async def _ayin_ids(
        session: AsyncSession, package_id: UUID
    ) -> list[tuple[EvidenceKind, UUID]]:
        result: list[tuple[EvidenceKind, UUID]] = []
        for model, kind, field in (
            (ResearchPackageAyinPassage, EvidenceKind.AYIN_PASSAGE, "passage_id"),
            (
                ResearchPackageAyinConcept,
                EvidenceKind.AYIN_CONCEPT,
                "concept_version_id",
            ),
            (
                ResearchPackageAyinPrinciple,
                EvidenceKind.AYIN_PRINCIPLE,
                "principle_version_id",
            ),
            (
                ResearchPackageAyinDistinction,
                EvidenceKind.AYIN_DISTINCTION,
                "distinction_version_id",
            ),
            (
                ResearchPackageAyinOpenQuestion,
                EvidenceKind.AYIN_OPEN_QUESTION,
                "open_question_version_id",
            ),
        ):
            rows = await session.scalars(
                select(model).where(model.package_id == package_id)
            )
            result.extend((kind, getattr(row, field)) for row in rows)
        return result

    @staticmethod
    def _authority(package: ResearchPackage) -> dict[str, object]:
        queries_raw = package.retrieval_snapshot.get("queries", [])
        queries = queries_raw if isinstance(queries_raw, list) else []
        has_manasek = any(
            isinstance(query, dict) and query.get("kind") == "MANASEK"
            for query in queries
        )
        return {
            "ayin": "LESSON_CANON" if package.lesson_id else "AYIN_WORKING",
            "manasek": "MANASEK_WORKING" if has_manasek else None,
            "package_status": package.status.value,
            "lesson_id": package.lesson_id,
            "lesson_canon_hash": package.lesson_canon_hash,
            "external_research_only": package.lesson_id is not None,
        }

    @staticmethod
    def _human_question(package: ResearchPackage) -> str:
        return str(
            package.retrieval_snapshot.get(
                "human_question", "ResearchPackage human question"
            )
        )

    @staticmethod
    def _prohibited(package: ResearchPackage) -> list[str]:
        return [
            "External evidence is not automatic proof of Ayin",
            "PROPOSED dialogue relations remain unreviewed",
            "Manasek is optional experiential context",
        ]

    @staticmethod
    def _section_purpose(role: SectionRole, _package: ResearchPackage) -> str:
        purposes = {
            SectionRole.HUMAN_ENTRY: "Connect the human question to lived experience.",
            SectionRole.AYIN_FRAME: (
                "Establish the selected Ayin Working frame and distinctions."
            ),
            SectionRole.EXTERNAL_DIALOGUE: (
                "Place external evidence and dialogue relations beside Ayin "
                "without equivalence."
            ),
            SectionRole.COUNTERARGUMENT: (
                "Expose counterevidence, limits, and alternative explanations."
            ),
            SectionRole.LIFE_RETURN: (
                "Return the structured inquiry to life without false resolution."
            ),
        }
        if role is SectionRole.AYIN_FRAME and _package.lesson_id is not None:
            return (
                "Use the pinned canonical Lesson Content Package as the Ayin core; "
                "do not retrieve or recreate it."
            )
        return purposes.get(role, role.value)
