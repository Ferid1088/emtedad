"""Material-gap detection and fill for brief-driven productions.

A production targets ``target_duration_minutes``; the rough sufficiency check
is ``units >= duration * units_per_video_minute`` over the topic's grounding
units. When the gap is real and web research is enabled, ``fill_gap``
researches the brief's question, thesis, and recorded knowledge gaps, ingests
the discovered pages as WEBPAGE sources assigned to the brief's channel, and
optionally drives them through the synchronous processing pipeline so the new
units can be linked back to the topic candidate immediately.
"""

import logging
import math
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.briefs.models import ContentBrief
from app.db.session import Database
from app.editorial_channels.domain import StrategyStatus
from app.editorial_channels.models import ChannelStrategyVersion, EditorialChannel
from app.knowledge.models import SourceVersion
from app.knowledge.processing import SourceProcessingService
from app.knowledge.units.models import KnowledgeUnit
from app.ops.settings.service import StudioSettingsService
from app.topics.models import TopicCandidate, TopicCandidateUnit
from app.web_research.domain import IngestedWebSource, WebResearchReport
from app.web_research.service import WebResearchService

logger = logging.getLogger(__name__)

_MAX_SEARCH_ROUNDS = 3
_QUERIES_PER_ROUND = 3


@dataclass(frozen=True)
class PlannedQuery:
    """One labeled search approach (§28): every round covers more than
    confirming phrasing — falsification and gap-filling are explicit."""

    kind: str
    text: str


@dataclass
class GapAssessment:
    """Whether the topic's grounding material fits the target duration."""

    units_available: int
    units_required: int
    target_minutes: float

    @property
    def has_gap(self) -> bool:
        return self.units_available < self.units_required

    @property
    def missing(self) -> int:
        return max(0, self.units_required - self.units_available)


@dataclass
class GapFillOutcome:
    assessment: GapAssessment
    ran: bool = False
    skipped_reason: str = ""
    rounds_completed: int = 0
    reports: list[WebResearchReport] = field(default_factory=list)
    ingested: list[IngestedWebSource] = field(default_factory=list)
    processed_source_ids: list[str] = field(default_factory=list)
    linked_units: int = 0
    remaining_gaps: list[str] = field(default_factory=list)
    error: str = ""


class GapFillService:
    """Assess and fill material gaps for one ContentBrief."""

    def __init__(
        self,
        database: Database,
        *,
        research: WebResearchService | None = None,
    ) -> None:
        self.database = database
        self.research = research or WebResearchService(database)

    async def assess(self, brief_id: UUID) -> GapAssessment:
        settings = await StudioSettingsService(self.database).effective()
        per_minute = float(settings.get("units_per_video_minute") or 1.5)
        async with self.database.transaction() as session:
            brief = await session.get(ContentBrief, brief_id)
            if brief is None:
                raise LookupError(f"Unknown content brief {brief_id}")
            count = int(
                await session.scalar(
                    select(func.count(TopicCandidateUnit.knowledge_unit_id)).where(
                        TopicCandidateUnit.topic_candidate_id
                        == brief.topic_candidate_id
                    )
                )
                or 0
            )
        return GapAssessment(
            units_available=count,
            units_required=math.ceil(brief.target_duration_minutes * per_minute),
            target_minutes=brief.target_duration_minutes,
        )

    async def fill_gap(
        self,
        brief_id: UUID,
        *,
        process_inline: bool = True,
        trigger: str = "gap_fill",
    ) -> GapFillOutcome:
        """Research the web when grounding material is below target.

        Auto-run happens only when the owner enabled web research; without the
        toggle the outcome records ``web_research_disabled`` so the UI can show
        a hint instead of failing.
        """

        assessment = await self.assess(brief_id)
        outcome = GapFillOutcome(assessment=assessment)
        if not assessment.has_gap:
            outcome.skipped_reason = "material_sufficient"
            return outcome
        if not await self.research.enabled():
            outcome.skipped_reason = "web_research_disabled"
            return outcome

        async with self.database.transaction() as session:
            brief = await session.get(ContentBrief, brief_id)
            if brief is None:
                raise LookupError(f"Unknown content brief {brief_id}")
            candidate = await session.get(TopicCandidate, brief.topic_candidate_id)
            channel_id = brief.editorial_channel_id
            rounds = self._plan_rounds(brief, candidate)
            language = await self._channel_language(session, channel_id)

        outcome.ran = True
        # §33 coverage loop: at most 3 rounds; each round re-assesses the
        # material gap and stops early when the grounding is sufficient.
        # Rounds past the first only fire while a gap remains — targeted
        # follow-ups, not blind repetition.
        for round_number, planned in enumerate(rounds, start=1):
            new_source_ids: list[UUID] = []
            for query in planned:
                result = await self.research.research_and_ingest(
                    query.text,
                    context=brief.thesis or "",
                    channel_ids=(channel_id,),
                    language=language,
                    schedule=not process_inline,
                    content_brief_id=brief_id,
                    trigger=trigger,
                    round_number=round_number,
                    query_kind=query.kind,
                )
                if result.report is not None:
                    outcome.reports.append(result.report)
                outcome.ingested.extend(result.ingested)
                new_source_ids.extend(result.new_source_ids)
                if result.error and not outcome.error:
                    outcome.error = result.error
            outcome.rounds_completed = round_number

            if process_inline and new_source_ids:
                processor = SourceProcessingService(self.database)
                for source_id in new_source_ids:
                    try:
                        state = await processor.process_source(source_id)
                        outcome.processed_source_ids.append(str(source_id))
                        logger.info(
                            "web_research.processed",
                            extra={
                                "source_id": str(source_id),
                                "status": state.status.value,
                            },
                        )
                    except Exception:
                        logger.exception(
                            "web_research.process_failed",
                            extra={"source_id": str(source_id)},
                        )

            if outcome.processed_source_ids:
                outcome.linked_units += await self._link_units(
                    brief.topic_candidate_id,
                    [UUID(raw) for raw in outcome.processed_source_ids],
                )

            assessment = await self.assess(brief_id)
            outcome.assessment = assessment
            if not assessment.has_gap:
                break

        # §33: gaps that survive the round cap are persisted, not hidden.
        if outcome.assessment.has_gap:
            outcome.remaining_gaps = [
                f"material gap persists after {outcome.rounds_completed} "
                f"search round(s): {outcome.assessment.units_available}/"
                f"{outcome.assessment.units_required} grounding units"
            ]
        return outcome

    async def _link_units(
        self, candidate_id: UUID | None, source_ids: list[UUID]
    ) -> int:
        """Ground the candidate on units from the newly processed sources."""

        if candidate_id is None or not source_ids:
            return 0
        async with self.database.transaction() as session:
            unit_ids = list(
                (
                    await session.scalars(
                        select(KnowledgeUnit.id)
                        .join(
                            SourceVersion,
                            SourceVersion.id == KnowledgeUnit.source_version_id,
                        )
                        .where(SourceVersion.source_id.in_(source_ids))
                    )
                ).all()
            )
            existing = set(
                (
                    await session.scalars(
                        select(TopicCandidateUnit.knowledge_unit_id).where(
                            TopicCandidateUnit.topic_candidate_id == candidate_id
                        )
                    )
                ).all()
            )
            linked = 0
            for unit_id in unit_ids:
                if unit_id in existing:
                    continue
                session.add(
                    TopicCandidateUnit(
                        topic_candidate_id=candidate_id,
                        knowledge_unit_id=unit_id,
                    )
                )
                linked += 1
            return linked

    @staticmethod
    def _plan_rounds(
        brief: ContentBrief, candidate: TopicCandidate | None
    ) -> list[list[PlannedQuery]]:
        """§28/29: per-round query plans covering distinct approaches.

        Round 1: broad question, thesis verification (support AND
        counterevidence in one query), first knowledge gap.
        Round 2: falsification phrasing, alternative explanations, next gap.
        Round 3: recent-evidence check plus any remaining gaps.
        No round is fired unless a material gap still exists (caller).
        """

        provenance = (candidate.provenance_json or {}) if candidate else {}
        raw_gaps = provenance.get("knowledge_gaps") or []
        gaps = [
            str(gap) for gap in (raw_gaps if isinstance(raw_gaps, list) else [raw_gaps])
        ]
        round1 = [PlannedQuery("broad_discovery", brief.question)]
        if brief.thesis:
            round1.append(
                PlannedQuery(
                    "verification",
                    f"Evidence and counterevidence: {brief.thesis}",
                )
            )
        if gaps:
            round1.append(PlannedQuery("knowledge_gap", gaps[0]))

        round2: list[PlannedQuery] = []
        if brief.thesis:
            round2.append(
                PlannedQuery(
                    "falsification",
                    f"Criticism, limitations, or evidence against: {brief.thesis}",
                )
            )
            round2.append(
                PlannedQuery(
                    "alternative_explanation",
                    f"Alternative explanations for: {brief.question}",
                )
            )
        if len(gaps) > 1:
            round2.append(PlannedQuery("knowledge_gap", gaps[1]))

        round3 = [
            PlannedQuery(
                "recent_evidence",
                f"Latest research and recent findings: {brief.question}",
            ),
            # Review-level evidence: for empirical questions a systematic
            # review beats another opinion page. Non-leading phrasing.
            PlannedQuery(
                "academic_evidence",
                f"Peer-reviewed studies and systematic reviews on: {brief.question}",
            ),
        ]
        round3.extend(PlannedQuery("knowledge_gap", gap) for gap in gaps[2:])

        rounds = [
            round_[:_QUERIES_PER_ROUND] for round_ in (round1, round2, round3) if round_
        ]
        return rounds[:_MAX_SEARCH_ROUNDS]

    @staticmethod
    async def _channel_language(session: AsyncSession, channel_id: UUID) -> str:
        channel = await session.get(EditorialChannel, channel_id)
        if channel is None:
            return "en"
        strategy = await session.scalar(
            select(ChannelStrategyVersion)
            .where(ChannelStrategyVersion.editorial_channel_id == channel.id)
            .where(ChannelStrategyVersion.status == StrategyStatus.ACTIVE)
            .limit(1)
        )
        return strategy.editorial_language if strategy else "en"
