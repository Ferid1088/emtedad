"""Integration coverage for the dynamic topic engine."""

import hashlib
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import selectinload

from alembic import command
from app.briefs.domain import BriefStatus
from app.briefs.models import ContentBrief
from app.briefs.service import BriefInput, BriefService, validate_ready
from app.content_engine.domain import (
    DraftStatus,
    FindingSeverity,
    PlanStatus,
    ProductionStage,
)
from app.content_engine.review import ScriptService
from app.content_engine.schemas import (
    ArgumentPlanOutput,
    ArgumentSectionProposal,
    NarrativePlanOutput,
    NarrativeSectionProposal,
)
from app.content_engine.service import (
    ContentEngineService,
    GateBlockedError,
)
from app.db.session import Database
from app.editorial_channels.domain import ChannelResourceRole, StrategyStatus
from app.editorial_channels.models import (
    ChannelStrategyVersion,
    EditorialChannel,
)
from app.editorial_channels.service import EditorialChannelService
from app.knowledge.domain import IngestionStatus, SourceType
from app.knowledge.models import Source, SourceSegment, SourceVersion
from app.knowledge.structure.domain import StructureNodeType
from app.knowledge.structure.schemas import (
    SourceStructureOutput,
    StructureNodeProposal,
)
from app.knowledge.structure.service import SourceStructureService
from app.knowledge.units.domain import KnowledgeUnitType
from app.knowledge.units.schemas import (
    UnitMetadataBatch,
    UnitMetadataProposal,
)
from app.knowledge.units.service import KnowledgeUnitService
from app.lecture.domain import (
    MasterOriginType,
    MasterStatus,
    SectionRole,
)
from app.lecture.generic_service import GenericMasterService
from app.lecture.models import (
    LectureCitation,
    LectureClaim,
    LectureClaimEvidence,
    LectureSection,
)
from app.production.service import ProductionService
from app.research.domain import (
    EvidenceSelectionRole,
    PackageStatus,
    ResearchPlanStatus,
)
from app.research.generic import GenericResearchService
from app.research.models import EvidenceMatrixItem
from app.topics.domain import TopicStatus
from app.topics.models import TopicCandidate
from app.topics.schemas import TopicCandidateProposal, TopicMiningBatch
from app.topics.service import TopicService

pytestmark = pytest.mark.integration


def _database_url() -> str:
    try:
        return os.environ["EMTEDAD_DATABASE_URL"]
    except KeyError as exc:
        raise RuntimeError(
            "EMTEDAD_DATABASE_URL is required for integration tests"
        ) from exc


@pytest.fixture
def migrated_database_url() -> Iterator[str]:
    base_url = _database_url()
    name = f"emtedad_test_{uuid4().hex}"
    admin_url = (
        make_url(base_url.replace("postgresql+psycopg://", "postgresql://", 1))
        .set(database="postgres")
        .render_as_string(hide_password=False)
    )
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = make_url(base_url).set(database=name).render_as_string(hide_password=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        yield url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


class _Provider:
    """Fake provider covering structure, unit metadata, and topic mining."""

    name = "fixture"

    async def extract(self, request):
        import json

        if request.task == "source_structure_local":
            return SourceStructureOutput(
                nodes=[
                    StructureNodeProposal(
                        temp_id="t1",
                        node_type=StructureNodeType.TOPIC,
                        title="Decision making",
                        summary="How decisions are made",
                        start_segment_sequence=1,
                        end_segment_sequence=10,
                        ordinal=1,
                    ),
                    StructureNodeProposal(
                        temp_id="s1",
                        parent_temp_id="t1",
                        node_type=StructureNodeType.STORY,
                        title="Sunk cost story",
                        summary="A story about sunk cost",
                        start_segment_sequence=3,
                        end_segment_sequence=8,
                        ordinal=1,
                    ),
                ]
            )
        if request.task == "knowledge_unit_metadata":
            nodes = json.loads(request.input_text)
            return UnitMetadataBatch(
                units=[
                    UnitMetadataProposal(
                        node_id=item["node_id"],
                        unit_type=(
                            KnowledgeUnitType.STORY
                            if item["node_type"] == "STORY"
                            else KnowledgeUnitType.EXPLANATION
                        ),
                        title=item["title"],
                        summary=item["summary"],
                    )
                    for item in nodes
                ]
            )
        if request.task == "argument_plan":
            return ArgumentPlanOutput(
                sections=[
                    ArgumentSectionProposal(
                        ordinal=1,
                        role="CLAIM",
                        purpose="State the thesis",
                        evidence_item_refs=["e1"],
                        story_unit_refs=["s1"],
                        must_include=["thesis"],
                    )
                ]
            )
        if request.task == "script_draft":
            from app.content_engine.review import ScriptDraftOutput

            return ScriptDraftOutput(
                text="Once upon a sunk cost. " * 30,
                estimated_duration_seconds=120,
            )
        if request.task == "script_review":
            from app.content_engine.review import (
                FindingProposal,
                ReviewFindingsOutput,
            )

            return ReviewFindingsOutput(
                findings=[
                    FindingProposal(
                        location="opening",
                        code="OVERCLAIM",
                        severity=FindingSeverity.BLOCKER,
                        explanation="Draft overclaims causal certainty.",
                        correction_constraint="Hedge the causal claim.",
                    )
                ]
            )
        if request.task == "script_revision":
            from app.content_engine.review import RevisionOutput

            return RevisionOutput(
                text="Perhaps we keep losing choices because of sunk cost. " * 30
            )
        if request.task == "narrative_plan":
            return NarrativePlanOutput(
                sections=[
                    NarrativeSectionProposal(
                        ordinal=1,
                        narrative_role="COLD_OPEN",
                        purpose="Hook with the story",
                        target_seconds=90,
                        argument_section_refs=["a1"],
                        story_unit_refs=["s1"],
                        opening_method="scene",
                    )
                ]
            )
        if request.task == "topic_mining":
            return TopicMiningBatch(
                topics=[
                    TopicCandidateProposal(
                        title="Why we keep bad investments",
                        video_question="Why do we stick with losing choices?",
                        tentative_thesis="Loss aversion keeps us locked in.",
                        angle="Everyday decision traps",
                        supporting_unit_refs=["u1"],
                        supporting_concepts=["Sunk cost fallacy"],
                        knowledge_gaps=["Cross-cultural evidence missing"],
                        channel_fit_reason="Core decision content",
                        curiosity=0.8,
                        emotional_relevance=0.7,
                        practical_value=0.9,
                        channel_fit=0.9,
                    ),
                    TopicCandidateProposal(
                        title="Speculative topic",
                        video_question="Are memory palaces magic?",
                        tentative_thesis="Unclear.",
                        angle="Curiosity hook",
                        supporting_unit_refs=["u99"],
                        supporting_concepts=[],
                        knowledge_gaps=["No source coverage"],
                        curiosity=0.95,
                    ),
                ]
            )
        raise AssertionError(f"unexpected task: {request.task}")


async def _build_source_with_units(database: Database) -> Source:
    async with database.transaction() as session:
        source = Source(
            source_type=SourceType.YOUTUBE_VIDEO,
            platform="youtube",
            external_id=f"topic{uuid4().hex[:8]}",
            canonical_url="https://example.test/topic-video",
            title="Topic fixture",
            language="en",
            ingestion_status=IngestionStatus.INGESTED,
        )
        session.add(source)
        await session.flush()
        version = SourceVersion(
            source_id=source.id,
            content_hash=hashlib.sha256(b"content").hexdigest(),
            transcript_hash=hashlib.sha256(b"transcript").hexdigest(),
            acquisition_tool="fixture",
            acquisition_version="0",
            normalization_version="0",
            acquired_at=datetime.now(UTC),
        )
        session.add(version)
        await session.flush()
        for index in range(1, 11):
            session.add(
                SourceSegment(
                    source_version_id=version.id,
                    sequence=index,
                    start_seconds=Decimal(index * 10),
                    end_seconds=Decimal(index * 10 + 9),
                    raw_text=f"segment {index} about sunk cost decisions",
                    normalized_text=f"segment {index} about sunk cost decisions",
                    language="en",
                    content_hash=hashlib.sha256(f"seg{index}".encode()).hexdigest(),
                )
            )
        await session.flush()
        return source


@pytest.mark.asyncio
async def test_topic_mining_scores_and_status(migrated_database_url: str) -> None:
    database = Database(migrated_database_url)
    try:
        channel_service = EditorialChannelService(database)
        await channel_service.seed_channels()
        channel = await channel_service.get_channel("emtedad")

        source = await _build_source_with_units(database)
        provider = _Provider()
        await SourceStructureService(database, provider=provider).process_source(
            source.id
        )
        await KnowledgeUnitService(database, provider=provider).extract_for_source(
            source.id
        )
        await channel_service.assign_resource(
            channel.id, source.id, role=ChannelResourceRole.PRIMARY
        )

        topics = TopicService(database, provider=provider)
        candidates = await topics.mine("emtedad")
        assert len(candidates) == 2

        grounded = next(c for c in candidates if "bad investments" in c.title)
        assert grounded.status == TopicStatus.CANDIDATE
        assert grounded.knowledge_coverage_score == 1.0
        assert grounded.novelty_score == 1.0
        assert grounded.strategy_version_id is not None
        assert 0 <= grounded.total_score <= 1

        ungrounded = next(c for c in candidates if "Speculative" in c.title)
        assert ungrounded.status == TopicStatus.NEEDS_RESEARCH
        assert ungrounded.knowledge_coverage_score == 0.0

        async with database.transaction() as session:
            stored = list(
                (
                    await session.scalars(
                        select(TopicCandidate).options(
                            selectinload(TopicCandidate.units),
                            selectinload(TopicCandidate.concepts),
                        )
                    )
                ).all()
            )
        assert len(stored) == 2
        grounded_stored = next(c for c in stored if "bad investments" in c.title)
        assert len(grounded_stored.units) == 1
        assert len(grounded_stored.concepts) == 0  # no concepts mapped in fixture

        shortlisted = await topics.set_status(grounded.id, TopicStatus.SHORTLISTED)
        assert shortlisted.status == TopicStatus.SHORTLISTED
        with pytest.raises(ValueError):
            await topics.set_status(grounded.id, TopicStatus.PUBLISHED)

        # Phase 9: a complete ContentBrief pins channel and strategy.
        briefs = BriefService(database)
        brief = await briefs.create_for_candidate(
            grounded.id,
            BriefInput(
                question="Why do we stick with losing choices?",
                thesis="Loss aversion keeps us locked in.",
                target_duration_minutes=12,
            ),
        )
        assert brief.status == BriefStatus.DRAFT
        assert brief.editorial_channel_id == channel.id
        ready = await briefs.mark_ready(brief.id)
        assert ready.status == BriefStatus.READY
        assert validate_ready(ready) == []

        # Phase 11: brief-origin research without lesson or spine.
        research = GenericResearchService(database)
        plan = await research.create_plan_for_brief(ready.id)
        assert plan.content_brief_id == ready.id
        assert plan.ayin_spine_id is None and plan.lesson_id is None
        assert plan.status == ResearchPlanStatus.READY

        matrix = await research.build_evidence_matrix(ready.id)
        assert matrix.version_number == 1
        async with database.transaction() as session:
            items = list(
                await session.scalars(
                    select(EvidenceMatrixItem).where(
                        EvidenceMatrixItem.evidence_matrix_id == matrix.id
                    )
                )
            )
        assert len(items) == 1
        assert items[0].role == EvidenceSelectionRole.CASE_STUDY
        assert items[0].claim_text

        package = await research.freeze_package(plan.id)
        assert package.content_brief_id == ready.id
        assert package.canon_version_id is None
        assert package.ayin_spine_id is None
        assert package.lesson_id is None
        assert package.status == PackageStatus.FROZEN
        snapshot = package.retrieval_snapshot
        assert snapshot["selected_unit_ids"]
        assert snapshot["claims"]
        assert snapshot["source_provenance"]
        assert snapshot["evidence_matrix_id"] == str(matrix.id)

        # Phase 12/13: gated argument + narrative plans.
        engine = ContentEngineService(database, provider=provider)
        argument = await engine.build_argument(ready.id)
        assert argument.status == PlanStatus.READY
        assert argument.evidence_matrix_id == matrix.id
        assert argument.sections[0].evidence_item_ids  # refs resolved
        narrative = await engine.build_narrative(ready.id)
        assert narrative.status == PlanStatus.READY
        assert narrative.argument_plan_id == argument.id
        assert narrative.sections[0].argument_section_ids
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_engine_gates(migrated_database_url: str) -> None:
    """§29.5: no argument without matrix, no narrative without argument."""

    database = Database(migrated_database_url)
    try:
        channel_service = EditorialChannelService(database)
        await channel_service.seed_channels()
        channel = await channel_service.get_channel("emtedad")
        source = await _build_source_with_units(database)
        provider = _Provider()
        await channel_service.assign_resource(
            channel.id, source.id, role=ChannelResourceRole.PRIMARY
        )
        await SourceStructureService(database, provider=provider).process_source(
            source.id
        )
        await KnowledgeUnitService(database, provider=provider).extract_for_source(
            source.id
        )
        candidates = await TopicService(database, provider=provider).mine("emtedad")
        candidate = candidates[0]
        briefs = BriefService(database)
        brief = await briefs.create_for_candidate(
            candidate.id,
            BriefInput(question="Q?", thesis="T.", target_duration_minutes=10),
        )
        await briefs.mark_ready(brief.id)

        engine = ContentEngineService(database, provider=provider)
        # No evidence matrix yet.
        with pytest.raises(GateBlockedError):
            await engine.build_argument(brief.id)
        await GenericResearchService(database).build_evidence_matrix(brief.id)
        # Matrix is DRAFT, not READY — still gated.
        with pytest.raises(GateBlockedError):
            await engine.build_argument(brief.id)
        # Freeze the matrix via package freeze, which sets it FROZEN.
        research = GenericResearchService(database)
        plan = await research.create_plan_for_brief(brief.id)
        await research.freeze_package(plan.id)
        argument = await engine.build_argument(brief.id)
        assert argument.status == PlanStatus.READY
        narrative = await engine.build_narrative(brief.id)
        assert narrative.status == PlanStatus.READY

        # Narrative gate: a second brief with no READY argument cannot narrate.
        brief2 = await briefs.create_for_candidate(
            candidates[1].id,
            BriefInput(question="Q2?", thesis="T2.", target_duration_minutes=5),
        )
        await briefs.mark_ready(brief2.id)
        with pytest.raises(GateBlockedError):
            await engine.build_narrative(brief2.id)

        # Phase 14/15: script gate, critics, approval gate, revision.
        scripts = ScriptService(database, provider=provider)
        masters = GenericMasterService(database)
        with pytest.raises(GateBlockedError):
            await scripts.build_script(brief2.id)  # no narrative yet
        with pytest.raises(GateBlockedError):
            await scripts.build_script(brief.id)  # no master yet
        await masters.build_from_content_brief(brief.id)
        draft = await scripts.build_script(brief.id, language="en")
        assert draft.status == DraftStatus.DRAFT
        assert draft.actual_word_count > 0

        findings = await scripts.review_draft(draft.id)
        assert findings  # every critic ran; fixture returns one finding each
        assert all(f.critic_role for f in findings)
        with pytest.raises(GateBlockedError):
            await scripts.approve_draft(draft.id)  # open BLOCKER

        revised = await scripts.revise_draft(draft.id)
        assert revised.version_number == draft.version_number + 1
        assert revised.status == DraftStatus.REVISED
        approved = await scripts.approve_draft(revised.id)
        assert approved.status == DraftStatus.APPROVED
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_generic_master_path(migrated_database_url: str) -> None:
    """§16/18: generic master gates, provenance, writer export, script."""

    database = Database(migrated_database_url)
    try:
        channel_service = EditorialChannelService(database)
        await channel_service.seed_channels()
        channel = await channel_service.get_channel("emtedad")
        source = await _build_source_with_units(database)
        provider = _Provider()
        await channel_service.assign_resource(
            channel.id, source.id, role=ChannelResourceRole.PRIMARY
        )
        await SourceStructureService(database, provider=provider).process_source(
            source.id
        )
        await KnowledgeUnitService(database, provider=provider).extract_for_source(
            source.id
        )
        candidates = await TopicService(database, provider=provider).mine("emtedad")
        candidate = next(c for c in candidates if "bad investments" in c.title)
        briefs = BriefService(database)
        brief = await briefs.create_for_candidate(
            candidate.id,
            BriefInput(
                question="Why do we stick with losing choices?",
                thesis="Loss aversion keeps us locked in.",
                target_duration_minutes=10,
            ),
        )
        await briefs.mark_ready(brief.id)

        masters = GenericMasterService(database)
        # §16: nothing upstream yet.
        with pytest.raises(GateBlockedError):
            await masters.build_from_content_brief(brief.id)
        research = GenericResearchService(database)
        plan = await research.create_plan_for_brief(brief.id)
        await research.build_evidence_matrix(brief.id)
        # Matrix exists but the package is not frozen yet.
        with pytest.raises(GateBlockedError):
            await masters.build_from_content_brief(brief.id)
        await research.freeze_package(plan.id)
        # Frozen package but no argument.
        with pytest.raises(GateBlockedError):
            await masters.build_from_content_brief(brief.id)
        engine = ContentEngineService(database, provider=provider)
        await engine.build_argument(brief.id)
        # Argument but no narrative.
        with pytest.raises(GateBlockedError):
            await masters.build_from_content_brief(brief.id)
        narrative = await engine.build_narrative(brief.id)

        master = await masters.build_from_content_brief(brief.id)
        assert master.status == MasterStatus.READY
        assert master.origin_type == MasterOriginType.CONTENT_BRIEF
        assert master.content_brief_id == brief.id
        assert master.channel_strategy_version_id == brief.strategy_version_id
        assert master.evidence_matrix_id is not None
        assert master.argument_plan_id is not None
        assert master.narrative_plan_id == narrative.id
        assert master.canon_version_id is None
        assert master.architecture["question"] == brief.question
        assert master.architecture["thesis"] == brief.thesis
        upstream = master.architecture["upstream"]
        assert upstream["narrative_plan_version"] == narrative.version_number
        assert upstream["research_package_version"] >= 1

        # Idempotent: identical inputs return the same master.
        again = await masters.build_from_content_brief(brief.id)
        assert again.id == master.id

        async with database.transaction() as session:
            sections = list(
                await session.scalars(
                    select(LectureSection).where(
                        LectureSection.lecture_master_version_id == master.id
                    )
                )
            )
            claims = list(
                await session.scalars(
                    select(LectureClaim).where(
                        LectureClaim.lecture_master_version_id == master.id
                    )
                )
            )
            bindings = list(
                await session.scalars(
                    select(LectureClaimEvidence)
                    .join(
                        LectureClaim,
                        LectureClaimEvidence.claim_id == LectureClaim.id,
                    )
                    .where(LectureClaim.lecture_master_version_id == master.id)
                )
            )
            citations = list(
                await session.scalars(
                    select(LectureCitation).where(
                        LectureCitation.lecture_master_version_id == master.id
                    )
                )
            )
        assert len(sections) == 1
        assert sections[0].role == SectionRole.HUMAN_ENTRY  # COLD_OPEN mapped
        assert sections[0].rhetorical_function == "COLD_OPEN"
        assert len(claims) == 1
        assert claims[0].section_id == sections[0].id
        assert claims[0].source_evidence  # unit-level provenance snapshot
        assert bindings and citations

        # Workspace stage: master ready, script available.
        state = await ProductionService(database).state_for_brief(brief.id)
        assert state.stage == ProductionStage.MASTER
        assert "build_master" in state.allowed_actions
        assert "build_script" in state.allowed_actions
        assert state.latest_master_id == master.id

        # Generic writer path: no lesson_id / lesson package involved.
        scripts = ScriptService(database, provider=provider)
        draft = await scripts.build_script(brief.id, language="en")
        assert draft.lecture_master_version_id == master.id
        assert draft.narrative_plan_id == narrative.id

        # §11: writer export is bounded — no corpus or archive dumps.
        export = await masters.writer_export(master.id)
        serialized = json.dumps(export).lower()
        assert export["master"]["origin_type"] == "CONTENT_BRIEF"
        assert export["sections"] and export["claims"]
        assert "lesson" not in serialized
        assert "canon" not in serialized

        # Cross-channel strategy pinned on the brief is rejected.
        async with database.transaction() as session:
            other = await session.scalar(
                select(EditorialChannel).where(
                    EditorialChannel.slug == "science-mystery"
                )
            )
            assert other is not None
            rogue = ChannelStrategyVersion(
                editorial_channel_id=other.id,
                version_number=99,
                core_question="rogue",
                status=StrategyStatus.DRAFT,
            )
            session.add(rogue)
            await session.flush()
            brief_row = await session.get(ContentBrief, brief.id)
            assert brief_row is not None
            brief_row.strategy_version_id = rogue.id
        with pytest.raises(GateBlockedError):
            await masters.build_from_content_brief(brief.id)
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_mining_requires_assigned_units(migrated_database_url: str) -> None:
    database = Database(migrated_database_url)
    try:
        channel_service = EditorialChannelService(database)
        await channel_service.seed_channels()
        topics = TopicService(database, provider=_Provider())
        assert await topics.mine("emtedad") == []
    finally:
        await database.dispose()
