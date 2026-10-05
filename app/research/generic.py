"""Generic brief-origin research path: no lesson, no spine required."""

import hashlib
import json
import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.briefs.models import ContentBrief
from app.db.session import Database
from app.editorial_channels.models import EditorialChannel
from app.knowledge.models import SourceVersion
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
from app.research.epistemic import (
    EpistemicStatus,
    classify_epistemic,
    unknown_evidence_warnings,
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

logger = logging.getLogger(__name__)


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
            channel = await session.get(EditorialChannel, brief.editorial_channel_id)
            channel_slug = channel.slug if channel is not None else ""
            status_pairs: list[tuple[str, str]] = []
            for ordinal, unit in enumerate(units, start=1):
                epistemic = classify_epistemic(
                    unit_type=unit.unit_type,
                    claim_type=unit.claim_type,
                    evidence_level=unit.evidence_level,
                )
                status_pairs.append((str(ordinal), epistemic.value))
                session.add(
                    EvidenceMatrixItem(
                        evidence_matrix_id=matrix.id,
                        ordinal=ordinal,
                        role=_unit_role(unit),
                        claim_text=unit.summary,
                        claim_type=unit.claim_type.value,
                        epistemic_status=epistemic.value,
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
            for warning in unknown_evidence_warnings(
                status_pairs, channel_slug=channel_slug
            ):
                logger.warning(
                    "evidence_matrix.unknown_epistemic",
                    extra={
                        "matrix_id": str(matrix.id),
                        "channel": channel_slug,
                        "warning": warning,
                    },
                )
            # §16 truth: a matrix becomes READY only after its own validation
            # pass — created rows are DRAFT until the checks below pass.
            report = await self._validate_matrix(session, matrix, brief)
            matrix.validation_report = report
            if report["passed"]:
                matrix.status = EvidenceMatrixStatus.READY
            return matrix

    async def _validate_matrix(
        self,
        session: AsyncSession,
        matrix: EvidenceMatrix,
        brief: ContentBrief,
    ) -> dict[str, object]:
        """§16 pre-READY validation: structure must be sound before READY.

        Hard failures (missing items, dead references, invalid epistemic
        fields) keep the matrix DRAFT. Content gaps (missing
        counterevidence/alternatives) are persisted as unresolved gaps —
        a READY matrix with documented gaps is honest; faking coverage
        is not.
        """

        items = list(
            (
                await session.scalars(
                    select(EvidenceMatrixItem).where(
                        EvidenceMatrixItem.evidence_matrix_id == matrix.id
                    )
                )
            ).all()
        )
        checks: dict[str, bool] = {}
        failures: list[str] = []
        gaps: list[dict[str, str]] = []

        checks["items_present"] = bool(items)
        if not items:
            failures.append("matrix contains no evidence items")

        epistemic_values = {status.value for status in EpistemicStatus}
        bad_epistemic = [
            item.ordinal
            for item in items
            if not item.claim_text.strip()
            or item.epistemic_status not in epistemic_values
        ]
        checks["epistemic_fields_valid"] = not bad_epistemic
        if bad_epistemic:
            failures.append(
                f"items {bad_epistemic} have empty claim or invalid epistemic status"
            )

        ref_ids: set[str] = set()
        for item in items:
            for raw in (
                *item.supporting_unit_ids,
                *item.counterevidence_unit_ids,
                *item.alternative_unit_ids,
            ):
                ref_ids.add(str(raw))
        parseable: set[UUID] = set()
        dead_refs = 0
        for raw in ref_ids:
            try:
                parseable.add(UUID(raw))
            except (ValueError, AttributeError):
                dead_refs += 1
        existing_units: dict[UUID, KnowledgeUnit] = {}
        if parseable:
            existing_units = {
                row.id: row
                for row in (
                    await session.scalars(
                        select(KnowledgeUnit).where(KnowledgeUnit.id.in_(parseable))
                    )
                ).all()
            }
        missing = parseable - set(existing_units)
        checks["evidence_references_valid"] = not dead_refs and not missing
        if dead_refs or missing:
            failures.append(
                f"{dead_refs} unparseable and {len(missing)} dangling unit references"
            )

        unsupported = [item.ordinal for item in items if not item.supporting_unit_ids]
        checks["supporting_evidence_structured"] = not unsupported
        if unsupported:
            failures.append(f"items {unsupported} have no supporting evidence units")

        source_versions = {row.source_version_id for row in existing_units.values()}
        existing_versions = (
            set(
                (
                    await session.scalars(
                        select(SourceVersion.id).where(
                            SourceVersion.id.in_(source_versions)
                        )
                    )
                ).all()
            )
            if source_versions
            else set()
        )
        checks["provenance_valid"] = source_versions == existing_versions
        if not checks["provenance_valid"]:
            failures.append(
                "referenced units point at source versions that do not exist"
            )

        has_counter = any(
            item.counterevidence_unit_ids
            or item.role is EvidenceSelectionRole.COUNTEREVIDENCE
            for item in items
        )
        if brief.required_counterargument and not has_counter:
            gaps.append(
                {
                    "kind": "counterevidence_missing",
                    "detail": "Brief requires a counterargument but no "
                    "counterevidence unit is linked.",
                }
            )
        has_alternative = any(item.alternative_unit_ids for item in items)
        channel = await session.get(EditorialChannel, brief.editorial_channel_id)
        strict_channels = {"science-mystery", "psychology-evolution"}
        if (
            channel is not None
            and channel.slug in strict_channels
            and not has_alternative
        ):
            gaps.append(
                {
                    "kind": "alternative_explanation_missing",
                    "detail": "Channel requires alternative explanations "
                    "but none are linked.",
                }
            )
        return {
            "validator": "evidence_matrix_v1",
            "checks": checks,
            "failures": failures,
            "unresolved_gaps": gaps,
            "passed": not failures,
        }

    async def revalidate_matrix(self, matrix_id: UUID) -> EvidenceMatrix:
        """Re-run §16 validation on an existing matrix.

        Used by tests and by the owner to re-check a matrix after its
        underlying material changed. A failing matrix drops/stays DRAFT;
        a passing one is promoted to READY.
        """

        async with self.database.transaction() as session:
            matrix = await session.get(EvidenceMatrix, matrix_id)
            if matrix is None:
                raise LookupError(f"Unknown evidence matrix {matrix_id}")
            brief = await session.get(ContentBrief, matrix.content_brief_id)
            if brief is None:
                raise LookupError("Matrix brief is missing")
            report = await self._validate_matrix(session, matrix, brief)
            matrix.validation_report = report
            if report["passed"] and matrix.status is EvidenceMatrixStatus.DRAFT:
                matrix.status = EvidenceMatrixStatus.READY
            elif not report["passed"] and matrix.status is EvidenceMatrixStatus.READY:
                matrix.status = EvidenceMatrixStatus.DRAFT
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
            if matrix.status not in {
                EvidenceMatrixStatus.READY,
                EvidenceMatrixStatus.FROZEN,
            }:
                raise ValueError(
                    "Evidence matrix failed validation — cannot freeze "
                    "research on an unvalidated matrix"
                )
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
