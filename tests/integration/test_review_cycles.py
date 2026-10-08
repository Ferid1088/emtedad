"""Phase 6: review cycles — the automatic revision budget is per cycle.

Reaching max_revision_rounds ends the *automatic* loop at an owner
checkpoint; it must never permanently lock a brief. The owner explicitly
starts the next cycle — history stays intact, runs keep their global
round_number, and each run records its cycle_number.
"""

import hashlib
import os
from collections.abc import Iterator
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from alembic import command
from app.briefs.models import ContentBrief
from app.briefs.service import BriefInput, BriefService
from app.content_engine.domain import (
    DraftStatus,
    FindingSeverity,
    FindingStatus,
    PlanStatus,
    ReviewRunStatus,
)
from app.content_engine.models import (
    ArgumentPlan,
    NarrativePlan,
    ReviewCycle,
    ReviewFinding,
    ReviewRun,
    ScriptDraft,
)
from app.content_engine.review import ScriptService
from app.content_engine.service import GateBlockedError
from app.db.session import Database
from app.editorial_channels.service import EditorialChannelService
from app.production.service import ProductionService
from app.research.domain import EvidenceMatrixStatus
from app.research.models import EvidenceMatrix
from app.topics.service import TopicService
from tests.integration.test_topics import _Provider

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


async def _brief(database: Database, question: str) -> ContentBrief:
    channel_service = EditorialChannelService(database)
    await channel_service.seed_channels()
    channel = await channel_service.get_channel("emtedad")
    strategies = await channel_service.list_strategies(channel.id)
    active = next(s for s in strategies if s.status.value == "ACTIVE")
    candidate = await TopicService(database).create_manual(
        channel.id, active.id, question=question
    )
    return await BriefService(database).create_for_candidate(
        candidate.id,
        BriefInput(question=question, thesis="T.", target_duration_minutes=27.5),
    )


async def _exhausted_cycle_one(
    database: Database, brief: ContentBrief
) -> tuple[ScriptDraft, UUID]:
    """Draft + 3 cycle-1 REVISIONS + 4 completed runs + one open WARNING.

    Models a brief whose first automatic cycle spent all 3 revision
    slots (review→revise×3→final review). Reviews alone never exhaust
    the budget — only persisted revisions do.
    """

    async with database.transaction() as session:
        matrix = EvidenceMatrix(
            content_brief_id=brief.id,
            version_number=1,
            status=EvidenceMatrixStatus.READY,
            content_hash=hashlib.sha256(b"matrix").hexdigest(),
        )
        session.add(matrix)
        await session.flush()
        argument = ArgumentPlan(
            content_brief_id=brief.id,
            evidence_matrix_id=matrix.id,
            version_number=1,
            status=PlanStatus.READY,
            content_hash=hashlib.sha256(b"argument").hexdigest(),
        )
        session.add(argument)
        await session.flush()
        narrative = NarrativePlan(
            content_brief_id=brief.id,
            argument_plan_id=argument.id,
            version_number=1,
            status=PlanStatus.READY,
            content_hash=hashlib.sha256(b"narrative").hexdigest(),
        )
        session.add(narrative)
        await session.flush()
        text = "word " * 3000
        draft = ScriptDraft(
            content_brief_id=brief.id,
            narrative_plan_id=narrative.id,
            language="en",
            version_number=1,
            text=text,
            status=DraftStatus.IN_REVIEW,
            provenance_json={},
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            target_duration_minutes=27.5,
            actual_word_count=3000,
        )
        session.add(draft)
        await session.flush()
        # Three revision drafts carry revision_cycle=1 — these are what
        # exhaust the cycle-1 budget, not the review runs. v4 is the
        # current (revisable) draft; v1–v3 are archived history.
        draft.status = DraftStatus.ARCHIVED
        current = draft
        for version in (2, 3, 4):
            revision_text = f"revision {version} " + text
            current = ScriptDraft(
                content_brief_id=brief.id,
                narrative_plan_id=narrative.id,
                language="en",
                version_number=version,
                text=revision_text,
                status=(DraftStatus.ARCHIVED if version < 4 else DraftStatus.REVISED),
                provenance_json={"revised_from_draft": str(draft.id)},
                content_hash=hashlib.sha256(revision_text.encode()).hexdigest(),
                target_duration_minutes=27.5,
                actual_word_count=3010,
                revision_cycle=1,
            )
            session.add(current)
            await session.flush()
        latest_run_id = None
        for round_number in (1, 2, 3, 4):
            run = ReviewRun(
                content_brief_id=brief.id,
                script_draft_id=current.id,
                draft_version=current.version_number,
                draft_hash=current.content_hash,
                round_number=round_number,
                cycle_number=1,
                status=ReviewRunStatus.COMPLETED,
                critic_profile_version="test",
            )
            session.add(run)
            await session.flush()
            latest_run_id = run.id
        assert latest_run_id is not None
        session.add(
            ReviewFinding(
                script_draft_id=current.id,
                review_run_id=latest_run_id,
                critic_role="FACT",
                severity=FindingSeverity.WARNING,
                location="middle",
                code="OVERCLAIM",
                explanation="Claim needs hedging.",
            )
        )
        await session.flush()
        await session.refresh(current)
        return current, latest_run_id


@pytest.mark.asyncio
async def test_cycle_one_exhaustion_checkpoint_and_start(
    migrated_database_url: str,
) -> None:
    """Loop 1: cap → owner checkpoint stays until explicit cycle start."""

    database = Database(migrated_database_url)
    try:
        scripts = ScriptService(database, provider=_Provider())
        brief = await _brief(database, "Cycle checkpoint?")
        draft, _run_id = await _exhausted_cycle_one(database, brief)

        state = await ProductionService(database).state_for_brief(brief.id)
        assert state.current_review_cycle == 1
        assert state.cycle_revisions_used == 3
        assert state.revision_budget_exhausted
        assert "start_review_cycle" in state.allowed_actions

        # Idle owner: automatic revision stays gated — no silent reset.
        with pytest.raises(GateBlockedError, match="OWNER_REVIEW_REQUIRED"):
            await scripts.revise_draft(draft.id)

        # Premature start is refused: budget only resets at the checkpoint.
        cycle = await scripts.start_review_cycle(brief.id, started_by="owner")
        assert cycle.cycle_number == 2

        state = await ProductionService(database).state_for_brief(brief.id)
        assert state.current_review_cycle == 2
        assert state.cycle_revisions_used == 0
        assert not state.revision_budget_exhausted
        assert "start_review_cycle" not in state.allowed_actions

        # Cycle 2 grants a fresh bounded budget — revision proceeds.
        revised = await scripts.revise_draft(draft.id)
        assert revised.version_number == 5
        assert revised.revision_cycle == 2

        # History untouched: cycle-1 runs keep round + cycle numbers.
        async with database.transaction() as session:
            runs = list(
                (
                    await session.scalars(
                        select(ReviewRun).where(ReviewRun.content_brief_id == brief.id)
                    )
                ).all()
            )
        assert {r.round_number for r in runs} == {1, 2, 3, 4}
        assert all(r.cycle_number == 1 for r in runs)
        cycles = list(
            (
                await session.scalars(
                    select(ReviewCycle).where(ReviewCycle.content_brief_id == brief.id)
                )
            ).all()
        )
        assert [c.cycle_number for c in cycles] == [2]
        assert cycles[0].started_by == "owner"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_new_cycle_runs_numbered_and_old_review_not_certifying(
    migrated_database_url: str,
) -> None:
    """Loop 2: new runs land in cycle 2; edited text voids certification."""

    database = Database(migrated_database_url)
    try:
        provider = _Provider()
        scripts = ScriptService(database, provider=provider)
        brief = await _brief(database, "Cycle numbering?")
        draft, _run_id = await _exhausted_cycle_one(database, brief)

        # Starting a cycle while budget remains must fail — verified here
        # on a brief whose cycle 2 has not been authorized yet.
        with pytest.raises(GateBlockedError, match="OWNER_REVIEW_REQUIRED"):
            await scripts.revise_draft(draft.id)
        await scripts.start_review_cycle(brief.id, started_by="owner")

        # A fresh review in cycle 2 records the cycle and keeps global
        # round numbering — old runs are never renumbered.
        await scripts.review_draft(draft.id)
        async with database.transaction() as session:
            latest = await session.scalar(
                select(ReviewRun)
                .where(ReviewRun.script_draft_id == draft.id)
                .order_by(ReviewRun.round_number.desc())
                .limit(1)
            )
            assert latest is not None
            assert latest.cycle_number == 2
            assert latest.round_number == 5
            assert latest.status is ReviewRunStatus.COMPLETED
            max_round = await session.scalar(
                select(func.max(ReviewRun.round_number)).where(
                    ReviewRun.content_brief_id == brief.id
                )
            )
            assert max_round == 5
            # Duplicate/extra reviews never consumed revision budget:
            # still zero revision drafts tagged to cycle 2.
            revisions_used = int(
                await session.scalar(
                    select(func.count(ScriptDraft.id)).where(
                        ScriptDraft.content_brief_id == brief.id,
                        ScriptDraft.revision_cycle == 2,
                    )
                )
                or 0
            )
            assert revisions_used == 0

        # Editing the draft creates a new hash — the completed cycle-2 run
        # certifies only the text it reviewed.
        async with database.transaction() as session:
            row = await session.get(ScriptDraft, draft.id)
            assert row is not None
            row.text = row.text + " extra words"
            row.content_hash = hashlib.sha256(row.text.encode()).hexdigest()
        with pytest.raises(GateBlockedError, match="review required"):
            await scripts.approve_draft(draft.id, approved_by="owner")

        # Cycle-2 budget is per-cycle and counts REVISIONS: zero used so
        # far, 3 max — revise is allowed without another owner cycle.
        revised = await scripts.revise_draft(draft.id)
        assert revised.version_number == 5
        assert revised.revision_cycle == 2
        assert revised.status is DraftStatus.REVISED
    finally:
        await database.dispose()


async def _fresh_draft(
    database: Database, brief: ContentBrief, *, words: int = 3000
) -> ScriptDraft:
    """Minimal artifact chain + draft (not a revision — cycle NULL)."""

    async with database.transaction() as session:
        matrix = EvidenceMatrix(
            content_brief_id=brief.id,
            version_number=1,
            status=EvidenceMatrixStatus.READY,
            content_hash=hashlib.sha256(b"matrix").hexdigest(),
        )
        session.add(matrix)
        await session.flush()
        argument = ArgumentPlan(
            content_brief_id=brief.id,
            evidence_matrix_id=matrix.id,
            version_number=1,
            status=PlanStatus.READY,
            content_hash=hashlib.sha256(b"argument").hexdigest(),
        )
        session.add(argument)
        await session.flush()
        narrative = NarrativePlan(
            content_brief_id=brief.id,
            argument_plan_id=argument.id,
            version_number=1,
            status=PlanStatus.READY,
            content_hash=hashlib.sha256(b"narrative").hexdigest(),
        )
        session.add(narrative)
        await session.flush()
        text = "word " * words
        draft = ScriptDraft(
            content_brief_id=brief.id,
            narrative_plan_id=narrative.id,
            language="en",
            version_number=1,
            text=text,
            status=DraftStatus.IN_REVIEW,
            provenance_json={},
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            target_duration_minutes=27.5,
            actual_word_count=words,
        )
        session.add(draft)
        await session.flush()
        await session.refresh(draft)
        return draft


@pytest.mark.asyncio
async def test_revision_budget_counts_revisions_not_runs(
    migrated_database_url: str,
) -> None:
    """§10 regression matrix: only persisted revisions consume budget."""

    database = Database(migrated_database_url)
    try:
        scripts = ScriptService(database, provider=_Provider())
        brief = await _brief(database, "Budget semantics?")
        draft = await _fresh_draft(database, brief)

        state = await ProductionService(database).state_for_brief(brief.id)
        # CASE A: initial review only → 0 used / 3 remaining.
        assert state.cycle_revisions_used == 0
        await scripts.review_draft(draft.id)
        state = await ProductionService(database).state_for_brief(brief.id)
        assert state.cycle_revisions_used == 0

        # CASE C: a second review of the SAME draft → still 0.
        await scripts.review_draft(draft.id)
        state = await ProductionService(database).state_for_brief(brief.id)
        assert state.cycle_revisions_used == 0

        # CASE B: revision #1 + review → used = 1.
        revised1 = await scripts.revise_draft(draft.id)
        assert revised1.revision_cycle == 1
        state = await ProductionService(database).state_for_brief(brief.id)
        assert state.cycle_revisions_used == 1
        await scripts.review_draft(revised1.id)
        state = await ProductionService(database).state_for_brief(brief.id)
        assert state.cycle_revisions_used == 1

        # CASE D: a FAILED run consumes nothing.
        async with database.transaction() as session:
            session.add(
                ReviewRun(
                    content_brief_id=brief.id,
                    script_draft_id=revised1.id,
                    draft_version=revised1.version_number,
                    draft_hash=revised1.content_hash,
                    round_number=99,
                    cycle_number=1,
                    status=ReviewRunStatus.FAILED,
                    critic_profile_version="test",
                )
            )
        state = await ProductionService(database).state_for_brief(brief.id)
        assert state.cycle_revisions_used == 1

        # CASE E: revisions #2 and #3 exhaust the cycle-1 budget.
        await scripts.review_draft(revised1.id)
        revised2 = await scripts.revise_draft(revised1.id)
        await scripts.review_draft(revised2.id)
        revised3 = await scripts.revise_draft(revised2.id)
        state = await ProductionService(database).state_for_brief(brief.id)
        assert state.cycle_revisions_used == 3
        assert state.revision_budget_exhausted
        # An open major finding on the exhausted-cycle draft → checkpoint.
        await scripts.review_draft(revised3.id)
        with pytest.raises(GateBlockedError, match="OWNER_REVIEW_REQUIRED"):
            await scripts.revise_draft(revised3.id)

        # CASE F: owner starts cycle 2 → fresh budget, history intact.
        await scripts.start_review_cycle(brief.id, started_by="owner")
        state = await ProductionService(database).state_for_brief(brief.id)
        assert state.current_review_cycle == 2
        assert state.cycle_revisions_used == 0
        async with database.transaction() as session:
            revisions = int(
                await session.scalar(
                    select(func.count(ScriptDraft.id)).where(
                        ScriptDraft.content_brief_id == brief.id,
                        ScriptDraft.revision_cycle == 1,
                    )
                )
                or 0
            )
        assert revisions == 3
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_waiver_is_owner_only_and_justified(
    migrated_database_url: str,
) -> None:
    """§4: agents may recommend; only an explicit owner call may waive."""

    database = Database(migrated_database_url)
    try:
        scripts = ScriptService(database, provider=_Provider())
        brief = await _brief(database, "Waiver authority?")
        draft, _run_id = await _exhausted_cycle_one(database, brief)
        async with database.transaction() as session:
            finding = await session.scalar(
                select(ReviewFinding).where(ReviewFinding.script_draft_id == draft.id)
            )
            assert finding is not None
            finding_id = finding.id

        # CASE B: agent recommendation keeps the finding OPEN and gating.
        rec = await scripts.recommend_waiver(
            finding_id,
            recommended_by="review-agent",
            reason="hedged researcher-attributed claim; minor",
        )
        assert rec.status is FindingStatus.OPEN
        assert rec.resolution_actor == "review-agent"
        assert rec.resolution_note is not None
        assert rec.resolution_note.startswith("RECOMMENDATION")

        # Missing identity / justification is rejected.
        with pytest.raises(ValueError):
            await scripts.waive_finding(finding_id, waived_by="", reason="x")
        with pytest.raises(ValueError):
            await scripts.waive_finding(finding_id, waived_by="owner", reason="")

        # CASE A/C: owner waiver persists actor + justification.
        waived = await scripts.waive_finding(
            finding_id, waived_by="owner", reason="accept minor style risk"
        )
        assert waived.status is FindingStatus.WAIVED
        assert waived.resolution_actor == "owner"
        assert waived.resolution_note == "accept minor style risk"
        # A waiver is final for that finding — no silent re-resolve.
        with pytest.raises(ValueError):
            await scripts.waive_finding(finding_id, waived_by="owner", reason="again")
    finally:
        await database.dispose()


async def _revision_fixture(
    database: Database,
    brief: ContentBrief,
    *,
    parent_blockers: int,
    parent_severity: FindingSeverity,
) -> tuple[ScriptDraft, ScriptDraft, ReviewFinding]:
    """Parent (archived, completed run) + candidate (REVISED) + finding.

    Mirrors the state ``revise_draft`` leaves behind: the parent is
    archived, its open finding was marked ADDRESSED, and the candidate
    carries ``revised_from_draft``/``parent_status``/``addressed_finding_ids``
    provenance. The candidate has not been reviewed yet — its own run is
    what triggers best-of-history comparison.
    """

    async with database.transaction() as session:
        matrix = EvidenceMatrix(
            content_brief_id=brief.id,
            version_number=1,
            status=EvidenceMatrixStatus.READY,
            content_hash=hashlib.sha256(b"matrix").hexdigest(),
        )
        session.add(matrix)
        await session.flush()
        argument = ArgumentPlan(
            content_brief_id=brief.id,
            evidence_matrix_id=matrix.id,
            version_number=1,
            status=PlanStatus.READY,
            content_hash=hashlib.sha256(b"argument").hexdigest(),
        )
        session.add(argument)
        await session.flush()
        narrative = NarrativePlan(
            content_brief_id=brief.id,
            argument_plan_id=argument.id,
            version_number=1,
            status=PlanStatus.READY,
            content_hash=hashlib.sha256(b"narrative").hexdigest(),
        )
        session.add(narrative)
        await session.flush()
        text = "word " * 3000  # 27.3 min at 110 wpm — inside the band.
        parent = ScriptDraft(
            content_brief_id=brief.id,
            narrative_plan_id=narrative.id,
            language="en",
            version_number=1,
            text=text,
            status=DraftStatus.ARCHIVED,
            provenance_json={},
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            target_duration_minutes=27.5,
            actual_word_count=3000,
            revision_cycle=1,
        )
        session.add(parent)
        await session.flush()
        parent_run = ReviewRun(
            content_brief_id=brief.id,
            script_draft_id=parent.id,
            draft_version=parent.version_number,
            draft_hash=parent.content_hash,
            round_number=1,
            cycle_number=1,
            status=ReviewRunStatus.COMPLETED,
            critic_profile_version="test",
            finding_count=1,
            blocking_count=parent_blockers,
            major_count=0 if parent_blockers else 1,
        )
        session.add(parent_run)
        await session.flush()
        finding = ReviewFinding(
            script_draft_id=parent.id,
            review_run_id=parent_run.id,
            critic_role="FACT",
            severity=parent_severity,
            location="middle",
            code="OVERCLAIM",
            explanation="overclaims",
            correction_constraint="hedge",
            status=FindingStatus.ADDRESSED,
        )
        session.add(finding)
        await session.flush()
        cand_text = "better words " * 3000
        candidate = ScriptDraft(
            content_brief_id=brief.id,
            narrative_plan_id=parent.narrative_plan_id,
            language="en",
            version_number=2,
            text=cand_text,
            status=DraftStatus.REVISED,
            provenance_json={
                "revised_from_draft": str(parent.id),
                "parent_status": DraftStatus.IN_REVIEW.value,
                "addressed_finding_ids": [str(finding.id)],
            },
            content_hash=hashlib.sha256(cand_text.encode()).hexdigest(),
            target_duration_minutes=27.5,
            actual_word_count=6000,
            revision_cycle=1,
        )
        session.add(candidate)
        await session.flush()
        return parent, candidate, finding


@pytest.mark.asyncio
async def test_rejected_revision_restores_parent_and_reopens_findings(
    migrated_database_url: str,
) -> None:
    """§5 best-of-history: a regression candidate never replaces the parent.

    Parent reviewed clean of blockers (one WARNING the revision claimed
    to fix); the candidate's fresh review reports one BLOCKER per critic
    role → strictly worse → the parent is restored to its recorded
    status, the candidate is archived, and the claimed finding is
    reopened rather than silently staying ADDRESSED.
    """

    database = Database(migrated_database_url)
    try:
        scripts = ScriptService(database, provider=_Provider())
        brief = await _brief(database, "Rejected revision?")
        parent, candidate, finding = await _revision_fixture(
            database,
            brief,
            parent_blockers=0,
            parent_severity=FindingSeverity.WARNING,
        )
        parent_id, candidate_id, finding_id = parent.id, candidate.id, finding.id

        await scripts.review_draft(candidate_id)

        async with database.transaction() as session:
            parent = await session.get(ScriptDraft, parent_id)
            candidate = await session.get(ScriptDraft, candidate_id)
            finding = await session.get(ReviewFinding, finding_id)
            assert parent is not None and candidate is not None
            assert finding is not None
            assert parent.status is DraftStatus.IN_REVIEW
            assert candidate.status is DraftStatus.ARCHIVED
            assert finding.status is FindingStatus.OPEN
            assert "rejected" in (finding.resolution_note or "")
            decision = candidate.provenance_json["candidate_decision"]
            assert decision["decision"] == "rejected"
            assert decision["incumbent_draft_id"] == str(parent_id)
            assert list(decision["candidate_rank"]) > list(decision["incumbent_rank"])
    finally:
        await database.dispose()


class _CleanReviewProvider(_Provider):
    """Reviews return zero findings — the candidate is genuinely clean."""

    async def extract(self, request):  # noqa: ANN001, ANN201
        if request.task == "script_review":
            from app.content_engine.review import ReviewFindingsOutput

            return ReviewFindingsOutput(findings=[])
        return await super().extract(request)


@pytest.mark.asyncio
async def test_improved_revision_promotes_and_keeps_parent_archived(
    migrated_database_url: str,
) -> None:
    """§5: a strictly-better candidate is promoted; history stays archived.

    The parent's completed run recorded a BLOCKER that the revision
    fixed: the candidate's clean review ranks strictly better, so it
    keeps REVISED status and the decision is recorded in provenance.
    """

    database = Database(migrated_database_url)
    try:
        scripts = ScriptService(database, provider=_CleanReviewProvider())
        brief = await _brief(database, "Improved revision?")
        parent, candidate, finding = await _revision_fixture(
            database,
            brief,
            parent_blockers=1,
            parent_severity=FindingSeverity.BLOCKER,
        )
        parent_id, candidate_id, finding_id = parent.id, candidate.id, finding.id

        await scripts.review_draft(candidate_id)

        async with database.transaction() as session:
            parent = await session.get(ScriptDraft, parent_id)
            candidate = await session.get(ScriptDraft, candidate_id)
            finding = await session.get(ReviewFinding, finding_id)
            assert parent is not None and candidate is not None
            assert finding is not None
            assert parent.status is DraftStatus.ARCHIVED
            # The candidate stays live — review_draft marked it IN_REVIEW
            # when its own run started; promotion only means it was not
            # archived back to history.
            assert candidate.status is DraftStatus.IN_REVIEW
            assert finding.status is FindingStatus.ADDRESSED
            decision = candidate.provenance_json["candidate_decision"]
            assert decision["decision"] == "promoted"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_critic_calls_are_billed_to_their_production(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: critic telemetry was recorded without the brief.

    Every other production call passes ``content_brief_id`` to its
    recorder; the critics did not, so the heaviest calls of a run landed in
    ``ops.llm_call_events`` unattributed and the workspace's per-production
    token and cost figures silently left them out.
    """

    from app.content_engine import review as review_module

    database = Database(migrated_database_url)
    recorders: list[object] = []
    real_resolve = review_module.resolve_llm_provider

    def capture(**kwargs: object):  # type: ignore[no-untyped-def]
        recorders.append(kwargs.get("recorder"))
        return _Provider()

    monkeypatch.setattr(review_module, "resolve_llm_provider", capture)
    try:
        brief = await _brief(database, "Wem gehört ein Kritiker-Call?")
        draft = await _fresh_draft(database, brief)
        # No injected provider: this is the path that builds its own.
        await ScriptService(database).review_draft(draft.id)

        assert recorders, "no provider was resolved — the path changed"
        attributed = [
            r for r in recorders if getattr(r, "content_brief_id", None) == brief.id
        ]
        assert len(attributed) == len(recorders), [
            getattr(r, "content_brief_id", None) for r in recorders
        ]
        assert real_resolve is not capture
    finally:
        await database.dispose()
