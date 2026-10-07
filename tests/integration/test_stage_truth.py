"""Stage-truth regressions (master audit §3).

Each production stage may only be complete on the basis of its own persisted,
valid artifact. No stage may become READY because an upstream artifact exists,
and approval must be impossible until critics have actually produced findings.
"""

from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import func, select, update
from sqlalchemy.engine import make_url

from alembic import command
from app.briefs.service import BriefInput, BriefService
from app.content_engine.domain import (
    DraftStatus,
    FindingSeverity,
    FindingStatus,
    ProductionStage,
    ReviewRunStatus,
    StageHealth,
)
from app.content_engine.models import (
    NarrativePlan,
    ReviewFinding,
    ReviewRun,
    ScriptDraft,
)
from app.content_engine.review import ScriptService
from app.content_engine.service import ContentEngineService, GateBlockedError
from app.db.session import Database
from app.editorial_channels.domain import ChannelResourceRole
from app.editorial_channels.models import ChannelStrategyVersion
from app.editorial_channels.service import EditorialChannelService
from app.knowledge.structure.service import SourceStructureService
from app.knowledge.units.service import KnowledgeUnitService
from app.lecture.domain import MasterStatus
from app.lecture.generic_service import GenericMasterService
from app.lecture.models import LectureMasterVersion
from app.production.service import ProductionService
from app.research.domain import EvidenceMatrixStatus, PackageStatus
from app.research.generic import GenericResearchService
from app.research.models import (
    EvidenceMatrix,
    EvidenceMatrixItem,
    ResearchPlan,
)
from app.topics.service import TopicService
from tests.integration.test_studio_ui import _database_url
from tests.integration.test_topics import _build_source_with_units, _Provider


class _InstructionCapturingProvider(_Provider):
    """Records the instructions each critic call receives."""

    def __init__(self) -> None:
        self.review_instructions: list[str] = []

    async def extract(self, request):
        if request.task == "script_review":
            self.review_instructions.append(request.instructions)
        return await super().extract(request)


class _ShortDraftProvider(_Provider):
    """Simulates a writer that violates the duration contract.

    The bounded generation-correction pass echoes the short draft back —
    correction cannot fix it, so the draft persists with FAILED generation
    status, which is exactly the pre-review gate under test.
    """

    async def extract(self, request):
        if request.task == "script_draft":
            from app.content_engine.review import ScriptDraftOutput

            return ScriptDraftOutput(
                text="Once upon a sunk cost. " * 30,
                estimated_duration_seconds=60,
            )
        if request.task == "script_generation_correction":
            from app.content_engine.review import RevisionOutput

            return RevisionOutput(text="Once upon a sunk cost. " * 30)
        return await super().extract(request)


pytestmark = pytest.mark.integration


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


def _health(state, stage: ProductionStage) -> StageHealth:
    return state.stage_states[stage]


@pytest.mark.asyncio
async def test_stage_truth_no_inferred_completion(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        provider = _Provider()
        channel_service = EditorialChannelService(database)
        await channel_service.seed_channels()
        channel = await channel_service.get_channel("emtedad")
        source = await _build_source_with_units(database)
        await SourceStructureService(database, provider=provider).process_source(
            source.id
        )
        await KnowledgeUnitService(database, provider=provider).extract_for_source(
            source.id
        )
        await channel_service.assign_resource(
            channel.id, source.id, role=ChannelResourceRole.PRIMARY
        )
        candidates = await TopicService(database, provider=provider).mine("emtedad")
        grounded = next(c for c in candidates if "bad investments" in c.title)

        briefs = BriefService(database)
        brief = await briefs.create_for_candidate(
            grounded.id,
            BriefInput(
                question="Why do we stick with losing choices?",
                thesis="Loss aversion keeps us locked in.",
                target_duration_minutes=22,
            ),
        )
        production = ProductionService(database)

        # A DRAFT brief: BRIEF in progress, nothing else started.
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.BRIEF) is StageHealth.IN_PROGRESS
        for stage in (
            ProductionStage.RESEARCH,
            ProductionStage.EVIDENCE,
            ProductionStage.ARGUMENT,
            ProductionStage.NARRATIVE,
            ProductionStage.MASTER,
            ProductionStage.SCRIPT,
            ProductionStage.REVIEW,
            ProductionStage.APPROVED,
        ):
            assert _health(state, stage) is StageHealth.NOT_STARTED, stage

        await briefs.mark_ready(brief.id)
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.BRIEF) is StageHealth.READY
        # §3: a ContentBrief does not mark RESEARCH ready.
        assert _health(state, ProductionStage.RESEARCH) is StageHealth.NOT_STARTED
        assert "freeze_research" not in state.allowed_actions

        research = GenericResearchService(database)
        plan = await research.create_plan_for_brief(brief.id)
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.RESEARCH) is StageHealth.READY
        # §3: a ResearchPlan does not mark EVIDENCE ready.
        assert _health(state, ProductionStage.EVIDENCE) is StageHealth.NOT_STARTED

        # Regression: build_evidence must produce a READY matrix, not a
        # DRAFT the owner can never promote (the historical UI deadlock).
        matrix = await research.build_evidence_matrix(brief.id)
        assert matrix.status is EvidenceMatrixStatus.READY
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.EVIDENCE) is StageHealth.READY
        # §3: a matrix does not mark ARGUMENT ready.
        assert _health(state, ProductionStage.ARGUMENT) is StageHealth.NOT_STARTED
        assert "freeze_research" in state.allowed_actions
        assert "build_master" not in state.allowed_actions

        package = await research.freeze_package(plan.id)
        assert package.status is PackageStatus.FROZEN
        state = await production.state_for_brief(brief.id)
        assert "freeze_research" not in state.allowed_actions

        engine = ContentEngineService(database, provider=provider)
        await engine.build_argument(brief.id)
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.ARGUMENT) is StageHealth.READY
        # §3: an ArgumentPlan does not mark NARRATIVE ready.
        assert _health(state, ProductionStage.NARRATIVE) is StageHealth.NOT_STARTED

        await engine.build_narrative(brief.id)
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.NARRATIVE) is StageHealth.READY
        # §3: a NarrativePlan does not mark MASTER or SCRIPT ready.
        assert _health(state, ProductionStage.MASTER) is StageHealth.NOT_STARTED
        assert "build_master" in state.allowed_actions

        await GenericMasterService(database).build_from_content_brief(brief.id)
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.MASTER) is StageHealth.READY
        # §3: a Semantic Master does not mark SCRIPT ready.
        assert _health(state, ProductionStage.SCRIPT) is StageHealth.NOT_STARTED

        scripts = ScriptService(database, provider=provider)
        draft = await scripts.build_script(brief.id, language="en")
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.SCRIPT) is StageHealth.READY
        # §3: a ScriptDraft does not mark REVIEW ready — and approval is
        # impossible until critics have produced findings.
        assert _health(state, ProductionStage.REVIEW) is StageHealth.NOT_STARTED
        assert "approve" not in state.allowed_actions
        assert _health(state, ProductionStage.APPROVED) is StageHealth.NOT_STARTED

        findings = await scripts.review_draft(draft.id)
        assert findings
        state = await production.state_for_brief(brief.id)
        # Fixture critic emits a BLOCKER → review requires attention and
        # approval is gated. §3: running critics does not auto-approve.
        assert _health(state, ProductionStage.REVIEW) is StageHealth.REVIEW_REQUIRED
        assert "approve" not in state.allowed_actions
        assert _health(state, ProductionStage.APPROVED) is StageHealth.NOT_STARTED
        with pytest.raises(GateBlockedError):
            await scripts.approve_draft(draft.id, approved_by="owner")
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_waive_then_approve_and_duration_finding(
    migrated_database_url: str,
) -> None:
    """Owner waiver is the explicit override; duration runs for all languages."""

    database = Database(migrated_database_url)
    try:
        provider = _Provider()
        channel_service = EditorialChannelService(database)
        await channel_service.seed_channels()
        channel = await channel_service.get_channel("emtedad")
        source = await _build_source_with_units(database)
        await SourceStructureService(database, provider=provider).process_source(
            source.id
        )
        await KnowledgeUnitService(database, provider=provider).extract_for_source(
            source.id
        )
        await channel_service.assign_resource(
            channel.id, source.id, role=ChannelResourceRole.PRIMARY
        )
        candidates = await TopicService(database, provider=provider).mine("emtedad")
        grounded = next(c for c in candidates if "bad investments" in c.title)
        briefs = BriefService(database)
        brief = await briefs.create_for_candidate(
            grounded.id,
            # 27.5 keeps the band draft inside the final 25–30 approval
            # gate; the short stub still exercises the review finding.
            BriefInput(question="Q?", thesis="T.", target_duration_minutes=27.5),
        )
        await briefs.mark_ready(brief.id)

        research = GenericResearchService(database)
        plan = await research.create_plan_for_brief(brief.id)
        await research.build_evidence_matrix(brief.id)
        await research.freeze_package(plan.id)
        engine = ContentEngineService(database, provider=provider)
        await engine.build_argument(brief.id)
        await engine.build_narrative(brief.id)
        await GenericMasterService(database).build_from_content_brief(brief.id)
        scripts = ScriptService(database, provider=provider)
        # Phase 5: a draft that violates the duration contract fails
        # GENERATION validation — correction is bounded, so the short
        # stub text persists with FAILED status and review actions stay
        # gated. The review-level duration finding still fires on it.
        short_scripts = ScriptService(database, provider=_ShortDraftProvider())
        short_draft = await short_scripts.build_script(brief.id, language="en")
        generation = short_draft.provenance_json["generation_validation"]
        assert generation["status"] == "FAILED"
        assert "DURATION_BELOW_GENERATION_BAND" in generation["failed_checks"]
        state = await ProductionService(database).state_for_brief(brief.id)
        assert state.generation_status == "FAILED"
        assert _health(state, ProductionStage.SCRIPT) is StageHealth.REVIEW_REQUIRED
        assert "run_review" not in state.allowed_actions
        assert "approve" not in state.allowed_actions
        findings = await short_scripts.review_draft(short_draft.id)
        duration_findings = [f for f in findings if f.code == "DURATION_TOO_SHORT"]
        assert duration_findings, "duration gate must run for English drafts"

        # A draft inside the generation band proceeds to review normally.
        draft = await scripts.build_script(brief.id, language="en")
        assert draft.provenance_json["generation_validation"]["status"] == "PASSED"
        state = await ProductionService(database).state_for_brief(brief.id)
        assert _health(state, ProductionStage.SCRIPT) is StageHealth.READY
        assert "run_review" in state.allowed_actions
        assert draft.estimated_duration_seconds > 0

        findings = await scripts.review_draft(draft.id)
        open_blocking = [
            f
            for f in findings
            if f.status is FindingStatus.OPEN
            and f.severity in {FindingSeverity.BLOCKER, FindingSeverity.WARNING}
        ]
        assert open_blocking

        # Waiving every open major finding is the honest override path.
        for finding in open_blocking:
            await scripts.waive_finding(
                finding.id, waived_by="owner", reason="owner waiver"
            )
        with pytest.raises(ValueError):
            await scripts.waive_finding(
                open_blocking[0].id, waived_by="owner", reason="owner waiver"
            )  # already waived

        state = await ProductionService(database).state_for_brief(brief.id)
        assert _health(state, ProductionStage.REVIEW) is StageHealth.READY
        assert "approve" in state.allowed_actions
        approved = await scripts.approve_draft(draft.id, approved_by="owner")
        assert approved.status is DraftStatus.APPROVED

        state = await ProductionService(database).state_for_brief(brief.id)
        assert _health(state, ProductionStage.APPROVED) is StageHealth.APPROVED
        assert "localize" in state.allowed_actions
        # §3: approval does not mark translation work complete — the
        # localization stepper truth lives on the translations page.
    finally:
        await database.dispose()


async def _draft_pipeline(database: Database, provider: _Provider):
    """Brief → plan → matrix → freeze → plans → master → draft (English)."""

    channel_service = EditorialChannelService(database)
    await channel_service.seed_channels()
    channel = await channel_service.get_channel("emtedad")
    source = await _build_source_with_units(database)
    await SourceStructureService(database, provider=provider).process_source(source.id)
    await KnowledgeUnitService(database, provider=provider).extract_for_source(
        source.id
    )
    await channel_service.assign_resource(
        channel.id, source.id, role=ChannelResourceRole.PRIMARY
    )
    candidates = await TopicService(database, provider=provider).mine("emtedad")
    grounded = next(c for c in candidates if "bad investments" in c.title)
    briefs = BriefService(database)
    brief = await briefs.create_for_candidate(
        grounded.id,
        BriefInput(question="Q?", thesis="T.", target_duration_minutes=27.5),
    )
    await briefs.mark_ready(brief.id)
    research = GenericResearchService(database)
    plan = await research.create_plan_for_brief(brief.id)
    await research.build_evidence_matrix(brief.id)
    await research.freeze_package(plan.id)
    engine = ContentEngineService(database, provider=provider)
    await engine.build_argument(brief.id)
    await engine.build_narrative(brief.id)
    await GenericMasterService(database).build_from_content_brief(brief.id)
    scripts = ScriptService(database, provider=provider)
    draft = await scripts.build_script(brief.id, language="en")
    return brief, scripts, draft


@pytest.mark.asyncio
async def test_evidence_matrix_validates_before_ready(
    migrated_database_url: str,
) -> None:
    """§16: READY requires a passing validation report — not bare creation."""

    database = Database(migrated_database_url)
    try:
        provider = _Provider()
        brief, _scripts, _draft = await _draft_pipeline(database, provider)
        research = GenericResearchService(database)

        async with database.transaction() as session:
            matrix = await session.scalar(
                select(EvidenceMatrix)
                .where(EvidenceMatrix.content_brief_id == brief.id)
                .order_by(EvidenceMatrix.version_number.desc())
                .limit(1)
            )
            assert matrix is not None
            # The pipeline froze this matrix — FROZEN is also a validated
            # state; the report must exist and pass regardless.
            assert matrix.status is EvidenceMatrixStatus.FROZEN
            assert matrix.validation_report["passed"] is True
            assert matrix.validation_report["checks"]["items_present"] is True
            assert matrix.validation_report["checks"]["evidence_references_valid"]

        # A fresh matrix builds DRAFT → validates → promotes to READY.
        matrix2 = await research.build_evidence_matrix(brief.id)
        assert matrix2.status is EvidenceMatrixStatus.READY
        assert matrix2.validation_report["passed"] is True

        async with database.transaction() as session:
            # Corrupt one item: dead unit reference + empty claim.
            item = await session.scalar(
                select(EvidenceMatrixItem)
                .where(EvidenceMatrixItem.evidence_matrix_id == matrix2.id)
                .order_by(EvidenceMatrixItem.ordinal)
                .limit(1)
            )
            assert item is not None
            item.supporting_unit_ids = ["not-a-uuid", str(uuid4())]
            item.claim_text = "   "

        matrix2 = await research.revalidate_matrix(matrix2.id)
        assert matrix2.status is EvidenceMatrixStatus.DRAFT
        report = matrix2.validation_report
        assert report["passed"] is False
        assert not report["checks"]["evidence_references_valid"]
        assert not report["checks"]["epistemic_fields_valid"]
        assert report["failures"]

        # Freezing on an unvalidated matrix must be refused.
        async with database.transaction() as session:
            plan_id = await session.scalar(
                select(ResearchPlan.id).where(ResearchPlan.content_brief_id == brief.id)
            )
        with pytest.raises(ValueError, match="unvalidated"):
            await research.freeze_package(plan_id)
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_review_run_cases_a_to_h(migrated_database_url: str) -> None:
    """§10: ReviewRun is the artifact; findings alone prove nothing."""

    database = Database(migrated_database_url)
    try:
        provider = _Provider()
        brief, scripts, draft = await _draft_pipeline(database, provider)
        production = ProductionService(database)

        # CASE A — no ReviewRun, no findings: NOT_STARTED + approval blocked.
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.REVIEW) is StageHealth.NOT_STARTED
        with pytest.raises(GateBlockedError):
            await scripts.approve_draft(draft.id, approved_by="owner")

        # CASE H — two real reviews become numbered rounds 1 and 2.
        await scripts.review_draft(draft.id)
        findings_r1 = await scripts.review_draft(draft.id)
        async with database.transaction() as session:
            runs = list(
                (
                    await session.scalars(
                        select(ReviewRun)
                        .where(ReviewRun.script_draft_id == draft.id)
                        .order_by(ReviewRun.round_number)
                    )
                ).all()
            )
        assert [run.round_number for run in runs] == [1, 2]
        assert all(run.status is ReviewRunStatus.COMPLETED for run in runs)
        assert all(
            run.draft_hash == draft.content_hash and run.draft_version == 1
            for run in runs
        )
        assert all(f.review_run_id == runs[1].id for f in findings_r1)
        # CASE D — open MAJOR/BLOCKER findings → REVIEW_REQUIRED, blocked.
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.REVIEW) is StageHealth.REVIEW_REQUIRED
        with pytest.raises(GateBlockedError):
            await scripts.approve_draft(draft.id, approved_by="owner")

        # CASE E — waiving the current run's open majors makes it READY.
        async with database.transaction() as session:
            open_major = list(
                (
                    await session.scalars(
                        select(ReviewFinding).where(
                            ReviewFinding.review_run_id == runs[1].id,
                            ReviewFinding.status == FindingStatus.OPEN,
                        )
                    )
                ).all()
            )
        for finding in open_major:
            await scripts.waive_finding(
                finding.id, waived_by="owner", reason="owner waiver"
            )
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.REVIEW) is StageHealth.READY
        assert "approve" in state.allowed_actions
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_review_run_running_stale_and_clean(
    migrated_database_url: str,
) -> None:
    """CASE B/C/F: RUNNING→IN_REVIEW, clean run→READY, hash edit→stale."""

    database = Database(migrated_database_url)
    try:
        provider = _Provider()
        brief, scripts, draft = await _draft_pipeline(database, provider)
        production = ProductionService(database)

        # CASE B — a RUNNING run with zero findings is IN_PROGRESS.
        async with database.transaction() as session:
            session.add(
                ReviewRun(
                    content_brief_id=brief.id,
                    script_draft_id=draft.id,
                    draft_version=draft.version_number,
                    draft_hash=draft.content_hash,
                    round_number=1,
                    status=ReviewRunStatus.RUNNING,
                    critic_profile_version="test",
                )
            )
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.REVIEW) is StageHealth.IN_PROGRESS
        with pytest.raises(GateBlockedError):
            await scripts.approve_draft(draft.id, approved_by="owner")

        # CASE C — a COMPLETED run with finding_count=0 is a clean review.
        async with database.transaction() as session:
            run = await session.scalar(
                select(ReviewRun).where(ReviewRun.script_draft_id == draft.id)
            )
            assert run is not None
            run.status = ReviewRunStatus.COMPLETED
            run.finding_count = 0
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.REVIEW) is StageHealth.READY
        assert "approve" in state.allowed_actions
        approved = await scripts.approve_draft(draft.id, approved_by="owner")
        assert approved.status is DraftStatus.APPROVED
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_review_stale_after_manual_edit_and_round_cap(
    migrated_database_url: str,
) -> None:
    """CASE F/G + §9: edits invalidate the run; 3 rounds then OWNER_REVIEW."""

    database = Database(migrated_database_url)
    try:
        provider = _Provider()
        brief, scripts, draft = await _draft_pipeline(database, provider)
        production = ProductionService(database)

        # Round 1 completes with open majors (fixture critic emits a BLOCKER).
        await scripts.review_draft(draft.id)
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.REVIEW) is StageHealth.REVIEW_REQUIRED

        # CASE F — simulate an owner manual edit: new text, new hash. The
        # round-1 certification must not carry over.
        async with database.transaction() as session:
            await session.execute(
                update(ScriptDraft)
                .where(ScriptDraft.id == draft.id)
                .values(
                    text=draft.text + "\nOwner-inserted paragraph.",
                    content_hash="0" * 64,
                )
            )
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.REVIEW) is StageHealth.REVIEW_REQUIRED
        with pytest.raises(GateBlockedError):
            await scripts.approve_draft(draft.id, approved_by="owner")

        # A new review against the edited text certifies the new hash.
        async with database.transaction() as session:
            edited = await session.get(ScriptDraft, draft.id)
            assert edited is not None
            edited_hash = edited.content_hash
        await scripts.review_draft(draft.id)
        async with database.transaction() as session:
            latest = await session.scalar(
                select(ReviewRun)
                .where(ReviewRun.script_draft_id == draft.id)
                .order_by(ReviewRun.round_number.desc())
                .limit(1)
            )
            assert latest is not None
            assert latest.round_number == 2
            assert latest.draft_hash == edited_hash

        # CASE G — round 2's findings are the active gate; round-1's open
        # findings are history and cannot block the new run.
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.REVIEW) is StageHealth.REVIEW_REQUIRED
        async with database.transaction() as session:
            stale_open = list(
                (
                    await session.scalars(
                        select(ReviewFinding).where(
                            ReviewFinding.script_draft_id == draft.id,
                            ReviewFinding.status == FindingStatus.OPEN,
                        )
                    )
                ).all()
            )
        # Waive round-2 majors only → READY proves round-1 stale findings
        # did not gate the current run.
        round2_open = [f for f in stale_open if f.review_run_id == latest.id]
        for finding in round2_open:
            await scripts.waive_finding(
                finding.id, waived_by="owner", reason="owner waiver"
            )
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.REVIEW) is StageHealth.READY

        # §9 — the budget counts actual REVISIONS, not review rounds.
        # A fresh run re-opens majors (round-2's were waived), then
        # three revise→review loops exhaust it; the next automatic
        # revision must stop at OWNER_REVIEW_REQUIRED instead of
        # looping forever.
        await scripts.review_draft(draft.id)
        current = draft
        for _ in range(3):
            current = await scripts.revise_draft(current.id)
            await scripts.review_draft(current.id)
        with pytest.raises(GateBlockedError, match="OWNER_REVIEW_REQUIRED"):
            await scripts.revise_draft(current.id)
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_channel_pack_checks_reach_the_critic(
    migrated_database_url: str,
) -> None:
    """§24: the strategy's agent_profile is the live source of review checks.

    An owner-edited custom check must reach the CHANNEL_SPECIFIC critic —
    not just the seeded defaults.
    """

    database = Database(migrated_database_url)
    try:
        provider = _InstructionCapturingProvider()
        brief, scripts, draft = await _draft_pipeline(database, provider)

        async with database.transaction() as session:
            strategy = await session.get(
                ChannelStrategyVersion, brief.strategy_version_id
            )
            assert strategy is not None
            profile = dict(strategy.agent_profile_json or {})
            profile["review_checks"] = ["CUSTOM_OWNER_CHECK_42"]
            strategy.agent_profile_json = profile

        await scripts.review_draft(draft.id)
        channel_critic = next(
            i for i in provider.review_instructions if "channel critic" in i
        )
        assert "CUSTOM_OWNER_CHECK_42" in channel_critic
        # Other critics still receive no channel checks.
        fact_critic = next(
            i for i in provider.review_instructions if "the fact critic" in i
        )
        assert "CUSTOM_OWNER_CHECK_42" not in fact_critic
        # The critic payload carries the bounded context, not just the draft.
        assert provider.review_instructions
    finally:
        await database.dispose()


def _seed_run(session, draft, brief, *, round_number, status, findings=0):
    """Insert one ReviewRun for the draft's current version+hash."""

    run = ReviewRun(
        content_brief_id=brief.id,
        script_draft_id=draft.id,
        draft_version=draft.version_number,
        draft_hash=draft.content_hash,
        round_number=round_number,
        status=status,
        critic_profile_version="test",
        finding_count=findings,
    )
    session.add(run)
    return run


@pytest.mark.asyncio
async def test_review_run_authority_matrix(migrated_database_url: str) -> None:
    """§1: the newest attempt for the current draft state is authoritative.

    An older clean COMPLETED run can never mask a newer RUNNING or FAILED
    attempt against the same draft hash.
    """

    database = Database(migrated_database_url)
    try:
        provider = _Provider()
        brief, _scripts, draft = await _draft_pipeline(database, provider)
        production = ProductionService(database)

        # R1 clean COMPLETED + R2 RUNNING → IN_PROGRESS, never READY.
        async with database.transaction() as session:
            _seed_run(
                session,
                draft,
                brief,
                round_number=1,
                status=ReviewRunStatus.COMPLETED,
            )
            _seed_run(
                session,
                draft,
                brief,
                round_number=2,
                status=ReviewRunStatus.RUNNING,
            )
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.REVIEW) is StageHealth.IN_PROGRESS
        assert "approve" not in state.allowed_actions

        # R2 FAILED instead → FAILED, never falls back to R1's clean run.
        async with database.transaction() as session:
            run2 = await session.scalar(
                select(ReviewRun).where(ReviewRun.round_number == 2)
            )
            assert run2 is not None
            run2.status = ReviewRunStatus.FAILED
            run2.error = "provider exploded"
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.REVIEW) is StageHealth.FAILED
        assert "approve" not in state.allowed_actions

        # R2 COMPLETED clean after R1-with-findings → R2 governs → READY.
        async with database.transaction() as session:
            run2 = await session.scalar(
                select(ReviewRun).where(ReviewRun.round_number == 2)
            )
            assert run2 is not None
            run2.status = ReviewRunStatus.COMPLETED
            run2.finding_count = 0
            session.add(
                ReviewFinding(
                    script_draft_id=draft.id,
                    review_run_id=(
                        await session.scalar(
                            select(ReviewRun.id).where(ReviewRun.round_number == 1)
                        )
                    ),
                    critic_role="FACT",
                    severity=FindingSeverity.WARNING,
                    location="old",
                    code="OLD_FINDING",
                    explanation="Round-1 finding, still open.",
                )
            )
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.REVIEW) is StageHealth.READY
        assert "approve" in state.allowed_actions

        # R3 COMPLETED with a MAJOR → REVIEW_REQUIRED again.
        async with database.transaction() as session:
            run3 = _seed_run(
                session,
                draft,
                brief,
                round_number=3,
                status=ReviewRunStatus.COMPLETED,
                findings=1,
            )
            await session.flush()
            session.add(
                ReviewFinding(
                    script_draft_id=draft.id,
                    review_run_id=run3.id,
                    critic_role="LOGIC",
                    severity=FindingSeverity.WARNING,
                    location="s2",
                    code="CIRCULAR",
                    explanation="Circular reasoning in section 2.",
                )
            )
        state = await production.state_for_brief(brief.id)
        assert _health(state, ProductionStage.REVIEW) is StageHealth.REVIEW_REQUIRED
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_no_concurrent_active_review_runs(
    migrated_database_url: str,
) -> None:
    """§2: at most one active run per exact draft state; history preserved."""

    database = Database(migrated_database_url)
    try:
        provider = _Provider()
        brief, scripts, draft = await _draft_pipeline(database, provider)

        async with database.transaction() as session:
            _seed_run(
                session,
                draft,
                brief,
                round_number=1,
                status=ReviewRunStatus.RUNNING,
            )
        # A second review POST for the same draft state must be refused,
        # not become an ambiguous second RUNNING run.
        with pytest.raises(GateBlockedError):
            await scripts.review_draft(draft.id)
        async with database.transaction() as session:
            active = list(
                await session.scalars(
                    select(ReviewRun).where(
                        ReviewRun.status.in_(
                            [ReviewRunStatus.PENDING, ReviewRunStatus.RUNNING]
                        )
                    )
                )
            )
        assert len(active) == 1

        # The DB also enforces it directly: a second active row for the
        # same draft+hash violates the partial unique index.
        with pytest.raises(Exception):  # noqa: B017 — IntegrityError
            async with database.transaction() as session:
                _seed_run(
                    session,
                    draft,
                    brief,
                    round_number=2,
                    status=ReviewRunStatus.PENDING,
                )
                await session.flush()

        # A RUNNING run for a *different* hash (edited draft) is legal —
        # the index scopes to the exact draft state.
        async with database.transaction() as session:
            _seed_run(
                session,
                draft,
                brief,
                round_number=3,
                status=ReviewRunStatus.RUNNING,
            ).draft_hash = "f" * 64
            await session.flush()

        # A completed run frees the slot: real review can start again.
        async with database.transaction() as session:
            runs = list(
                await session.scalars(
                    select(ReviewRun).where(ReviewRun.script_draft_id == draft.id)
                )
            )
            for run in runs:
                run.status = ReviewRunStatus.COMPLETED
        await scripts.review_draft(draft.id)
        async with database.transaction() as session:
            latest = await session.scalar(
                select(func.max(ReviewRun.round_number)).where(
                    ReviewRun.script_draft_id == draft.id
                )
            )
        assert latest == 4
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_legacy_unscoped_findings_stay_historical(
    migrated_database_url: str,
) -> None:
    """§3: findings with no review_run_id are history, never a modern gate.

    They are preserved for display, cannot block or certify a modern run,
    and are not silently re-scoped into the current run by revision.
    """

    database = Database(migrated_database_url)
    try:
        provider = _Provider()
        brief, scripts, draft = await _draft_pipeline(database, provider)

        # Legacy row: an unscoped BLOCKER predating the ReviewRun model.
        async with database.transaction() as session:
            session.add(
                ReviewFinding(
                    script_draft_id=draft.id,
                    review_run_id=None,
                    critic_role="FACT",
                    severity=FindingSeverity.BLOCKER,
                    location="legacy",
                    code="LEGACY",
                    explanation="Pre-ReviewRun finding.",
                )
            )

        # A modern clean run completes → the legacy BLOCKER does not gate.
        async with database.transaction() as session:
            _seed_run(
                session,
                draft,
                brief,
                round_number=1,
                status=ReviewRunStatus.COMPLETED,
            )
        state = await ProductionService(database).state_for_brief(brief.id)
        assert _health(state, ProductionStage.REVIEW) is StageHealth.READY
        assert "approve" in state.allowed_actions
        approved = await scripts.approve_draft(draft.id, approved_by="owner")
        assert approved.status is DraftStatus.APPROVED

        # The legacy row itself is untouched — history preserved.
        async with database.transaction() as session:
            legacy = await session.scalar(
                select(ReviewFinding).where(ReviewFinding.code == "LEGACY")
            )
            assert legacy is not None
            assert legacy.review_run_id is None
            assert legacy.status is FindingStatus.OPEN
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_all_channel_agent_packs_reach_only_their_channel_critic(
    migrated_database_url: str,
) -> None:
    """§7: every channel's seeded agent_profile produces distinct live
    checks for the CHANNEL_SPECIFIC critic — not dead configuration."""

    from app.briefs.models import ContentBrief
    from app.content_engine.review import _channel_checks
    from app.editorial_channels.domain import StrategyStatus
    from app.editorial_channels.models import EditorialChannel
    from app.topics.service import _strategy_payload

    database = Database(migrated_database_url)
    try:
        service = EditorialChannelService(database)
        await service.seed_channels()
        async with database.transaction() as session:
            channels = list(await session.scalars(select(EditorialChannel)))
            assert len(channels) == 5
            checks_by_slug: dict[str, tuple[str, ...]] = {}
            for channel in channels:
                strategy = await session.scalar(
                    select(ChannelStrategyVersion)
                    .where(
                        ChannelStrategyVersion.editorial_channel_id == channel.id,
                        ChannelStrategyVersion.status == StrategyStatus.ACTIVE,
                    )
                    .order_by(ChannelStrategyVersion.version_number.desc())
                )
                assert strategy is not None
                # A transient brief is enough — _channel_checks only reads
                # strategy_version_id.
                brief = ContentBrief(
                    topic_candidate_id=channel.id,
                    editorial_channel_id=channel.id,
                    strategy_version_id=strategy.id,
                    question="q",
                    thesis="t",
                    target_duration_minutes=27.5,
                )
                checks = await _channel_checks(session, brief)
                checks_by_slug[channel.slug] = checks
                assert checks, f"{channel.slug} produced no live checks"
                # Forbidden angles reach the mining prompt via the
                # strategy payload (behavioral: they constrain topics).
                payload = _strategy_payload(strategy)
                assert payload["forbidden_angles"], (
                    f"{channel.slug} has no forbidden angles"
                )

        # Channel packs are semantically distinct — no two channels
        # receive the identical check list.
        all_checks = list(checks_by_slug.values())
        assert len({tuple(sorted(c)) for c in all_checks}) == len(all_checks)

        # Spot semantic fit: each pack carries its domain vocabulary.
        assert any("adaptation" in c for c in checks_by_slug["psychology-evolution"])
        assert any("epistemic" in c for c in checks_by_slug["science-mystery"])
        assert any(
            "anachronism" in c or "timeline" in c
            for c in checks_by_slug["history-human-stories"]
        )
        assert any(
            "gender" in c or "stereotype" in c
            for c in checks_by_slug["pop-psychology-relationships"]
        )
        assert any(
            "meaning" in c or "Ayin" in c or "continuity" in c
            for c in checks_by_slug["emtedad"]
        )
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_master_survives_upstream_mutation(migrated_database_url: str) -> None:
    """A frozen master must not change when an upstream draft artifact mutates.

    Rebuilding after mutation must yield a *new* version with a different
    input_hash — never a silent in-place change.
    """
    database = Database(migrated_database_url)
    try:
        brief, _scripts, _draft = await _draft_pipeline(database, _Provider())
        async with database.transaction() as session:
            master = await GenericMasterService(database).latest_ready_for_brief(
                brief.id
            )
            assert master is not None
            first_hash = master.input_hash
            first_id = master.id
            narrative = await session.scalar(
                select(NarrativePlan).where(NarrativePlan.content_brief_id == brief.id)
            )
            assert narrative is not None
            await session.execute(
                update(NarrativePlan)
                .where(NarrativePlan.id == narrative.id)
                .values(content_hash="f" * 64)
            )
        # Frozen master is untouched.
        async with database.transaction() as session:
            reloaded = await session.get(LectureMasterVersion, first_id)
            assert reloaded is not None
            assert reloaded.input_hash == first_hash
            assert reloaded.status == MasterStatus.READY
        # Rebuild produces a distinct version bound to the new narrative hash.
        master2 = await GenericMasterService(database).build_from_content_brief(
            brief.id
        )
        assert master2.id != first_id
        assert master2.input_hash != first_hash
    finally:
        await database.dispose()
