"""Targeted proposal, review, counterevidence, and dependency services."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ayin.domain import DiscourseType
from app.core.ayin.models import (
    AyinConcept,
    AyinConceptVersion,
    AyinDistinction,
    AyinDistinctionVersion,
    AyinOpenQuestion,
    AyinOpenQuestionVersion,
    AyinPrinciple,
    AyinPrincipleVersion,
)
from app.db.session import Database
from app.dialogue.classifier import (
    CLASSIFIER_VERSION,
    PROMPT_VERSION,
    EvidenceRoleClassifier,
)
from app.dialogue.domain import (
    AyinTargetKind,
    ClaimTestability,
    ExternalTargetKind,
    ProposalMethod,
    ProposalRunStatus,
    RelationType,
    ReviewAction,
    ReviewPriority,
    ReviewReason,
    ReviewStatus,
)
from app.dialogue.models import (
    DialogueAyinEvidence,
    DialogueAyinTarget,
    DialogueExternalEvidence,
    DialogueExternalTarget,
    DialogueProposal,
    DialogueProposalRun,
    DialogueProposalRunCandidate,
    DialogueRelation,
    DialogueReviewDecision,
    DialogueReviewFlag,
)
from app.dialogue.schemas import (
    CounterevidenceRequest,
    DialogueClassification,
    ProposalResult,
    ProposeRequest,
    ProvenancePins,
    RelationRead,
    ReviewQueueRead,
    ReviewRequest,
    ValidationIssue,
    ValidationReport,
)
from app.dialogue.validator import DialogueEpistemicValidator, ValidationInput
from app.knowledge.models import SourceVersion
from app.retrieval.domain import BuildStatus, RetrievalLane
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.models import ChunkingRun, EmbeddingModel
from app.retrieval.schemas import SearchResult
from app.retrieval.service import HybridRetrievalService


@dataclass(frozen=True, slots=True)
class AyinContext:
    kind: AyinTargetKind
    version_id: UUID
    canon_version_id: UUID
    passage_id: UUID
    stable_id: UUID
    text: str
    retrieval_text: str
    fixed_testability: ClaimTestability | None


def _hash(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return sha256(payload.encode()).hexdigest()


def proposal_cache_key(
    *,
    ayin_input_hash: str,
    candidate_input_hash: str,
    provider: str,
    model: str,
    configuration_hash: str,
    prompt_version: str = PROMPT_VERSION,
    classifier_version: str = CLASSIFIER_VERSION,
) -> str:
    """Key classifier results by every meaning- or behavior-changing input."""

    return _hash(
        {
            "ayin": ayin_input_hash,
            "candidates": candidate_input_hash,
            "provider": provider,
            "model": model,
            "prompt": prompt_version,
            "classifier": classifier_version,
            "configuration": configuration_hash,
        }
    )


def classifier_cache_key(
    *,
    ayin_version_id: UUID,
    ayin_input_hash: str,
    external_version_id: UUID,
    external_content_hash: str,
    provider: str,
    model: str,
    prompt_version: str = PROMPT_VERSION,
    classifier_version: str = CLASSIFIER_VERSION,
) -> str:
    """Key one pair judgment independently of its surrounding retrieval run."""

    return _hash(
        {
            "ayin_version": ayin_version_id,
            "ayin": ayin_input_hash,
            "external_version": external_version_id,
            "external": external_content_hash,
            "provider": provider,
            "model": model,
            "prompt": prompt_version,
            "classifier": classifier_version,
        }
    )


def review_status_for_action(action: ReviewAction) -> ReviewStatus:
    """Map explicit human action to lifecycle state; no implicit approval."""

    return {
        ReviewAction.START_REVIEW: ReviewStatus.IN_REVIEW,
        ReviewAction.APPROVE: ReviewStatus.APPROVED,
        ReviewAction.REJECT: ReviewStatus.REJECTED,
        ReviewAction.SUPERSEDE: ReviewStatus.SUPERSEDED,
    }[action]


def merge_counterevidence_results(
    batches: list[list[SearchResult]], *, limit: int
) -> list[SearchResult]:
    """Deduplicate only retrieved corpus results; an empty result is legitimate."""

    found: dict[UUID, SearchResult] = {}
    for batch in batches:
        for result in batch:
            found.setdefault(result.chunk_id, result)
    return list(found.values())[:limit]


def _fixed_testability(discourse: DiscourseType) -> ClaimTestability | None:
    return {
        DiscourseType.CONCEPTUAL: ClaimTestability.CONCEPTUAL,
        DiscourseType.ETHICAL: ClaimTestability.ETHICAL,
        DiscourseType.OPTIONAL_METAPHYSICAL: ClaimTestability.OPTIONAL_METAPHYSICAL,
        DiscourseType.DESCRIPTIVE: None,
    }[discourse]


class DialogueService:
    """Application service owning Phase 6 transactions and model side effects."""

    def __init__(
        self,
        database: Database,
        embedding_provider: EmbeddingProvider,
        classifier: EvidenceRoleClassifier,
    ) -> None:
        self.database = database
        self.retrieval = HybridRetrievalService(database, embedding_provider)
        self.classifier = classifier
        self.validator = DialogueEpistemicValidator()

    async def propose(self, request: ProposeRequest) -> ProposalResult:
        async with self.database.transaction() as session:
            context = await self._resolve_ayin_context(
                session, request.ayin_target_kind, request.ayin_identifier
            )
            chunking_run_id, embedding_model_id = await self._resolve_retrieval_pins(
                session, request.chunking_run_id, request.embedding_model_id
            )

        search = await self.retrieval.search(
            context.retrieval_text,
            request.language,
            chunking_run_id=chunking_run_id,
            embedding_model_id=embedding_model_id,
            lanes=[RetrievalLane.EXTERNAL],
            parameters={"lane_top_n": request.max_candidates},
        )
        candidates = search.results[: request.max_candidates]
        ayin_hash = _hash({"version": context.version_id, "text": context.text})
        candidate_hash = _hash(
            [(item.chunk_id, item.chunk_content_hash) for item in candidates]
        )
        configuration = {
            "language": request.language.value,
            "max_candidates": request.max_candidates,
            "retrieval_configuration_id": str(search.retrieval_configuration_id),
        }
        configuration_digest = _hash(configuration)
        run_cache_key = proposal_cache_key(
            ayin_input_hash=ayin_hash,
            candidate_input_hash=candidate_hash,
            provider=self.classifier.provider.name,
            model=request.model,
            configuration_hash=configuration_digest,
        )
        candidate_rows: list[tuple[DialogueProposalRunCandidate, SearchResult]] = []
        relation_ids: list[UUID] = []
        successes = 0
        cache_reused = False
        result_by_chunk = {item.chunk_id: item for item in candidates}
        async with self.database.transaction() as session:
            cached = await session.scalar(
                select(DialogueProposalRun).where(
                    DialogueProposalRun.cache_key == run_cache_key
                )
            )
            if cached is not None:
                relation_ids = list(
                    await session.scalars(
                        select(DialogueRelation.id)
                        .join(
                            DialogueProposal,
                            DialogueProposal.id == DialogueRelation.proposal_id,
                        )
                        .where(DialogueProposal.proposal_run_id == cached.id)
                        .order_by(DialogueRelation.created_at, DialogueRelation.id)
                    )
                )
                if cached.status is ProposalRunStatus.SUCCEEDED:
                    cached.cache_hit = True
                    return ProposalResult(
                        proposal_run_id=cached.id,
                        retrieval_run_id=cached.retrieval_run_id,
                        relation_ids=relation_ids,
                        candidate_count=cached.candidate_count,
                        success_count=cached.success_count,
                        failure_count=cached.failure_count,
                        cache_hit=True,
                    )
                stored_candidates = list(
                    await session.scalars(
                        select(DialogueProposalRunCandidate)
                        .where(
                            DialogueProposalRunCandidate.proposal_run_id == cached.id
                        )
                        .order_by(DialogueProposalRunCandidate.rank)
                    )
                )
                successes = sum(
                    item.structured_output is not None for item in stored_candidates
                )
                candidate_rows = [
                    (item, result_by_chunk[item.chunk_id])
                    for item in stored_candidates
                    if item.structured_output is None
                    and item.chunk_id in result_by_chunk
                ]
                for item, _result in candidate_rows:
                    item.error_code = None
                cached.status = ProposalRunStatus.RUNNING
                cached.failure_count = 0
                cached.completed_at = None
                run = cached
                cache_reused = True
            else:
                ayin_target = await self._ensure_ayin_target(session, context)
                run = DialogueProposalRun(
                    ayin_target_id=ayin_target.id,
                    retrieval_run_id=search.retrieval_run_id,
                    provider=self.classifier.provider.name,
                    model=request.model,
                    prompt_version=PROMPT_VERSION,
                    classifier_version=CLASSIFIER_VERSION,
                    retrieval_configuration=configuration,
                    configuration_hash=configuration_digest,
                    ayin_input_hash=ayin_hash,
                    candidate_input_hash=candidate_hash,
                    cache_key=run_cache_key,
                    status=ProposalRunStatus.RUNNING,
                    candidate_count=len(candidates),
                )
                session.add(run)
                await session.flush()
                for result in candidates:
                    if not result.provenance.record_ids:
                        continue
                    external_target = DialogueExternalTarget(
                        kind=ExternalTargetKind.CHUNK,
                        source_version_id=result.provenance.source_version_id,
                        source_segment_id=result.provenance.record_ids[0],
                        chunk_id=result.chunk_id,
                    )
                    session.add(external_target)
                    await session.flush()
                    for segment_id in result.provenance.record_ids:
                        session.add(
                            DialogueExternalEvidence(
                                external_target_id=external_target.id,
                                source_version_id=result.provenance.source_version_id,
                                source_segment_id=segment_id,
                                chunk_id=result.chunk_id,
                            )
                        )
                    pair_cache_key = classifier_cache_key(
                        ayin_version_id=context.version_id,
                        ayin_input_hash=ayin_hash,
                        external_version_id=result.provenance.source_version_id,
                        external_content_hash=result.chunk_content_hash,
                        provider=self.classifier.provider.name,
                        model=request.model,
                    )
                    candidate = DialogueProposalRunCandidate(
                        proposal_run_id=run.id,
                        external_target_id=external_target.id,
                        chunk_id=result.chunk_id,
                        rank=result.final_rank,
                        chunk_content_hash=result.chunk_content_hash,
                        classifier_cache_key=pair_cache_key,
                    )
                    session.add(candidate)
                    candidate_rows.append((candidate, result))

        failures = 0
        for candidate, result in candidate_rows:
            async with self.database.transaction() as session:
                prior_output = await session.scalar(
                    select(DialogueProposalRunCandidate.structured_output)
                    .where(
                        DialogueProposalRunCandidate.classifier_cache_key
                        == candidate.classifier_cache_key,
                        DialogueProposalRunCandidate.id != candidate.id,
                        DialogueProposalRunCandidate.structured_output.is_not(None),
                    )
                    .order_by(DialogueProposalRunCandidate.created_at)
                    .limit(1)
                )
            if prior_output is not None:
                output = DialogueClassification.model_validate(prior_output)
                cache_reused = True
            else:
                try:
                    output = await self.classifier.classify(
                        ayin_context=context.text,
                        external_context=result.text,
                        fixed_testability=context.fixed_testability,
                    )
                except Exception as exc:
                    failures += 1
                    async with self.database.transaction() as session:
                        stored = await session.get(
                            DialogueProposalRunCandidate, candidate.id
                        )
                        if stored is not None:
                            stored.error_code = type(exc).__name__
                    continue
            successes += 1
            async with self.database.transaction() as session:
                stored_candidate = await session.get(
                    DialogueProposalRunCandidate, candidate.id
                )
                if stored_candidate is None:
                    raise RuntimeError("dialogue proposal candidate disappeared")
                stored_candidate.structured_output = output.model_dump(mode="json")
                for classified in output.relations:
                    pins = ProvenancePins(
                        ayin_version_id=context.version_id,
                        ayin_passage_ids=[context.passage_id],
                        external_version_id=result.provenance.source_version_id,
                        external_segment_ids=result.provenance.record_ids,
                        proposal_run_id=run.id,
                    )
                    issues = self.validator.validate(
                        ValidationInput(
                            relation_type=classified.relation_type,
                            scope=classified.scope,
                            claim_testability=output.claim_testability,
                            explanation=classified.explanation,
                            provenance=pins,
                        )
                    )
                    priority = self._priority(
                        classified.review_priority,
                        classified.relation_type,
                        output.claim_testability,
                        issues,
                    )
                    proposal = DialogueProposal(
                        proposal_run_id=run.id,
                        candidate_id=stored_candidate.id,
                        ayin_target_id=run.ayin_target_id,
                        external_target_id=stored_candidate.external_target_id,
                        relation_type=classified.relation_type,
                        scope=classified.scope,
                        explanation=classified.explanation,
                        relation_confidence=classified.relation_confidence,
                        evidence_role=output.evidence_role,
                        claim_testability=output.claim_testability,
                        proposal_method=ProposalMethod.MODEL_CLASSIFIER,
                        review_priority=priority,
                        created_by=request.created_by,
                        validation_issues=[
                            item.model_dump(mode="json") for item in issues
                        ],
                    )
                    session.add(proposal)
                    await session.flush()
                    relation = DialogueRelation(
                        proposal_id=proposal.id,
                        relation_type=proposal.relation_type,
                        scope=proposal.scope,
                        explanation=proposal.explanation,
                        review_status=ReviewStatus.PROPOSED,
                        review_priority=priority,
                    )
                    session.add(relation)
                    await session.flush()
                    relation_ids.append(relation.id)
                    reasons = set(classified.review_reasons)
                    reasons.update(
                        issue.review_reason
                        for issue in issues
                        if issue.review_reason is not None
                    )
                    if classified.relation_confidence < 0.65:
                        reasons.add(ReviewReason.RELATION_AMBIGUITY)
                    for reason in reasons:
                        session.add(
                            DialogueReviewFlag(
                                relation_id=relation.id,
                                reason=reason,
                                priority=priority,
                                message=self._review_message(reason),
                            )
                        )

        async with self.database.transaction() as session:
            stored_run = await session.get(DialogueProposalRun, run.id)
            if stored_run is None:
                raise RuntimeError("dialogue proposal run disappeared")
            stored_run.success_count = successes
            stored_run.failure_count = failures
            stored_run.status = (
                ProposalRunStatus.SUCCEEDED
                if failures == 0
                else ProposalRunStatus.PARTIAL
                if successes
                else ProposalRunStatus.FAILED
            )
            stored_run.completed_at = datetime.now(UTC)
            stored_run.cache_hit = cache_reused
        return ProposalResult(
            proposal_run_id=run.id,
            retrieval_run_id=search.retrieval_run_id,
            relation_ids=relation_ids,
            candidate_count=len(candidates),
            success_count=successes,
            failure_count=failures,
            cache_hit=cache_reused,
        )

    async def counterevidence(
        self, request: CounterevidenceRequest
    ) -> list[SearchResult]:
        async with self.database.transaction() as session:
            context = await self._resolve_ayin_context(
                session, request.ayin_target_kind, request.ayin_identifier
            )
            chunking_run_id, embedding_model_id = await self._resolve_retrieval_pins(
                session, request.chunking_run_id, request.embedding_model_id
            )
        suffixes = (
            "نقد شواهد متناقض نتایج منفی توضیح جایگزین مورد مرزی",
            "competing explanation criticism contradictory evidence "
            "null result boundary case",
            "alternative mechanism counterexample methodological limitation",
        )
        batches: list[list[SearchResult]] = []
        for suffix in suffixes:
            response = await self.retrieval.search(
                f"{context.retrieval_text}\n{suffix}",
                request.language,
                chunking_run_id=chunking_run_id,
                embedding_model_id=embedding_model_id,
                lanes=[RetrievalLane.EXTERNAL],
                parameters={"lane_top_n": request.limit},
            )
            batches.append(response.results)
        return merge_counterevidence_results(batches, limit=request.limit)

    async def relations(
        self,
        *,
        relation_type: RelationType | None = None,
        concept_id: UUID | None = None,
    ) -> list[RelationRead]:
        async with self.database.transaction() as session:
            query = self._relation_query()
            if relation_type is not None:
                query = query.where(DialogueRelation.relation_type == relation_type)
            if concept_id is not None:
                query = query.join(
                    AyinConceptVersion,
                    AyinConceptVersion.id == DialogueAyinTarget.concept_version_id,
                ).where(AyinConceptVersion.concept_id == concept_id)
            rows = (
                await session.execute(query.order_by(DialogueRelation.created_at))
            ).all()
            return [await self._read(session, *row) for row in rows]

    async def relation(self, relation_id: UUID) -> RelationRead:
        async with self.database.transaction() as session:
            row = (
                await session.execute(
                    self._relation_query().where(DialogueRelation.id == relation_id)
                )
            ).one_or_none()
            if row is None:
                raise ValueError("dialogue relation not found")
            return await self._read(session, *row)

    async def review_queue(self) -> list[ReviewQueueRead]:
        async with self.database.transaction() as session:
            rows = (
                await session.execute(
                    self._relation_query()
                    .where(
                        DialogueRelation.review_status.in_(
                            [ReviewStatus.PROPOSED, ReviewStatus.IN_REVIEW]
                        )
                    )
                    .order_by(
                        DialogueRelation.review_priority.desc(),
                        DialogueRelation.created_at,
                    )
                )
            ).all()
            output: list[ReviewQueueRead] = []
            for row in rows:
                relation = await self._read(session, *row)
                reasons = list(
                    await session.scalars(
                        select(DialogueReviewFlag.reason).where(
                            DialogueReviewFlag.relation_id == relation.id,
                            DialogueReviewFlag.resolved_at.is_(None),
                        )
                    )
                )
                reasons.extend(
                    issue.review_reason
                    for issue in relation.validation_issues
                    if issue.review_reason is not None
                    and issue.review_reason not in reasons
                )
                output.append(ReviewQueueRead(relation=relation, reasons=reasons))
            return output

    async def review(self, relation_id: UUID, request: ReviewRequest) -> RelationRead:
        async with self.database.transaction() as session:
            relation = await session.get(DialogueRelation, relation_id)
            if relation is None:
                raise ValueError("dialogue relation not found")
            proposal = await session.get(DialogueProposal, relation.proposal_id)
            if proposal is None:
                raise RuntimeError("dialogue proposal disappeared")
            ayin = await session.get(DialogueAyinTarget, proposal.ayin_target_id)
            external = await session.get(
                DialogueExternalTarget, proposal.external_target_id
            )
            if ayin is None or external is None:
                raise RuntimeError("dialogue target disappeared")
            new_type = request.relation_type or relation.relation_type
            new_scope = request.scope or relation.scope
            new_explanation = request.explanation or relation.explanation
            new_status = review_status_for_action(request.action)
            ayin_passage_ids = list(
                await session.scalars(
                    select(DialogueAyinEvidence.passage_id).where(
                        DialogueAyinEvidence.ayin_target_id == ayin.id
                    )
                )
            )
            external_segment_ids = list(
                await session.scalars(
                    select(DialogueExternalEvidence.source_segment_id).where(
                        DialogueExternalEvidence.external_target_id == external.id
                    )
                )
            )
            issues = self.validator.validate(
                ValidationInput(
                    relation_type=new_type,
                    scope=new_scope,
                    claim_testability=proposal.claim_testability,
                    explanation=new_explanation,
                    provenance=ProvenancePins(
                        ayin_version_id=self._ayin_object_version_id(ayin),
                        ayin_passage_ids=ayin_passage_ids,
                        external_version_id=external.source_version_id,
                        external_segment_ids=external_segment_ids,
                        proposal_run_id=proposal.proposal_run_id,
                    ),
                    review_status=new_status,
                    proposal_method=proposal.proposal_method,
                )
            )
            if request.action is ReviewAction.APPROVE and any(
                item.severity == "ERROR" for item in issues
            ):
                raise ValueError("relation has critical epistemic validation errors")
            session.add(
                DialogueReviewDecision(
                    relation_id=relation.id,
                    action=request.action,
                    reviewer=request.reviewer,
                    previous_relation_type=relation.relation_type,
                    new_relation_type=new_type,
                    previous_scope=relation.scope,
                    new_scope=new_scope,
                    previous_explanation=relation.explanation,
                    new_explanation=new_explanation,
                    notes=request.notes,
                )
            )
            relation.relation_type = new_type
            relation.scope = new_scope
            relation.explanation = new_explanation
            relation.review_status = new_status
            relation.reviewer_notes = request.notes
            relation.reviewed_at = (
                None if new_status is ReviewStatus.IN_REVIEW else datetime.now(UTC)
            )
            if new_status in {
                ReviewStatus.APPROVED,
                ReviewStatus.REJECTED,
                ReviewStatus.SUPERSEDED,
            }:
                flags = await session.scalars(
                    select(DialogueReviewFlag).where(
                        DialogueReviewFlag.relation_id == relation.id,
                        DialogueReviewFlag.resolved_at.is_(None),
                    )
                )
                for flag in flags:
                    flag.resolved_at = datetime.now(UTC)
        return await self.relation(relation_id)

    async def validate(self) -> ValidationReport:
        items = await self.relations()
        issues = [issue for item in items for issue in item.validation_issues]
        return ValidationReport(
            valid=not any(item.severity == "ERROR" for item in issues),
            relation_count=len(items),
            issue_count=len(issues),
            issues=issues,
        )

    @staticmethod
    def _relation_query() -> Select[
        tuple[
            DialogueRelation,
            DialogueProposal,
            DialogueAyinTarget,
            DialogueExternalTarget,
        ]
    ]:
        return (
            select(
                DialogueRelation,
                DialogueProposal,
                DialogueAyinTarget,
                DialogueExternalTarget,
            )
            .join(DialogueProposal, DialogueProposal.id == DialogueRelation.proposal_id)
            .join(
                DialogueAyinTarget,
                DialogueAyinTarget.id == DialogueProposal.ayin_target_id,
            )
            .join(
                DialogueExternalTarget,
                DialogueExternalTarget.id == DialogueProposal.external_target_id,
            )
        )

    async def _read(
        self,
        session: AsyncSession,
        relation: DialogueRelation,
        proposal: DialogueProposal,
        ayin: DialogueAyinTarget,
        external: DialogueExternalTarget,
    ) -> RelationRead:
        ayin_passage_ids = list(
            await session.scalars(
                select(DialogueAyinEvidence.passage_id).where(
                    DialogueAyinEvidence.ayin_target_id == ayin.id
                )
            )
        )
        external_segment_ids = list(
            await session.scalars(
                select(DialogueExternalEvidence.source_segment_id).where(
                    DialogueExternalEvidence.external_target_id == external.id
                )
            )
        )
        proposal_run = (
            await session.get(DialogueProposalRun, proposal.proposal_run_id)
            if proposal.proposal_run_id is not None
            else None
        )
        issues = self.validator.validate(
            ValidationInput(
                relation_type=relation.relation_type,
                scope=relation.scope,
                claim_testability=proposal.claim_testability,
                explanation=relation.explanation,
                provenance=ProvenancePins(
                    ayin_version_id=self._ayin_object_version_id(ayin),
                    ayin_passage_ids=ayin_passage_ids,
                    external_version_id=external.source_version_id,
                    external_segment_ids=external_segment_ids,
                    proposal_run_id=proposal.proposal_run_id,
                ),
                review_status=relation.review_status,
                proposal_method=proposal.proposal_method,
            )
        )
        ayin_stale = await self._ayin_stale(session, ayin)
        external_stale = await self._external_stale(session, external)
        if ayin_stale:
            issues.append(
                ValidationIssue(
                    code="STALE_AYIN_VERSION",
                    message="A newer version of this Ayin object exists",
                    severity="WARNING",
                    review_reason=ReviewReason.STALE_AFTER_AYIN_REVISION,
                )
            )
        if external_stale:
            issues.append(
                ValidationIssue(
                    code="STALE_EXTERNAL_VERSION",
                    message="A newer version of this external source exists",
                    severity="WARNING",
                    review_reason=ReviewReason.STALE_AFTER_EXTERNAL_REVISION,
                )
            )
        return RelationRead(
            id=relation.id,
            proposal_id=proposal.id,
            ayin_target_id=ayin.id,
            ayin_target_kind=ayin.kind,
            ayin_version_id=self._ayin_object_version_id(ayin),
            ayin_canon_version_id=ayin.canon_version_id,
            ayin_passage_id=ayin.source_passage_id,
            ayin_passage_ids=ayin_passage_ids,
            external_target_id=external.id,
            external_target_kind=external.kind,
            external_version_id=external.source_version_id,
            external_segment_id=external.source_segment_id,
            external_segment_ids=external_segment_ids,
            external_chunk_id=external.chunk_id,
            original_relation_type=proposal.relation_type,
            original_scope=proposal.scope,
            original_explanation=proposal.explanation,
            relation_type=relation.relation_type,
            scope=relation.scope,
            explanation=relation.explanation,
            relation_confidence=proposal.relation_confidence,
            evidence_role=proposal.evidence_role,
            claim_testability=proposal.claim_testability,
            review_status=relation.review_status,
            review_priority=relation.review_priority,
            proposal_run_id=proposal.proposal_run_id,
            retrieval_run_id=(
                proposal_run.retrieval_run_id if proposal_run is not None else None
            ),
            classifier_provider=(
                proposal_run.provider if proposal_run is not None else None
            ),
            classifier_model=(proposal_run.model if proposal_run is not None else None),
            prompt_version=(
                proposal_run.prompt_version if proposal_run is not None else None
            ),
            classifier_version=(
                proposal_run.classifier_version if proposal_run is not None else None
            ),
            configuration_hash=(
                proposal_run.configuration_hash if proposal_run is not None else None
            ),
            created_by=proposal.created_by,
            created_at=relation.created_at,
            reviewed_at=relation.reviewed_at,
            reviewer_notes=relation.reviewer_notes,
            validation_issues=issues,
            ayin_stale=ayin_stale,
            external_stale=external_stale,
        )

    async def _resolve_ayin_context(
        self,
        session: AsyncSession,
        kind: AyinTargetKind,
        identifier: str,
    ) -> AyinContext:
        if kind is AyinTargetKind.CONCEPT_VERSION:
            concept = await session.scalar(
                select(AyinConcept).where(AyinConcept.stable_key == identifier)
            )
            if concept is None:
                raise ValueError("Ayin concept not found")
            version = await session.scalar(
                select(AyinConceptVersion)
                .where(AyinConceptVersion.concept_id == concept.id)
                .order_by(AyinConceptVersion.version_number.desc())
                .limit(1)
            )
            if version is None:
                raise ValueError("Ayin concept has no version")
            distinctions = list(
                await session.scalars(
                    select(AyinDistinctionVersion)
                    .join(
                        AyinDistinction,
                        AyinDistinction.id == AyinDistinctionVersion.distinction_id,
                    )
                    .where(
                        AyinDistinctionVersion.canon_version_id
                        == version.canon_version_id,
                        (AyinDistinction.left_concept_id == concept.id)
                        | (AyinDistinctionVersion.right_concept_id == concept.id),
                    )
                    .order_by(AyinDistinctionVersion.version_number.desc())
                )
            )
            distinction_text = "\n".join(
                f"Distinction: {item.explanation}" for item in distinctions
            )
            text = f"Concept {concept.stable_key}: {version.definition}"
            retrieval = "\n".join(
                value for value in (version.definition, distinction_text) if value
            )
            return AyinContext(
                kind,
                version.id,
                version.canon_version_id,
                version.source_passage_id,
                concept.id,
                f"{text}\n{distinction_text}".strip(),
                retrieval,
                ClaimTestability.CONCEPTUAL,
            )
        identity = self._identifier(identifier)
        if kind is AyinTargetKind.PRINCIPLE_VERSION:
            condition = (
                AyinPrinciple.id == identity
                if isinstance(identity, UUID)
                else AyinPrinciple.stable_key == identity
            )
            stable = await session.scalar(select(AyinPrinciple).where(condition))
            if stable is None:
                raise ValueError("Ayin principle not found")
            version = await session.scalar(
                select(AyinPrincipleVersion)
                .where(AyinPrincipleVersion.principle_id == stable.id)
                .order_by(AyinPrincipleVersion.version_number.desc())
                .limit(1)
            )
            if version is None:
                raise ValueError("Ayin principle has no version")
            return AyinContext(
                kind,
                version.id,
                version.canon_version_id,
                version.source_passage_id,
                stable.id,
                f"Principle {stable.stable_key}: {version.statement}",
                version.statement,
                _fixed_testability(version.discourse_type),
            )
        if kind is AyinTargetKind.DISTINCTION_VERSION:
            distinction_condition = (
                AyinDistinction.id == identity
                if isinstance(identity, UUID)
                else AyinDistinction.stable_key == identity
            )
            stable_distinction = await session.scalar(
                select(AyinDistinction).where(distinction_condition)
            )
            if stable_distinction is None:
                raise ValueError("Ayin distinction not found")
            version = await session.scalar(
                select(AyinDistinctionVersion)
                .where(AyinDistinctionVersion.distinction_id == stable_distinction.id)
                .order_by(AyinDistinctionVersion.version_number.desc())
                .limit(1)
            )
            if version is None:
                raise ValueError("Ayin distinction has no version")
            return AyinContext(
                kind,
                version.id,
                version.canon_version_id,
                version.source_passage_id,
                stable_distinction.id,
                f"Distinction {stable_distinction.stable_key}: {version.explanation}",
                version.explanation,
                _fixed_testability(version.discourse_type),
            )
        question_condition = (
            AyinOpenQuestion.id == identity
            if isinstance(identity, UUID)
            else AyinOpenQuestion.stable_key == identity
        )
        stable_question = await session.scalar(
            select(AyinOpenQuestion).where(question_condition)
        )
        if stable_question is None:
            raise ValueError("Ayin open question not found")
        version = await session.scalar(
            select(AyinOpenQuestionVersion)
            .where(AyinOpenQuestionVersion.open_question_id == stable_question.id)
            .order_by(AyinOpenQuestionVersion.version_number.desc())
            .limit(1)
        )
        if version is None:
            raise ValueError("Ayin open question has no version")
        return AyinContext(
            kind,
            version.id,
            version.canon_version_id,
            version.source_passage_id,
            stable_question.id,
            f"Open question {stable_question.stable_key}: "
            f"{version.question}\n{version.context}",
            f"{version.question}\n{version.context}",
            ClaimTestability.OPEN_QUESTION,
        )

    @staticmethod
    def _identifier(value: str) -> UUID | str:
        try:
            return UUID(value)
        except ValueError:
            return value

    @staticmethod
    async def _resolve_retrieval_pins(
        session: AsyncSession,
        chunking_run_id: UUID | None,
        embedding_model_id: UUID | None,
    ) -> tuple[UUID, UUID]:
        if chunking_run_id is None:
            chunking_run_id = await session.scalar(
                select(ChunkingRun.id)
                .where(ChunkingRun.status == BuildStatus.SUCCEEDED)
                .order_by(ChunkingRun.created_at.desc())
                .limit(1)
            )
        if embedding_model_id is None:
            embedding_model_id = await session.scalar(
                select(EmbeddingModel.id)
                .order_by(EmbeddingModel.created_at.desc())
                .limit(1)
            )
        if chunking_run_id is None or embedding_model_id is None:
            raise ValueError("successful chunking run and embedding model are required")
        return chunking_run_id, embedding_model_id

    @staticmethod
    async def _ensure_ayin_target(
        session: AsyncSession, context: AyinContext
    ) -> DialogueAyinTarget:
        if context.kind is AyinTargetKind.CONCEPT_VERSION:
            column = DialogueAyinTarget.concept_version_id
        elif context.kind is AyinTargetKind.PRINCIPLE_VERSION:
            column = DialogueAyinTarget.principle_version_id
        elif context.kind is AyinTargetKind.DISTINCTION_VERSION:
            column = DialogueAyinTarget.distinction_version_id
        else:
            column = DialogueAyinTarget.open_question_version_id
        target = await session.scalar(
            select(DialogueAyinTarget).where(column == context.version_id)
        )
        if target is not None:
            return target
        values: dict[str, UUID | None] = {
            "concept_version_id": None,
            "principle_version_id": None,
            "distinction_version_id": None,
            "open_question_version_id": None,
        }
        field = {
            AyinTargetKind.CONCEPT_VERSION: "concept_version_id",
            AyinTargetKind.PRINCIPLE_VERSION: "principle_version_id",
            AyinTargetKind.DISTINCTION_VERSION: "distinction_version_id",
            AyinTargetKind.OPEN_QUESTION_VERSION: "open_question_version_id",
        }[context.kind]
        values[field] = context.version_id
        target = DialogueAyinTarget(
            kind=context.kind,
            canon_version_id=context.canon_version_id,
            source_passage_id=context.passage_id,
            **values,
        )
        session.add(target)
        await session.flush()
        session.add(
            DialogueAyinEvidence(
                ayin_target_id=target.id,
                passage_id=context.passage_id,
                canon_version_id=context.canon_version_id,
            )
        )
        return target

    @staticmethod
    def _ayin_object_version_id(target: DialogueAyinTarget) -> UUID:
        """Return the exact concept/principle/distinction/question version."""

        for version_id in (
            target.concept_version_id,
            target.principle_version_id,
            target.distinction_version_id,
            target.open_question_version_id,
        ):
            if version_id is not None:
                return version_id
        raise RuntimeError("dialogue Ayin target has no typed object version")

    @staticmethod
    def _priority(
        proposed: ReviewPriority,
        relation_type: RelationType,
        testability: ClaimTestability,
        issues: list[ValidationIssue],
    ) -> ReviewPriority:
        if issues or testability is ClaimTestability.OPTIONAL_METAPHYSICAL:
            return ReviewPriority.CRITICAL
        if relation_type is RelationType.SUPPORTS_EMPIRICAL_SUBCLAIM:
            return ReviewPriority.HIGH
        return proposed

    @staticmethod
    def _review_message(reason: ReviewReason) -> str:
        return reason.value.replace("_", " ").lower()

    @staticmethod
    async def _ayin_stale(session: AsyncSession, target: DialogueAyinTarget) -> bool:
        if target.concept_version_id is not None:
            current = await session.get(AyinConceptVersion, target.concept_version_id)
            if current is None:
                return True
            count = await session.scalar(
                select(func.count())
                .select_from(AyinConceptVersion)
                .where(
                    AyinConceptVersion.concept_id == current.concept_id,
                    AyinConceptVersion.version_number > current.version_number,
                )
            )
            return bool(count)
        if target.principle_version_id is not None:
            current_principle = await session.get(
                AyinPrincipleVersion, target.principle_version_id
            )
            if current_principle is None:
                return True
            count = await session.scalar(
                select(func.count())
                .select_from(AyinPrincipleVersion)
                .where(
                    AyinPrincipleVersion.principle_id == current_principle.principle_id,
                    AyinPrincipleVersion.version_number
                    > current_principle.version_number,
                )
            )
            return bool(count)
        if target.distinction_version_id is not None:
            current_distinction = await session.get(
                AyinDistinctionVersion, target.distinction_version_id
            )
            if current_distinction is None:
                return True
            count = await session.scalar(
                select(func.count())
                .select_from(AyinDistinctionVersion)
                .where(
                    AyinDistinctionVersion.distinction_id
                    == current_distinction.distinction_id,
                    AyinDistinctionVersion.version_number
                    > current_distinction.version_number,
                )
            )
            return bool(count)
        if target.open_question_version_id is not None:
            current_question = await session.get(
                AyinOpenQuestionVersion, target.open_question_version_id
            )
            if current_question is None:
                return True
            count = await session.scalar(
                select(func.count())
                .select_from(AyinOpenQuestionVersion)
                .where(
                    AyinOpenQuestionVersion.open_question_id
                    == current_question.open_question_id,
                    AyinOpenQuestionVersion.version_number
                    > current_question.version_number,
                )
            )
            return bool(count)
        return True

    @staticmethod
    async def _external_stale(
        session: AsyncSession, target: DialogueExternalTarget
    ) -> bool:
        version = await session.get(SourceVersion, target.source_version_id)
        if version is None:
            return True
        newer = await session.scalar(
            select(func.count())
            .select_from(SourceVersion)
            .where(
                SourceVersion.source_id == version.source_id,
                SourceVersion.created_at > version.created_at,
            )
        )
        return bool(newer)
