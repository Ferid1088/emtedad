"""Persist resolver candidates without silently merging ambiguous entities."""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.knowledge.domain import (
    EntityType,
    IdentifierScheme,
    KnowledgeReviewStatus,
    ResolutionStatus,
    ReviewReason,
)
from app.knowledge.models import (
    ExternalIdentifier,
    Mention,
    ResolutionCandidate,
    ReviewFlag,
)
from app.knowledge.normalization import normalize_identifier
from app.knowledge.resolution import (
    ProviderCandidate,
    ReferenceResolver,
    candidate_score,
)
from app.ops.logging import get_logger


@dataclass(frozen=True, slots=True)
class ResolutionSummary:
    processed_mentions: int
    candidate_count: int
    provider_failures: int
    resolved: int
    review: int
    unresolved: int


class ResolutionService:
    def __init__(
        self,
        database: Database,
        resolvers: list[ReferenceResolver],
        *,
        resolve_threshold: float = 96,
        review_threshold: float = 72,
        ambiguity_margin: float = 4,
    ) -> None:
        self._database = database
        self._resolvers = resolvers
        self._resolve_threshold = resolve_threshold
        self._review_threshold = review_threshold
        self._ambiguity_margin = ambiguity_margin
        self._log = get_logger(__name__)

    async def resolve_pending(
        self, source_id: UUID | None = None, *, limit: int | None = None
    ) -> ResolutionSummary:
        async with self._database.transaction() as session:
            statement = select(Mention).where(
                Mention.resolution_status.in_(
                    [ResolutionStatus.REVIEW, ResolutionStatus.UNRESOLVED]
                )
            )
            if source_id is not None:
                from app.knowledge.models import SourceVersion

                statement = statement.join(
                    SourceVersion, SourceVersion.id == Mention.source_version_id
                ).where(SourceVersion.source_id == source_id)
            statement = statement.order_by(Mention.created_at)
            if limit is not None:
                statement = statement.limit(limit)
            mentions = list(await session.scalars(statement))

        candidate_total = 0
        provider_failures = 0
        counts = {status: 0 for status in ResolutionStatus}
        for mention in mentions:
            candidates = []
            for resolver in self._resolvers:
                started = time.monotonic()
                try:
                    provider_candidates = await resolver.search(
                        mention.surface_text, mention.entity_type
                    )
                    candidates.extend(provider_candidates)
                    self._log.info(
                        "knowledge_resolver_completed",
                        source_id=str(source_id) if source_id else None,
                        mention_id=str(mention.id),
                        resolver=resolver.provider.value,
                        candidate_count=len(provider_candidates),
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                    )
                except Exception as exc:
                    provider_failures += 1
                    self._log.error(
                        "knowledge_resolver_failed",
                        source_id=str(source_id) if source_id else None,
                        mention_id=str(mention.id),
                        resolver=resolver.provider.value,
                        candidate_count=0,
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                        error_code=type(exc).__name__,
                    )
            scored = sorted(
                (
                    (candidate_score(mention.surface_text, item), item)
                    for item in candidates
                ),
                key=lambda pair: pair[0],
                reverse=True,
            )
            candidate_total += len(scored)
            status = self._status(scored)
            counts[status] += 1
            async with self._database.transaction() as session:
                stored = await session.get(Mention, mention.id)
                if stored is None:
                    continue
                stored.resolution_status = status
                for score, item in scored:
                    existing = await session.scalar(
                        select(ResolutionCandidate.id).where(
                            ResolutionCandidate.mention_id == stored.id,
                            ResolutionCandidate.provider == item.provider,
                            ResolutionCandidate.candidate_key == item.candidate_key,
                        )
                    )
                    if existing is None:
                        session.add(
                            ResolutionCandidate(
                                mention_id=stored.id,
                                provider=item.provider,
                                candidate_key=item.candidate_key,
                                candidate_type=item.entity_type,
                                candidate_name=item.name,
                                candidate_identifiers=item.identifiers,
                                candidate_url=item.url,
                                score=score,
                                metadata_json=item.metadata,
                                status=status,
                            )
                        )
                if status is ResolutionStatus.RESOLVED and scored:
                    await self._apply_identifiers(session, stored, scored[0][1])
                if status is not ResolutionStatus.RESOLVED:
                    await self._ensure_review(session, stored, status, scored)
        return ResolutionSummary(
            processed_mentions=len(mentions),
            candidate_count=candidate_total,
            provider_failures=provider_failures,
            resolved=counts[ResolutionStatus.RESOLVED],
            review=counts[ResolutionStatus.REVIEW],
            unresolved=counts[ResolutionStatus.UNRESOLVED],
        )

    @staticmethod
    async def _apply_identifiers(
        session: AsyncSession, mention: Mention, candidate: ProviderCandidate
    ) -> None:
        target_field = {
            EntityType.PERSON: "person_id",
            EntityType.WORK: "work_id",
            EntityType.ORGANIZATION: "organization_id",
            EntityType.CONCEPT: "concept_id",
        }[mention.entity_type]
        target_id = getattr(mention, target_field)
        if target_id is None:
            return
        for raw_scheme, value in candidate.identifiers.items():
            try:
                scheme = IdentifierScheme(raw_scheme)
            except ValueError:
                continue
            normalized = normalize_identifier(value)
            existing = await session.scalar(
                select(ExternalIdentifier).where(
                    ExternalIdentifier.scheme == scheme,
                    ExternalIdentifier.normalized_value == normalized,
                )
            )
            if existing is not None:
                existing_target = getattr(existing, target_field)
                if existing_target is not None:
                    setattr(mention, target_field, existing_target)
                continue
            values = {
                "person_id": None,
                "work_id": None,
                "organization_id": None,
                "concept_id": None,
            }
            values[target_field] = target_id
            session.add(
                ExternalIdentifier(
                    scheme=scheme,
                    value=value,
                    normalized_value=normalized,
                    source_url=candidate.url,
                    **values,
                )
            )

    def _status(
        self, scored: Sequence[tuple[float, ProviderCandidate]]
    ) -> ResolutionStatus:
        if not scored:
            return ResolutionStatus.UNRESOLVED
        best = scored[0][0]
        second = scored[1][0] if len(scored) > 1 else 0
        if best >= self._resolve_threshold and best - second >= self._ambiguity_margin:
            return ResolutionStatus.RESOLVED
        if best >= self._review_threshold:
            return ResolutionStatus.REVIEW
        return ResolutionStatus.UNRESOLVED

    async def _ensure_review(
        self,
        session: AsyncSession,
        mention: Mention,
        status: ResolutionStatus,
        scored: Sequence[tuple[float, ProviderCandidate]],
    ) -> None:
        reason = (
            ReviewReason.MULTIPLE_HIGH_SCORING_MATCHES
            if len(scored) > 1 and scored[0][0] - scored[1][0] < self._ambiguity_margin
            else ReviewReason.UNRESOLVED_REFERENCE
        )
        existing = await session.scalar(
            select(ReviewFlag.id).where(
                ReviewFlag.mention_id == mention.id,
                ReviewFlag.reason == reason,
                ReviewFlag.status == KnowledgeReviewStatus.OPEN,
            )
        )
        if existing is None:
            session.add(
                ReviewFlag(
                    source_version_id=mention.source_version_id,
                    mention_id=mention.id,
                    reason=reason,
                    status=KnowledgeReviewStatus.OPEN,
                    message=f"Reference resolution remains {status.value}.",
                )
            )
