"""Phase 6: deterministic final duration gate at approval.

The generation band (0.85–1.15 × target) only decides whether a draft is
complete enough to enter semantic review. Approval additionally requires
the configured editorial band (default 25–30 min) measured with the
draft language's speech WPM — independently of what any critic emitted.
"""

import hashlib
import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import select
from sqlalchemy.engine import make_url

from alembic import command
from app.briefs.models import ContentBrief
from app.briefs.service import BriefInput, BriefService
from app.content_engine.domain import (
    DraftStatus,
    FindingStatus,
    PlanStatus,
    ReviewRunStatus,
)
from app.content_engine.models import (
    ArgumentPlan,
    NarrativePlan,
    ReviewRun,
    ScriptDraft,
)
from app.content_engine.review import ScriptService
from app.content_engine.service import GateBlockedError
from app.db.session import Database
from app.editorial_channels.service import EditorialChannelService
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


async def _brief(database: Database, question: str, target: float = 27.5):
    """Minimal artifact chain: channel → candidate → brief."""

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
        BriefInput(question=question, thesis="T.", target_duration_minutes=target),
    )


async def _draft_with_completed_review(
    database: Database,
    brief: ContentBrief,
    *,
    language: str,
    words: int,
    version: int = 1,
    chain: int | None = None,
) -> ScriptDraft:
    """A draft plus a COMPLETED current-hash ReviewRun and zero findings.

    Satisfies every approval precondition except the final duration gate,
    isolating the deterministic check under test.
    """

    chain_version = chain if chain is not None else version
    text = " ".join(f"w{i}" for i in range(words))
    async with database.transaction() as session:
        matrix = EvidenceMatrix(
            content_brief_id=brief.id,
            version_number=chain_version,
            status=EvidenceMatrixStatus.READY,
            content_hash=hashlib.sha256(f"matrix{chain_version}".encode()).hexdigest(),
        )
        session.add(matrix)
        await session.flush()
        argument = ArgumentPlan(
            content_brief_id=brief.id,
            evidence_matrix_id=matrix.id,
            version_number=chain_version,
            status=PlanStatus.READY,
            content_hash=hashlib.sha256(
                f"argument{chain_version}".encode()
            ).hexdigest(),
        )
        session.add(argument)
        await session.flush()
        narrative = NarrativePlan(
            content_brief_id=brief.id,
            argument_plan_id=argument.id,
            version_number=chain_version,
            status=PlanStatus.READY,
            content_hash=hashlib.sha256(
                f"narrative{chain_version}".encode()
            ).hexdigest(),
        )
        session.add(narrative)
        await session.flush()
        draft = ScriptDraft(
            content_brief_id=brief.id,
            narrative_plan_id=narrative.id,
            language=language,
            version_number=version,
            text=text,
            status=DraftStatus.DRAFT,
            provenance_json={},
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            target_duration_minutes=brief.target_duration_minutes,
            actual_word_count=words,
            estimated_duration_seconds=0,
        )
        session.add(draft)
        await session.flush()
        session.add(
            ReviewRun(
                content_brief_id=brief.id,
                script_draft_id=draft.id,
                draft_version=version,
                draft_hash=draft.content_hash,
                round_number=chain_version,
                status=ReviewRunStatus.COMPLETED,
                critic_profile_version="test",
            )
        )
        await session.flush()
        await session.refresh(draft)
        return draft


@pytest.mark.asyncio
async def test_final_gate_loop1_en_short_long_and_in_band(
    migrated_database_url: str,
) -> None:
    """Loop 1 (English, 140 wpm): 23.5 and 31 min blocked, 27.2 approved."""

    database = Database(migrated_database_url)
    try:
        scripts = ScriptService(database, provider=_Provider())
        brief = await _brief(database, "Final gate EN?")
        # CASE A — 23.5 min: review-eligible, never approvable.
        short = await _draft_with_completed_review(
            database, brief, language="en", words=int(23.5 * 140)
        )
        with pytest.raises(GateBlockedError, match="APPROVAL_DURATION_GATE"):
            await scripts.approve_draft(short.id, approved_by="owner")
        # CASE B — 27.2 min: the gate passes when all review gates pass.
        ok = await _draft_with_completed_review(
            database, brief, language="en", words=int(27.2 * 140), version=2
        )
        approved = await scripts.approve_draft(ok.id, approved_by="owner")
        assert approved.status is DraftStatus.APPROVED
        # CASE C — 31 min: symmetric upper bound.
        long_draft = await _draft_with_completed_review(
            database, brief, language="en", words=int(31 * 140), version=3
        )
        with pytest.raises(GateBlockedError, match="APPROVAL_DURATION_GATE"):
            await scripts.approve_draft(long_draft.id, approved_by="owner")
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_final_gate_loop2_persian_and_german_wpm(
    migrated_database_url: str,
) -> None:
    """Loop 2: per-language WPM — fa 110, de 130; band stays 25–30 min."""

    database = Database(migrated_database_url)
    try:
        scripts = ScriptService(database, provider=_Provider())
        brief = await _brief(database, "Final gate FA/DE?")
        # Persian: 2585 words ≈ 23.5 min at 110 wpm → blocked.
        fa_short = await _draft_with_completed_review(
            database, brief, language="fa", words=2585, chain=1
        )
        with pytest.raises(GateBlockedError, match="APPROVAL_DURATION_GATE"):
            await scripts.approve_draft(fa_short.id, approved_by="owner")
        # Persian: 2992 words ≈ 27.2 min → approvable.
        fa_ok = await _draft_with_completed_review(
            database, brief, language="fa", words=2992, version=2, chain=2
        )
        approved_fa = await scripts.approve_draft(fa_ok.id, approved_by="owner")
        assert approved_fa.status is DraftStatus.APPROVED
        # German: 3055 words ≈ 23.5 min at 130 wpm → blocked;
        # 3575 words ≈ 27.5 min → approvable.
        de_short = await _draft_with_completed_review(
            database, brief, language="de", words=3055, chain=3
        )
        with pytest.raises(GateBlockedError, match="APPROVAL_DURATION_GATE"):
            await scripts.approve_draft(de_short.id, approved_by="owner")
        de_ok = await _draft_with_completed_review(
            database, brief, language="de", words=3575, version=2, chain=4
        )
        approved_de = await scripts.approve_draft(de_ok.id, approved_by="owner")
        assert approved_de.status is DraftStatus.APPROVED
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_generation_band_draft_enters_review_but_cannot_approve(
    migrated_database_url: str,
) -> None:
    """CASE D: a 23.5-min draft passes review entry; approval stays gated."""

    database = Database(migrated_database_url)
    try:
        provider = _Provider()
        scripts = ScriptService(database, provider=provider)
        brief = await _brief(database, "Review entry vs approval?")
        # 23.5 min at 140 wpm sits inside the 0.85 generation band of a
        # 27.5-min target — review may run; the finding may be waived;
        # the deterministic final gate still blocks approval.
        draft = await _draft_with_completed_review(
            database, brief, language="en", words=int(23.5 * 140)
        )
        # Remove the synthetic run so a real critic pass creates one.
        async with database.transaction() as session:
            run = await session.scalar(
                select(ReviewRun).where(ReviewRun.script_draft_id == draft.id)
            )
            assert run is not None
            await session.delete(run)
        findings = await scripts.review_draft(draft.id)
        duration = [f for f in findings if f.code == "DURATION_TOO_SHORT"]
        assert duration, "duration critic must flag the short draft"
        for finding in findings:
            if finding.status is FindingStatus.OPEN and finding.severity.value in {
                "BLOCKER",
                "WARNING",
            }:
                await scripts.waive_finding(
                    finding.id, waived_by="owner", reason="owner waiver"
                )
        with pytest.raises(GateBlockedError, match="APPROVAL_DURATION_GATE"):
            await scripts.approve_draft(draft.id, approved_by="owner")
    finally:
        await database.dispose()
