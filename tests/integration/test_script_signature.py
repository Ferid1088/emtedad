"""ScriptSignature lifecycle: approval boundary, idempotency, distinctiveness."""

import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from alembic import command
from app.briefs.service import BriefInput, BriefService
from app.content_engine.review import ScriptService
from app.db.session import Database
from app.editorial_channels.domain import ChannelResourceRole
from app.editorial_channels.service import EditorialChannelService
from app.knowledge.structure.service import SourceStructureService
from app.knowledge.units.service import KnowledgeUnitService
from app.lecture.generic_service import GenericMasterService
from app.topics.distinctiveness import (
    DistinctivenessPlanner,
    DistinctivenessVerdict,
)
from app.topics.domain import TopicStatus
from app.topics.models import ScriptSignature, TopicCandidate
from app.topics.service import TopicService
from tests.integration.test_topics import _build_source_with_units, _Provider

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


async def _signature_count(database: Database, draft_id) -> int:
    async with database.transaction() as session:
        return (
            await session.scalar(
                select(func.count())
                .select_from(ScriptSignature)
                .where(ScriptSignature.script_draft_id == draft_id)
            )
        ) or 0


@pytest.mark.asyncio
async def test_approval_writes_signature_once_and_feeds_distinctiveness(
    migrated_database_url: str,
) -> None:
    """Approve → signature; re-approve → no duplicate; planner sees it."""

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

        from app.content_engine.service import ContentEngineService
        from app.research.generic import GenericResearchService

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

        # Draft state: no canonical signature yet.
        assert await _signature_count(database, draft.id) == 0

        approved = await scripts.approve_draft(draft.id)

        signature: ScriptSignature | None = None
        async with database.transaction() as session:
            signature = await session.scalar(
                select(ScriptSignature).where(
                    ScriptSignature.script_draft_id == approved.id
                )
            )
        assert signature is not None
        assert signature.editorial_channel_id == channel.id
        assert signature.topic_candidate_id == candidate.id
        assert signature.question == brief.question
        assert signature.thesis == brief.thesis
        assert signature.angle == brief.angle
        assert signature.argument_signature  # deterministic role chain
        assert "CLAIM" in signature.argument_signature
        assert signature.story_unit_ids  # fixture binds story_unit_refs
        assert signature.content_hash == draft.content_hash
        assert signature.created_at is not None

        # Idempotent: re-approving the same draft does not duplicate.
        await scripts.approve_draft(approved.id)
        assert await _signature_count(database, approved.id) == 1

        # Distinctiveness: a near-identical candidate sees the signature.
        async with database.transaction() as session:
            twin = TopicCandidate(
                editorial_channel_id=channel.id,
                strategy_version_id=candidate.strategy_version_id,
                title="twin",
                video_question="Why do we stick with losing choices?",
                tentative_thesis="Loss aversion keeps us locked in.",
                angle="Everyday decision traps",
                status=TopicStatus.CANDIDATE,
                knowledge_coverage_score=1.0,
                channel_fit_score=0.9,
                novelty_score=0.5,
                curiosity_score=0.8,
                emotional_score=0.7,
                practical_value_score=0.9,
                total_score=0.8,
            )
            session.add(twin)
            await session.flush()
            twin_id = twin.id
        from app.editorial_channels.models import ChannelStrategyVersion

        async with database.transaction() as session:
            twin = await session.get(TopicCandidate, twin_id)
            strategy = await session.get(
                ChannelStrategyVersion, candidate.strategy_version_id
            )
            assert twin is not None and strategy is not None
        verdict, report = await DistinctivenessPlanner(database).assess(twin, strategy)
        assert verdict == DistinctivenessVerdict.REVIEW_REQUIRED
        assert report.topic == 1.0
    finally:
        await database.dispose()
