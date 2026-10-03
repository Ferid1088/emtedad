"""Generic brief-origin research path: no lesson, no spine required."""

import hashlib
import json
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.briefs.models import ContentBrief
from app.db.session import Database
from app.knowledge.units.domain import KnowledgeUnitType
from app.knowledge.units.models import KnowledgeUnit
from app.research.domain import (
    EvidenceMatrixStatus,
    EvidenceSelectionRole,
    PackageStatus,
    ResearchPlanStatus,
    ResearchQuestionKind,
    ResearchQuestionStatus,
)
from app.research.models import (
    EvidenceMatrix,
    EvidenceMatrixItem,
    ResearchPackage,
    ResearchPlan,
    ResearchPlanQuestion,
    ResearchProject,
)
from app.retrieval.models import RetrievalConfiguration
from app.topics.models import TopicCandidateUnit


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


_UNIT_ROLE = {
    KnowledgeUnitType.STORY: EvidenceSelectionRole.CASE_STUDY,
    KnowledgeUnitType.CASE_STUDY: EvidenceSelectionRole.CASE_STUDY,
    KnowledgeUnitType.COUNTERARGUMENT: EvidenceSelectionRole.COUNTEREVIDENCE,
    KnowledgeUnitType.OPEN_QUESTION: EvidenceSelectionRole.OPEN_QUESTION,
    KnowledgeUnitType.EXAMPLE: EvidenceSelectionRole.EXAMPLE,
    KnowledgeUnitType.EXPLANATION: EvidenceSelectionRole.SUPPORTING_EVIDENCE,
}


def _unit_role(unit: KnowledgeUnit) -> EvidenceSelectionRole:
    return _UNIT_ROLE.get(unit.unit_type, EvidenceSelectionRole.PRIMARY_EVIDENCE)


class GenericResearchService:
    """Create research artifacts that originate from a ContentBrief."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def create_plan_for_brief(
        self, brief_id: UUID, *, created_by: str = "studio"
    ) -> ResearchPlan:
        """Create a ResearchPlan whose sole origin is a ContentBrief."""

        async with self.database.transaction() as session:
            brief = await session.get(ContentBrief, brief_id)
            if brief is None:
                raise LookupError(f"Unknown content brief {brief_id}")
            version_number = int(
                await session.scalar(
                    select(
                        func.coalesce(func.max(ResearchPlan.version_number), 0) + 1
                    ).where(ResearchPlan.content_brief_id == brief_id)
                )
                or 1
            )
            questions = [
                brief.question,
                f"Counterevidence for: {brief.thesis}",
                *(
                    f"What does the base say about {concept}?"
                    for concept in brief.primary_concepts_json
                ),
            ]
            plan = ResearchPlan(
                content_brief_id=brief.id,
                human_question=brief.question,
                query_provenance={"brief_id": str(brief.id)},
                version_number=version_number,
                prohibited_conflations=[],
                retrieval_configuration={
                    "retriever": "unit-hybrid",
                    "counterevidence_required": bool(brief.required_counterargument),
                    "max_candidates_per_question": 8,
                },
                input_hash=_hash(
                    {
                        "brief": str(brief.id),
                        "question": brief.question,
                        "thesis": brief.thesis,
                        "concepts": brief.primary_concepts_json,
                    }
                ),
                status=ResearchPlanStatus.READY,
                created_by=created_by,
            )
            session.add(plan)
            await session.flush()
            for ordinal, question in enumerate(questions, start=1):
                session.add(
                    ResearchPlanQuestion(
                        research_plan_id=plan.id,
                        ordinal=ordinal,
                        kind=(
                            ResearchQuestionKind.COUNTEREVIDENCE
                            if ordinal == 2
                            else ResearchQuestionKind.EXTERNAL_CONCEPT
                        ),
                        question=question,
                        retrieval_text=question,
                        requires_counterevidence=(
                            ordinal == 2 and bool(brief.required_counterargument)
                        ),
                        status=ResearchQuestionStatus.OPEN,
                    )
                )
            return plan

    async def build_evidence_matrix(self, brief_id: UUID) -> EvidenceMatrix:
        """Build a versioned matrix from the brief's topic-grounded units."""

        async with self.database.transaction() as session:
            brief = await session.get(ContentBrief, brief_id)
            if brief is None:
                raise LookupError(f"Unknown content brief {brief_id}")
            unit_ids = list(
                (
                    await session.scalars(
                        select(TopicCandidateUnit.knowledge_unit_id).where(
                            TopicCandidateUnit.topic_candidate_id
                            == brief.topic_candidate_id
                        )
                    )
                ).all()
            )
            if not unit_ids:
                raise ValueError("Brief's candidate has no grounding units")
            units = list(
                (
                    await session.scalars(
                        select(KnowledgeUnit).where(KnowledgeUnit.id.in_(unit_ids))
                    )
                ).all()
            )
            version_number = int(
                await session.scalar(
                    select(
                        func.coalesce(func.max(EvidenceMatrix.version_number), 0) + 1
                    ).where(EvidenceMatrix.content_brief_id == brief_id)
                )
                or 1
            )
            matrix = EvidenceMatrix(
                content_brief_id=brief_id,
                version_number=version_number,
                status=EvidenceMatrixStatus.DRAFT,
                content_hash=_hash(
                    {
                        "brief": str(brief_id),
                        "units": sorted(str(unit_id) for unit_id in unit_ids),
                        "version": version_number,
                    }
                ),
            )
            session.add(matrix)
            await session.flush()
            for ordinal, unit in enumerate(units, start=1):
                session.add(
                    EvidenceMatrixItem(
                        evidence_matrix_id=matrix.id,
                        ordinal=ordinal,
                        role=_unit_role(unit),
                        claim_text=unit.summary,
                        claim_type=unit.claim_type.value,
                        epistemic_status=unit.evidence_level.value,
                        supporting_unit_ids=[str(unit.id)],
                        source_quality=unit.evidence_level.value,
                        limitations=(
                            "Extracted knowledge unit; verify against "
                            "the source segment span."
                        ),
                        allowed_wording=unit.summary,
                        forbidden_wording="; ".join(brief.forbidden_claims_json),
                    )
                )
            return matrix

    async def freeze_package(
        self, plan_id: UUID, *, created_by: str = "studio"
    ) -> ResearchPackage:
        """Freeze a brief-origin ResearchPackage: units, claims, roles,
        provenance, uncertainty, content hash."""

        async with self.database.transaction() as session:
            plan = await session.get(ResearchPlan, plan_id)
            if plan is None or plan.content_brief_id is None:
                raise LookupError(f"Unknown brief-origin research plan {plan_id}")
            brief = await session.get(ContentBrief, plan.content_brief_id)
            if brief is None:
                raise LookupError("Plan brief is missing")
            matrix = await session.scalar(
                select(EvidenceMatrix)
                .where(EvidenceMatrix.content_brief_id == brief.id)
                .order_by(EvidenceMatrix.version_number.desc())
                .limit(1)
            )
            if matrix is None:
                raise ValueError("Build an evidence matrix first")
            items = list(
                (
                    await session.scalars(
                        select(EvidenceMatrixItem)
                        .where(EvidenceMatrixItem.evidence_matrix_id == matrix.id)
                        .order_by(EvidenceMatrixItem.ordinal)
                    )
                ).all()
            )
            unit_ids = sorted(
                unit_id for item in items for unit_id in item.supporting_unit_ids
            )
            units = (
                list(
                    (
                        await session.scalars(
                            select(KnowledgeUnit).where(
                                KnowledgeUnit.id.in_(
                                    [UUID(unit_id) for unit_id in unit_ids]
                                )
                            )
                        )
                    ).all()
                )
                if unit_ids
                else []
            )
            configuration = await self._configuration(session)
            project = ResearchProject(
                human_question=brief.question, created_by=created_by
            )
            session.add(project)
            await session.flush()
            snapshot = {
                "selected_unit_ids": unit_ids,
                "claims": [
                    {
                        "claim_text": item.claim_text,
                        "claim_type": item.claim_type,
                        "epistemic_status": item.epistemic_status,
                        "role": item.role.value,
                    }
                    for item in items
                ],
                "counterevidence": [item.counterevidence_unit_ids for item in items],
                "alternative_explanations": [
                    item.alternative_unit_ids for item in items
                ],
                "source_provenance": [
                    {
                        "unit_id": str(unit.id),
                        "source_version_id": str(unit.source_version_id),
                        "extraction_run_id": (
                            str(unit.extraction_run_id)
                            if unit.extraction_run_id
                            else None
                        ),
                        "content_hash": unit.content_hash,
                    }
                    for unit in units
                ],
                "source_quality": [
                    {"unit_id": str(unit.id), "quality": unit.evidence_level.value}
                    for unit in units
                ],
                "uncertainty": [
                    {
                        "unit_id": str(unit.id),
                        "evidence_level": unit.evidence_level.value,
                    }
                    for unit in units
                    if unit.evidence_level.value != "STRONG"
                ],
                "evidence_matrix_id": str(matrix.id),
                "matrix_version": matrix.version_number,
            }
            package_version = int(
                await session.scalar(
                    select(
                        func.coalesce(func.max(ResearchPackage.package_version), 0) + 1
                    ).where(ResearchPackage.research_project_id == project.id)
                )
                or 1
            )
            package = ResearchPackage(
                research_project_id=project.id,
                content_brief_id=brief.id,
                research_plan_id=plan.id,
                retrieval_configuration_id=configuration.id,
                package_version=package_version,
                status=PackageStatus.FROZEN,
                retrieval_snapshot=snapshot,
                unresolved_issues=[],
                input_hash=plan.input_hash,
                content_hash=_hash(snapshot),
                created_by=created_by,
            )
            session.add(package)
            matrix.status = EvidenceMatrixStatus.FROZEN
            return package

    async def _configuration(self, session: AsyncSession) -> RetrievalConfiguration:
        """Reuse the latest retrieval configuration or create a stub."""

        existing = await session.scalar(
            select(RetrievalConfiguration).order_by(
                RetrievalConfiguration.created_at.desc()
            )
        )
        if existing is not None:
            return existing
        configuration = RetrievalConfiguration(
            name="unit-hybrid",
            version="1",
            parameters={"retriever": "unit-hybrid"},
            configuration_hash=_hash({"name": "unit-hybrid", "version": "1"}),
        )
        session.add(configuration)
        await session.flush()
        return configuration
