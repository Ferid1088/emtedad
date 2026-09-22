"""Deterministic Phase 7 orchestration from human question to frozen package."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ayin.domain import CorpusZone
from app.core.ayin.models import (
    AyinConcept,
    AyinConceptVersion,
    AyinDistinction,
    AyinDistinctionVersion,
    AyinOpenQuestion,
    AyinOpenQuestionVersion,
    AyinPrinciple,
    AyinPrincipleVersion,
    CanonPassage,
    CanonVersion,
)
from app.db.session import Database
from app.dialogue.models import (
    DialogueExternalTarget,
    DialogueProposal,
    DialogueRelation,
)
from app.knowledge.models import ExternalClaim
from app.research.domain import (
    EvidenceSelectionRole,
    PackageStatus,
    ResearchPlanStatus,
    ResearchProjectStatus,
    ResearchQuestionKind,
    ResearchQuestionStatus,
    SpineConceptRole,
    SpineStatus,
)
from app.research.models import (
    AyinSpine,
    AyinSpineConcept,
    AyinSpineDistinction,
    AyinSpineOpenQuestion,
    AyinSpinePassage,
    AyinSpinePrinciple,
    ResearchPackage,
    ResearchPackageAyinConcept,
    ResearchPackageAyinDistinction,
    ResearchPackageAyinOpenQuestion,
    ResearchPackageAyinPassage,
    ResearchPackageAyinPrinciple,
    ResearchPackageDialogueRelation,
    ResearchPackageExternalChunk,
    ResearchPackageExternalClaim,
    ResearchPackageExternalPerson,
    ResearchPackageExternalWork,
    ResearchPackageRitualVersion,
    ResearchPlan,
    ResearchPlanQuestion,
    ResearchProject,
)
from app.research.schemas import (
    AyinSpineBuildRequest,
    AyinSpineRead,
    PackageEvidenceCounts,
    PackageIssueRead,
    ResearchPackageBuildRequest,
    ResearchPackageBuildResult,
    ResearchPackageRead,
    ResearchPlanCreate,
    ResearchPlanRead,
    ResearchProjectCreate,
    ResearchProjectRead,
    ResearchQuestionInput,
    ResearchQuestionRead,
    ResearchValidationReport,
)
from app.research.validator import (
    PlanValidationInput,
    ResearchEngineValidator,
    SpineValidationInput,
)
from app.retrieval.domain import BuildStatus, RetrievalLane
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.models import (
    ChunkExternalEntity,
    ChunkExternalSegment,
    ChunkingRun,
    ChunkRitualVersion,
    EmbeddingModel,
    RetrievalResult,
)
from app.retrieval.schemas import SearchResult
from app.retrieval.service import HybridRetrievalService


def _hash(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def _snapshot_id(value: UUID) -> str:
    """Encode UUID identifiers as JSON-safe strings in frozen snapshots."""

    return str(value)


class ResearchEngineService:
    """Owns versioned spine/plan construction and frozen package transactions."""

    def __init__(
        self, database: Database, embedding_provider: EmbeddingProvider
    ) -> None:
        self.database = database
        self.retrieval = HybridRetrievalService(database, embedding_provider)
        self.validator = ResearchEngineValidator()

    async def create_project(
        self, request: ResearchProjectCreate
    ) -> ResearchProjectRead:
        async with self.database.transaction() as session:
            project = ResearchProject(
                human_question=request.human_question,
                created_by=request.created_by,
            )
            session.add(project)
            await session.flush()
            return ResearchProjectRead.model_validate(project)

    async def projects(self) -> list[ResearchProjectRead]:
        async with self.database.transaction() as session:
            rows = await session.scalars(
                select(ResearchProject).order_by(ResearchProject.created_at)
            )
            return [ResearchProjectRead.model_validate(row) for row in rows]

    async def build_spine(self, request: AyinSpineBuildRequest) -> AyinSpineRead:
        async with self.database.transaction() as session:
            project = await session.get(ResearchProject, request.project_id)
            if project is None:
                raise ValueError("research project not found")
            canon_version = await self._canon_version(session, request.canon_version_id)
            primary = await self._concept_version(
                session, request.primary_concept, canon_version.id
            )
            secondary = [
                await self._concept_version(session, key, canon_version.id)
                for key in request.secondary_concepts
            ]
            principles = [
                await self._principle_version(session, key, canon_version.id)
                for key in request.principle_ids
            ]
            distinctions = [
                await self._distinction_version(session, key, canon_version.id)
                for key in request.distinction_ids
            ]
            questions = [
                await self._open_question_version(session, key, canon_version.id)
                for key in request.open_question_ids
            ]
            passage_ids = list(request.passage_ids)
            source_items: list[Any] = [
                primary,
                *secondary,
                *principles,
                *distinctions,
                *questions,
            ]
            passage_ids.extend(
                source_passage_id
                for source_passage_id in (
                    item.source_passage_id for item in source_items
                )
                if source_passage_id not in passage_ids
            )
            if not passage_ids:
                raise ValueError("Ayin Spine needs at least one source passage")
            await self._validate_passages(session, passage_ids, canon_version.id)
            discourse = sorted(
                {
                    item.discourse_type.value
                    for item in source_items
                    if getattr(item, "discourse_type", None) is not None
                }
            )
            prohibited = list(
                dict.fromkeys(
                    [
                        (
                            "Ayin concept is not automatically a personality or "
                            "identity theory"
                        ),
                        (
                            "External science does not prove conceptual, ethical, "
                            "or metaphysical Ayin statements"
                        ),
                        *request.prohibited_conflations,
                    ]
                )
            )
            spine_issues = self.validator.validate_spine(
                SpineValidationInput(
                    human_question=project.human_question,
                    concept_version_ids=[primary.id, *(item.id for item in secondary)],
                    passage_ids=passage_ids,
                    canon_version_id=canon_version.id,
                    target_canon_version_ids=[
                        item.canon_version_id for item in source_items
                    ],
                    discourse_types=discourse,
                    prohibited_conflations=prohibited,
                )
            )
            if any(issue.severity.value == "ERROR" for issue in spine_issues):
                raise ValueError(
                    "Ayin Spine validation failed: "
                    + ", ".join(issue.code for issue in spine_issues)
                )
            version_number = int(
                await session.scalar(
                    select(
                        func.coalesce(func.max(AyinSpine.version_number), 0) + 1
                    ).where(AyinSpine.research_project_id == project.id)
                )
                or 1
            )
            input_hash = _hash(
                {
                    "question": project.human_question,
                    "canon_version": canon_version.id,
                    "concepts": [primary.id, *(item.id for item in secondary)],
                    "principles": [item.id for item in principles],
                    "distinctions": [item.id for item in distinctions],
                    "open_questions": [item.id for item in questions],
                    "passages": passage_ids,
                }
            )
            spine = AyinSpine(
                research_project_id=project.id,
                canon_version_id=canon_version.id,
                version_number=version_number,
                central_human_question=project.human_question,
                canonical_question=request.canonical_question or project.human_question,
                discourse_types=discourse,
                prohibited_conflations=prohibited,
                optional_ritual_links=request.optional_ritual_links,
                input_hash=input_hash,
                status=SpineStatus.VALIDATED,
                created_by=request.created_by,
            )
            session.add(spine)
            await session.flush()
            for item, role in [
                (primary, SpineConceptRole.PRIMARY),
                *[(item, SpineConceptRole.SECONDARY) for item in secondary],
            ]:
                session.add(
                    AyinSpineConcept(
                        ayin_spine_id=spine.id,
                        concept_version_id=item.id,
                        canon_version_id=canon_version.id,
                        role=role,
                    )
                )
            for principle in principles:
                session.add(
                    AyinSpinePrinciple(
                        ayin_spine_id=spine.id,
                        principle_version_id=principle.id,
                        canon_version_id=canon_version.id,
                    )
                )
            for distinction in distinctions:
                session.add(
                    AyinSpineDistinction(
                        ayin_spine_id=spine.id,
                        distinction_version_id=distinction.id,
                        canon_version_id=canon_version.id,
                    )
                )
            for open_question in questions:
                session.add(
                    AyinSpineOpenQuestion(
                        ayin_spine_id=spine.id,
                        open_question_version_id=open_question.id,
                        canon_version_id=canon_version.id,
                    )
                )
            for passage_id in passage_ids:
                session.add(
                    AyinSpinePassage(
                        ayin_spine_id=spine.id,
                        passage_id=passage_id,
                        canon_version_id=canon_version.id,
                    )
                )
            project.status = ResearchProjectStatus.READY
            return await self._spine_read(session, spine)

    async def spine(self, spine_id: UUID) -> AyinSpineRead:
        async with self.database.transaction() as session:
            spine = await session.get(AyinSpine, spine_id)
            if spine is None:
                raise ValueError("Ayin Spine not found")
            return await self._spine_read(session, spine)

    async def create_plan(self, request: ResearchPlanCreate) -> ResearchPlanRead:
        async with self.database.transaction() as session:
            spine = await session.get(AyinSpine, request.spine_id)
            if spine is None:
                raise ValueError("Ayin Spine not found")
            project = await session.get(ResearchProject, spine.research_project_id)
            if project is None:
                raise ValueError("research project not found")
            inputs = request.questions or self._default_questions(
                project.human_question, spine
            )
            if request.manasek_relevant and not any(
                item.kind is ResearchQuestionKind.MANASEK for item in inputs
            ):
                inputs = [
                    *inputs,
                    ResearchQuestionInput(
                        kind=ResearchQuestionKind.MANASEK,
                        question=(
                            "What optional Manasek context is relevant without "
                            "serving as evidence for Ayin?"
                        ),
                        retrieval_text=project.human_question,
                    ),
                ]
            has_counter = any(
                item.kind is ResearchQuestionKind.COUNTEREVIDENCE for item in inputs
            )
            plan_issues = self.validator.validate_plan(
                PlanValidationInput(
                    question_count=len(inputs),
                    question_kinds=[item.kind for item in inputs],
                    has_counterevidence_question=has_counter,
                    manasek_relevant=request.manasek_relevant,
                    manasek_reason=request.manasek_reason,
                )
            )
            version_number = int(
                await session.scalar(
                    select(
                        func.coalesce(func.max(ResearchPlan.version_number), 0) + 1
                    ).where(ResearchPlan.ayin_spine_id == spine.id)
                )
                or 1
            )
            retrieval_configuration = {
                "retriever": "phase5-hybrid",
                "lanes": ["ayin", "external", "counterevidence"],
                "counterevidence_required": has_counter,
                "max_candidates_per_question": 5,
            }
            input_hash = _hash(
                {
                    "spine": spine.input_hash,
                    "questions": [item.model_dump(mode="json") for item in inputs],
                    "manasek": request.manasek_relevant,
                }
            )
            plan = ResearchPlan(
                ayin_spine_id=spine.id,
                version_number=version_number,
                manasek_relevant=request.manasek_relevant,
                manasek_reason=request.manasek_reason,
                prohibited_conflations=spine.prohibited_conflations
                + request.prohibited_conflations,
                retrieval_configuration=retrieval_configuration,
                input_hash=input_hash,
                status=ResearchPlanStatus.READY
                if not any(item.severity.value == "ERROR" for item in plan_issues)
                else ResearchPlanStatus.DRAFT,
                created_by=request.created_by,
            )
            session.add(plan)
            await session.flush()
            for ordinal, item in enumerate(inputs, start=1):
                session.add(
                    ResearchPlanQuestion(
                        research_plan_id=plan.id,
                        ordinal=ordinal,
                        kind=item.kind,
                        question=item.question,
                        retrieval_text=item.retrieval_text or item.question,
                        requires_counterevidence=item.requires_counterevidence,
                        status=ResearchQuestionStatus.OPEN,
                    )
                )
            return await self._plan_read(session, plan)

    async def plan(self, plan_id: UUID) -> ResearchPlanRead:
        async with self.database.transaction() as session:
            plan = await session.get(ResearchPlan, plan_id)
            if plan is None:
                raise ValueError("ResearchPlan not found")
            return await self._plan_read(session, plan)

    async def build_package(
        self, request: ResearchPackageBuildRequest
    ) -> ResearchPackageBuildResult:
        async with self.database.transaction() as session:
            plan = await session.get(ResearchPlan, request.plan_id)
            if plan is None:
                raise ValueError("ResearchPlan not found")
            spine = await session.get(AyinSpine, plan.ayin_spine_id)
            if spine is None:
                raise ValueError("Ayin Spine not found")
            project = await session.get(ResearchProject, spine.research_project_id)
            if project is None:
                raise ValueError("research project not found")
            questions = list(
                await session.scalars(
                    select(ResearchPlanQuestion)
                    .where(ResearchPlanQuestion.research_plan_id == plan.id)
                    .order_by(ResearchPlanQuestion.ordinal)
                )
            )
            chunking_run_id, embedding_model_id = await self._retrieval_pins(
                session, request.chunking_run_id, request.embedding_model_id
            )
        responses: list[tuple[ResearchPlanQuestion, object]] = []
        for question in questions:
            lanes = [RetrievalLane.EXTERNAL]
            if question.kind is ResearchQuestionKind.AYIN:
                lanes = [RetrievalLane.AYIN]
            elif (
                question.kind is ResearchQuestionKind.MANASEK
                and request.include_manasek
            ):
                lanes = [RetrievalLane.MANASEK]
            response = await self.retrieval.search(
                question.retrieval_text,
                request.language,
                chunking_run_id=chunking_run_id,
                embedding_model_id=embedding_model_id,
                lanes=lanes,
                parameters={"lane_top_n": request.max_candidates_per_question},
            )
            responses.append((question, response))
        return await self._persist_package(
            request,
            project.id,
            spine,
            plan,
            responses,
            chunking_run_id,
            embedding_model_id,
        )

    async def package(self, package_id: UUID) -> ResearchPackageRead:
        async with self.database.transaction() as session:
            package = await session.get(ResearchPackage, package_id)
            if package is None:
                raise ValueError("ResearchPackage not found")
            return await self._package_read(session, package)

    async def packages(self) -> list[ResearchPackageRead]:
        async with self.database.transaction() as session:
            rows = await session.scalars(
                select(ResearchPackage).order_by(ResearchPackage.created_at)
            )
            return [await self._package_read(session, row) for row in rows]

    async def validate(self) -> ResearchValidationReport:
        async with self.database.transaction() as session:
            packages = list(await session.scalars(select(ResearchPackage)))
            issues: list[PackageIssueRead] = []
            for package in packages:
                if package.status is not PackageStatus.FROZEN:
                    issues.append(
                        PackageIssueRead(
                            code="PACKAGE_NOT_FROZEN",
                            severity="ERROR",
                            message=str(package.id),
                            resolved=False,
                        )
                    )
                if package.frozen_at is None:
                    issues.append(
                        PackageIssueRead(
                            code="MISSING_FROZEN_AT",
                            severity="ERROR",
                            message=str(package.id),
                            resolved=False,
                        )
                    )
            return ResearchValidationReport(
                valid=not any(item.severity.value == "ERROR" for item in issues),
                issue_count=len(issues),
                issues=issues,
            )

    async def _persist_package(
        self,
        request: ResearchPackageBuildRequest,
        project_id: UUID,
        spine: AyinSpine,
        plan: ResearchPlan,
        responses: list[tuple[ResearchPlanQuestion, object]],
        chunking_run_id: UUID,
        embedding_model_id: UUID,
    ) -> ResearchPackageBuildResult:
        response_objects = [response for _question, response in responses]
        retrieval_run_ids = [response.retrieval_run_id for response in response_objects]  # type: ignore[attr-defined]
        input_hash = _hash(
            {
                "plan": plan.input_hash,
                "spine": spine.input_hash,
                "retrieval_runs": retrieval_run_ids,
                "embedding_model": embedding_model_id,
            }
        )
        async with self.database.transaction() as session:
            cached = await session.scalar(
                select(ResearchPackage).where(
                    ResearchPackage.input_hash == input_hash,
                    ResearchPackage.status == PackageStatus.FROZEN,
                )
            )
            if cached is not None:
                return ResearchPackageBuildResult(
                    package=await self._package_read(session, cached),
                    cache_hit=True,
                    retrieval_run_ids=retrieval_run_ids,
                )
            configuration_id = response_objects[0].retrieval_configuration_id  # type: ignore[attr-defined]
            version = int(
                await session.scalar(
                    select(
                        func.coalesce(func.max(ResearchPackage.package_version), 0) + 1
                    ).where(ResearchPackage.research_project_id == project_id)
                )
                or 1
            )
            external_chunks: dict[UUID, tuple[SearchResult, EvidenceSelectionRole]] = {}
            ritual_chunk_ids: set[UUID] = set()
            snapshot: list[dict[str, object]] = []
            for question, response in responses:
                role = (
                    EvidenceSelectionRole.COUNTEREVIDENCE
                    if question.kind is ResearchQuestionKind.COUNTEREVIDENCE
                    else EvidenceSelectionRole.EXTERNAL_EVIDENCE
                )
                if question.kind is ResearchQuestionKind.AYIN:
                    role = EvidenceSelectionRole.AYIN_GROUNDING
                snapshot.append(
                    {
                        "question_id": _snapshot_id(question.id),
                        "kind": question.kind.value,
                        "retrieval_run_id": _snapshot_id(response.retrieval_run_id),  # type: ignore[attr-defined]
                        "results": [
                            {
                                "chunk_id": _snapshot_id(result.chunk_id),
                                "rank": result.final_rank,
                                "text": result.text,
                                "language": result.language,
                                "fusion_score": result.fusion_score,
                                "reranker_score": result.reranker_score,
                                "content_hash": result.chunk_content_hash,
                                "provenance": result.provenance.model_dump(mode="json"),
                            }
                            for result in response.results  # type: ignore[attr-defined]
                        ],
                    }
                )
                for result in response.results:  # type: ignore[attr-defined]
                    if result.provenance.lane is RetrievalLane.EXTERNAL:
                        external_chunks.setdefault(result.chunk_id, (result, role))
                    elif result.provenance.lane is RetrievalLane.MANASEK:
                        ritual_chunk_ids.add(result.chunk_id)
            retrieval_snapshot = {
                "chunking_run_id": _snapshot_id(chunking_run_id),
                "embedding_model_id": _snapshot_id(embedding_model_id),
                "queries": snapshot,
            }
            content_hash = _hash(
                {
                    "spine": spine.input_hash,
                    "plan": plan.input_hash,
                    "snapshot": retrieval_snapshot,
                    "chunks": sorted(str(chunk_id) for chunk_id in external_chunks),
                }
            )
            package = ResearchPackage(
                research_project_id=project_id,
                ayin_spine_id=spine.id,
                research_plan_id=plan.id,
                canon_version_id=spine.canon_version_id,
                retrieval_configuration_id=configuration_id,
                package_version=version,
                status=PackageStatus.BUILDING,
                retrieval_snapshot=retrieval_snapshot,
                unresolved_issues=[],
                input_hash=input_hash,
                content_hash=content_hash,
                created_by=request.created_by,
            )
            session.add(package)
            await session.flush()
            spine_passages = list(
                await session.scalars(
                    select(AyinSpinePassage).where(
                        AyinSpinePassage.ayin_spine_id == spine.id
                    )
                )
            )
            for item in spine_passages:
                session.add(
                    ResearchPackageAyinPassage(
                        package_id=package.id,
                        passage_id=item.passage_id,
                        canon_version_id=item.canon_version_id,
                    )
                )
            for concept_link in await session.scalars(
                select(AyinSpineConcept).where(
                    AyinSpineConcept.ayin_spine_id == spine.id
                )
            ):
                session.add(
                    ResearchPackageAyinConcept(
                        package_id=package.id,
                        concept_version_id=concept_link.concept_version_id,
                        canon_version_id=concept_link.canon_version_id,
                    )
                )
            for principle_link in await session.scalars(
                select(AyinSpinePrinciple).where(
                    AyinSpinePrinciple.ayin_spine_id == spine.id
                )
            ):
                session.add(
                    ResearchPackageAyinPrinciple(
                        package_id=package.id,
                        principle_version_id=principle_link.principle_version_id,
                        canon_version_id=principle_link.canon_version_id,
                    )
                )
            for distinction_link in await session.scalars(
                select(AyinSpineDistinction).where(
                    AyinSpineDistinction.ayin_spine_id == spine.id
                )
            ):
                session.add(
                    ResearchPackageAyinDistinction(
                        package_id=package.id,
                        distinction_version_id=distinction_link.distinction_version_id,
                        canon_version_id=distinction_link.canon_version_id,
                    )
                )
            for question_link in await session.scalars(
                select(AyinSpineOpenQuestion).where(
                    AyinSpineOpenQuestion.ayin_spine_id == spine.id
                )
            ):
                session.add(
                    ResearchPackageAyinOpenQuestion(
                        package_id=package.id,
                        open_question_version_id=question_link.open_question_version_id,
                        canon_version_id=question_link.canon_version_id,
                    )
                )
            for result, role in external_chunks.values():
                retrieval_result_id = await session.scalar(
                    select(RetrievalResult.id)
                    .where(
                        RetrievalResult.chunk_id == result.chunk_id,
                        RetrievalResult.retrieval_run_id.in_(retrieval_run_ids),
                    )
                    .order_by(RetrievalResult.final_rank)
                    .limit(1)
                )
                session.add(
                    ResearchPackageExternalChunk(
                        package_id=package.id,
                        chunk_id=result.chunk_id,
                        source_version_id=result.provenance.source_version_id,
                        content_hash=result.chunk_content_hash,
                        selection_role=role,
                        retrieval_result_id=retrieval_result_id,
                    )
                )
            if external_chunks:
                chunk_ids = list(external_chunks)
                segment_rows = list(
                    await session.scalars(
                        select(ChunkExternalSegment).where(
                            ChunkExternalSegment.chunk_id.in_(chunk_ids)
                        )
                    )
                )
                segment_ids = [row.source_segment_id for row in segment_rows]
                if segment_ids:
                    claims = await session.execute(
                        select(ExternalClaim).where(
                            ExternalClaim.source_segment_id.in_(segment_ids)
                        )
                    )
                    for claim in claims.scalars().unique():
                        session.add(
                            ResearchPackageExternalClaim(
                                package_id=package.id,
                                claim_id=claim.id,
                                source_version_id=claim.source_version_id,
                                source_segment_id=claim.source_segment_id,
                            )
                        )
                entities = await session.scalars(
                    select(ChunkExternalEntity).where(
                        ChunkExternalEntity.chunk_id.in_(chunk_ids)
                    )
                )
                work_ids: set[UUID] = set()
                person_ids: set[UUID] = set()
                for entity in entities:
                    if entity.work_id is not None:
                        work_ids.add(entity.work_id)
                    if entity.person_id is not None:
                        person_ids.add(entity.person_id)
                for work_id in work_ids:
                    session.add(
                        ResearchPackageExternalWork(
                            package_id=package.id, work_id=work_id
                        )
                    )
                for person_id in person_ids:
                    session.add(
                        ResearchPackageExternalPerson(
                            package_id=package.id, person_id=person_id
                        )
                    )
                relation_rows = await session.execute(
                    select(DialogueRelation, DialogueProposal, DialogueExternalTarget)
                    .join(
                        DialogueProposal,
                        DialogueProposal.id == DialogueRelation.proposal_id,
                    )
                    .join(
                        DialogueExternalTarget,
                        DialogueExternalTarget.id
                        == DialogueProposal.external_target_id,
                    )
                    .where(DialogueExternalTarget.chunk_id.in_(chunk_ids))
                )
                dialogue_snapshot: list[dict[str, object]] = []
                for relation, _proposal, _target in relation_rows:
                    role = self._dialogue_role(relation.relation_type.value)
                    dialogue_snapshot.append(
                        {
                            "relation_id": str(relation.id),
                            "relation_type": relation.relation_type.value,
                            "scope": relation.scope.value,
                            "explanation": relation.explanation,
                            "review_status": relation.review_status.value,
                            "selection_role": role.value,
                        }
                    )
                    session.add(
                        ResearchPackageDialogueRelation(
                            package_id=package.id,
                            relation_id=relation.id,
                            review_status=relation.review_status.value,
                            selection_role=role,
                        )
                    )
                package.retrieval_snapshot = {
                    **package.retrieval_snapshot,
                    "dialogue_relations": dialogue_snapshot,
                }
            if ritual_chunk_ids and request.include_manasek:
                ritual_rows = await session.scalars(
                    select(ChunkRitualVersion).where(
                        ChunkRitualVersion.chunk_id.in_(ritual_chunk_ids)
                    )
                )
                for ritual_row in ritual_rows:
                    session.add(
                        ResearchPackageRitualVersion(
                            package_id=package.id,
                            ritual_version_id=ritual_row.ritual_version_id,
                            selection_role=EvidenceSelectionRole.RITUAL_CONTEXT,
                        )
                    )
            package.status = PackageStatus.FROZEN
            package.frozen_at = datetime.now(UTC)
            await session.flush()
            return ResearchPackageBuildResult(
                package=await self._package_read(session, package),
                cache_hit=False,
                retrieval_run_ids=retrieval_run_ids,
            )

    @staticmethod
    def _dialogue_role(relation_type: str) -> EvidenceSelectionRole:
        if relation_type == "ALTERNATIVE_EXPLANATION":
            return EvidenceSelectionRole.ALTERNATIVE_EXPLANATION
        if relation_type in {"TENSION_WITH", "CHALLENGES", "COUNTEREXAMPLE_TO"}:
            return EvidenceSelectionRole.TENSION
        if relation_type == "UNRESOLVED_RELATION":
            return EvidenceSelectionRole.UNRESOLVED
        if relation_type in {"CONCEPTUAL_PARALLEL", "NOT_EQUIVALENT_TO"}:
            return EvidenceSelectionRole.CONCEPTUAL_PARALLEL
        return EvidenceSelectionRole.EXTERNAL_EVIDENCE

    async def _spine_read(
        self, session: AsyncSession, spine: AyinSpine
    ) -> AyinSpineRead:
        concepts = list(
            await session.scalars(
                select(AyinSpineConcept)
                .where(AyinSpineConcept.ayin_spine_id == spine.id)
                .order_by(AyinSpineConcept.role)
            )
        )
        principles = list(
            await session.scalars(
                select(AyinSpinePrinciple).where(
                    AyinSpinePrinciple.ayin_spine_id == spine.id
                )
            )
        )
        distinctions = list(
            await session.scalars(
                select(AyinSpineDistinction).where(
                    AyinSpineDistinction.ayin_spine_id == spine.id
                )
            )
        )
        questions = list(
            await session.scalars(
                select(AyinSpineOpenQuestion).where(
                    AyinSpineOpenQuestion.ayin_spine_id == spine.id
                )
            )
        )
        passages = list(
            await session.scalars(
                select(AyinSpinePassage).where(
                    AyinSpinePassage.ayin_spine_id == spine.id
                )
            )
        )
        return AyinSpineRead(
            **{
                key: getattr(spine, key)
                for key in (
                    "id",
                    "research_project_id",
                    "canon_version_id",
                    "version_number",
                    "central_human_question",
                    "canonical_question",
                    "discourse_types",
                    "prohibited_conflations",
                    "optional_ritual_links",
                    "input_hash",
                    "status",
                    "created_by",
                    "created_at",
                )
            },
            concept_version_ids=[item.concept_version_id for item in concepts],
            principle_version_ids=[item.principle_version_id for item in principles],
            distinction_version_ids=[
                item.distinction_version_id for item in distinctions
            ],
            open_question_version_ids=[
                item.open_question_version_id for item in questions
            ],
            passage_ids=[item.passage_id for item in passages],
        )

    async def _plan_read(
        self, session: AsyncSession, plan: ResearchPlan
    ) -> ResearchPlanRead:
        questions = list(
            await session.scalars(
                select(ResearchPlanQuestion)
                .where(ResearchPlanQuestion.research_plan_id == plan.id)
                .order_by(ResearchPlanQuestion.ordinal)
            )
        )
        return ResearchPlanRead(
            **{
                key: getattr(plan, key)
                for key in (
                    "id",
                    "ayin_spine_id",
                    "version_number",
                    "manasek_relevant",
                    "manasek_reason",
                    "prohibited_conflations",
                    "retrieval_configuration",
                    "input_hash",
                    "status",
                    "created_by",
                    "created_at",
                )
            },
            questions=[ResearchQuestionRead.model_validate(item) for item in questions],
        )

    async def _package_read(
        self, session: AsyncSession, package: ResearchPackage
    ) -> ResearchPackageRead:
        counts = PackageEvidenceCounts(
            ayin_passages=await session.scalar(
                select(func.count())
                .select_from(ResearchPackageAyinPassage)
                .where(ResearchPackageAyinPassage.package_id == package.id)
            )
            or 0,
            ayin_concepts=await session.scalar(
                select(func.count())
                .select_from(ResearchPackageAyinConcept)
                .where(ResearchPackageAyinConcept.package_id == package.id)
            )
            or 0,
            ayin_principles=await session.scalar(
                select(func.count())
                .select_from(ResearchPackageAyinPrinciple)
                .where(ResearchPackageAyinPrinciple.package_id == package.id)
            )
            or 0,
            ayin_distinctions=await session.scalar(
                select(func.count())
                .select_from(ResearchPackageAyinDistinction)
                .where(ResearchPackageAyinDistinction.package_id == package.id)
            )
            or 0,
            ayin_open_questions=await session.scalar(
                select(func.count())
                .select_from(ResearchPackageAyinOpenQuestion)
                .where(ResearchPackageAyinOpenQuestion.package_id == package.id)
            )
            or 0,
            external_chunks=await session.scalar(
                select(func.count())
                .select_from(ResearchPackageExternalChunk)
                .where(ResearchPackageExternalChunk.package_id == package.id)
            )
            or 0,
            external_claims=await session.scalar(
                select(func.count())
                .select_from(ResearchPackageExternalClaim)
                .where(ResearchPackageExternalClaim.package_id == package.id)
            )
            or 0,
            external_works=await session.scalar(
                select(func.count())
                .select_from(ResearchPackageExternalWork)
                .where(ResearchPackageExternalWork.package_id == package.id)
            )
            or 0,
            external_people=await session.scalar(
                select(func.count())
                .select_from(ResearchPackageExternalPerson)
                .where(ResearchPackageExternalPerson.package_id == package.id)
            )
            or 0,
            dialogue_relations=await session.scalar(
                select(func.count())
                .select_from(ResearchPackageDialogueRelation)
                .where(ResearchPackageDialogueRelation.package_id == package.id)
            )
            or 0,
            ritual_versions=await session.scalar(
                select(func.count())
                .select_from(ResearchPackageRitualVersion)
                .where(ResearchPackageRitualVersion.package_id == package.id)
            )
            or 0,
        )
        return ResearchPackageRead(
            **{
                key: getattr(package, key)
                for key in (
                    "id",
                    "research_project_id",
                    "ayin_spine_id",
                    "research_plan_id",
                    "canon_version_id",
                    "retrieval_configuration_id",
                    "package_version",
                    "status",
                    "retrieval_snapshot",
                    "unresolved_issues",
                    "input_hash",
                    "content_hash",
                    "created_by",
                    "created_at",
                    "frozen_at",
                )
            },
            evidence_counts=counts,
        )

    @staticmethod
    def _default_questions(
        human_question: str, spine: AyinSpine
    ) -> list[ResearchQuestionInput]:
        return [
            ResearchQuestionInput(
                kind=ResearchQuestionKind.AYIN,
                question=f"How does Ayin frame this question: {human_question}",
                retrieval_text=human_question,
            ),
            ResearchQuestionInput(
                kind=ResearchQuestionKind.EMPIRICAL,
                question=("What external evidence is relevant without proving Ayin?"),
                retrieval_text=human_question,
            ),
            ResearchQuestionInput(
                kind=ResearchQuestionKind.COUNTEREVIDENCE,
                question=(
                    "What contradictory findings, boundary cases, or alternative "
                    "explanations bear on this question?"
                ),
                retrieval_text=human_question,
                requires_counterevidence=True,
            ),
        ]

    @staticmethod
    async def _canon_version(
        session: AsyncSession, version_id: UUID | None
    ) -> CanonVersion:
        if version_id is not None:
            version = await session.get(CanonVersion, version_id)
        else:
            version = await session.scalar(
                select(CanonVersion)
                .where(
                    CanonVersion.corpus_zone.in_(
                        [CorpusZone.AYIN_CANON, CorpusZone.AYIN_WORKING]
                    )
                )
                .order_by(CanonVersion.created_at.desc())
                .limit(1)
            )
        if version is None:
            raise ValueError("Ayin source version not found")
        return version

    @staticmethod
    async def _concept_version(
        session: AsyncSession, identifier: str, canon_version_id: UUID
    ) -> AyinConceptVersion:
        concept = await session.scalar(
            select(AyinConcept).where(AyinConcept.stable_key == identifier)
        )
        if concept is None:
            raise ValueError(f"Ayin concept not found: {identifier}")
        version = await session.scalar(
            select(AyinConceptVersion)
            .where(
                AyinConceptVersion.concept_id == concept.id,
                AyinConceptVersion.canon_version_id == canon_version_id,
            )
            .order_by(AyinConceptVersion.version_number.desc())
            .limit(1)
        )
        if version is None:
            raise ValueError(
                f"Ayin concept has no version in pinned corpus: {identifier}"
            )
        return version

    @staticmethod
    async def _principle_version(
        session: AsyncSession, identifier: str, canon_version_id: UUID
    ) -> AyinPrincipleVersion:
        condition = (
            AyinPrinciple.id == UUID(identifier)
            if _is_uuid(identifier)
            else AyinPrinciple.stable_key == identifier
        )
        stable = await session.scalar(select(AyinPrinciple).where(condition))
        if stable is None:
            raise ValueError(f"Ayin principle not found: {identifier}")
        version = await session.scalar(
            select(AyinPrincipleVersion)
            .where(
                AyinPrincipleVersion.principle_id == stable.id,
                AyinPrincipleVersion.canon_version_id == canon_version_id,
            )
            .order_by(AyinPrincipleVersion.version_number.desc())
            .limit(1)
        )
        if version is None:
            raise ValueError(f"Ayin principle has no pinned version: {identifier}")
        return version

    @staticmethod
    async def _distinction_version(
        session: AsyncSession, identifier: str, canon_version_id: UUID
    ) -> AyinDistinctionVersion:
        condition = (
            AyinDistinction.id == UUID(identifier)
            if _is_uuid(identifier)
            else AyinDistinction.stable_key == identifier
        )
        stable = await session.scalar(select(AyinDistinction).where(condition))
        if stable is None:
            raise ValueError(f"Ayin distinction not found: {identifier}")
        version = await session.scalar(
            select(AyinDistinctionVersion)
            .where(
                AyinDistinctionVersion.distinction_id == stable.id,
                AyinDistinctionVersion.canon_version_id == canon_version_id,
            )
            .order_by(AyinDistinctionVersion.version_number.desc())
            .limit(1)
        )
        if version is None:
            raise ValueError(f"Ayin distinction has no pinned version: {identifier}")
        return version

    @staticmethod
    async def _open_question_version(
        session: AsyncSession, identifier: str, canon_version_id: UUID
    ) -> AyinOpenQuestionVersion:
        condition = (
            AyinOpenQuestion.id == UUID(identifier)
            if _is_uuid(identifier)
            else AyinOpenQuestion.stable_key == identifier
        )
        stable = await session.scalar(select(AyinOpenQuestion).where(condition))
        if stable is None:
            raise ValueError(f"Ayin open question not found: {identifier}")
        version = await session.scalar(
            select(AyinOpenQuestionVersion)
            .where(
                AyinOpenQuestionVersion.open_question_id == stable.id,
                AyinOpenQuestionVersion.canon_version_id == canon_version_id,
            )
            .order_by(AyinOpenQuestionVersion.version_number.desc())
            .limit(1)
        )
        if version is None:
            raise ValueError(f"Ayin open question has no pinned version: {identifier}")
        return version

    @staticmethod
    async def _validate_passages(
        session: AsyncSession, passage_ids: list[UUID], canon_version_id: UUID
    ) -> None:
        found = set(
            await session.scalars(
                select(CanonPassage.id).where(
                    CanonPassage.id.in_(passage_ids),
                    CanonPassage.canon_version_id == canon_version_id,
                )
            )
        )
        if found != set(passage_ids):
            raise ValueError(
                "Every Ayin Spine passage must belong to its pinned corpus version"
            )

    @staticmethod
    async def _retrieval_pins(
        session: AsyncSession,
        chunking_run_id: UUID | None,
        embedding_model_id: UUID | None,
    ) -> tuple[UUID, UUID]:
        chunking_run_id = chunking_run_id or await session.scalar(
            select(ChunkingRun.id)
            .where(ChunkingRun.status == BuildStatus.SUCCEEDED)
            .order_by(ChunkingRun.created_at.desc())
            .limit(1)
        )
        embedding_model_id = embedding_model_id or await session.scalar(
            select(EmbeddingModel.id)
            .order_by(EmbeddingModel.created_at.desc())
            .limit(1)
        )
        if chunking_run_id is None or embedding_model_id is None:
            raise ValueError("successful chunking run and embedding model are required")
        return chunking_run_id, embedding_model_id


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True
