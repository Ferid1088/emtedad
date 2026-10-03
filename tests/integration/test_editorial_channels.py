"""Integration coverage for the editorial channel domain (Phase 1)."""

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
from app.db.session import Database
from app.editorial_channels.domain import (
    EDITORIAL_CHANNEL_SEEDS,
    ChannelResourceRole,
    StrategyStatus,
)
from app.editorial_channels.models import EditorialChannel
from app.editorial_channels.service import (
    ChannelNotFoundError,
    EditorialChannelService,
)
from app.knowledge.domain import IngestionStatus, SourceType
from app.knowledge.models import Source

pytestmark = pytest.mark.integration


def _database_url() -> str:
    try:
        return os.environ["EMTEDAD_DATABASE_URL"]
    except KeyError as exc:
        raise RuntimeError(
            "EMTEDAD_DATABASE_URL is required for integration tests"
        ) from exc


def _sync_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _url_for_database(url: str, database: str) -> str:
    return make_url(url).set(database=database).render_as_string(hide_password=False)


@pytest.fixture
def migrated_database_url() -> Iterator[str]:
    base_url = _database_url()
    name = f"emtedad_test_{uuid4().hex}"
    admin_url = _sync_url(_url_for_database(base_url, "postgres"))
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = _url_for_database(base_url, name)
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


async def _create_source(database: Database, external_id: str) -> Source:
    async with database.transaction() as session:
        source = Source(
            source_type=SourceType.YOUTUBE_VIDEO,
            platform="youtube",
            external_id=external_id,
            canonical_url=f"https://www.youtube.com/watch?v={external_id}",
            title="Fixture source",
            language="en",
            ingestion_status=IngestionStatus.INGESTED,
        )
        session.add(source)
        await session.flush()
        return source


@pytest.mark.asyncio
async def test_five_channels_seeded_with_active_strategy(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    service = EditorialChannelService(database)
    try:
        channels = await service.seed_channels()
        assert len(channels) == 5
        assert {channel.slug for channel in channels} == {
            seed.slug for seed in EDITORIAL_CHANNEL_SEEDS
        }
        for channel in channels:
            strategy = await service.get_active_strategy(channel.id)
            assert strategy.status is StrategyStatus.ACTIVE
            assert strategy.version_number == 1
            assert strategy.core_question
            assert strategy.activated_at is not None
            assert strategy.agent_profile_json["special_roles"]

        # Seeding twice must not duplicate channels or strategies.
        again = await service.seed_channels()
        assert {channel.id for channel in again} == {channel.id for channel in channels}
        for channel in channels:
            strategies = await service.list_strategies(channel.id)
            assert len(strategies) == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_source_assignable_to_many_channels_without_duplication(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    service = EditorialChannelService(database)
    try:
        channels = await service.seed_channels()
        source = await _create_source(database, "multiassign01")
        targets = channels[:3]
        for channel in targets:
            await service.assign_resource(
                channel.id, source.id, role=ChannelResourceRole.PRIMARY
            )
        for channel in targets:
            links = await service.list_channel_resources(channel.id)
            assert len(links) == 1
            assert links[0].source_id == source.id
        async with database.transaction() as session:
            source_count = await session.scalar(select(func.count(Source.id)))
            channel_count = await session.scalar(
                select(func.count(EditorialChannel.id))
            )
        assert source_count == 1
        assert channel_count == 5
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_one_active_strategy_and_version_increments(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    service = EditorialChannelService(database)
    try:
        channel = (await service.seed_channels())[0]
        draft = await service.create_strategy_draft(
            channel.id, core_question="A revised editorial question?"
        )
        assert draft.version_number == 2
        assert draft.status is StrategyStatus.DRAFT

        activated = await service.activate_strategy(draft.id)
        assert activated.status is StrategyStatus.ACTIVE
        assert activated.activated_at is not None

        strategies = await service.list_strategies(channel.id)
        active = [s for s in strategies if s.status is StrategyStatus.ACTIVE]
        archived = [s for s in strategies if s.status is StrategyStatus.ARCHIVED]
        assert len(active) == 1
        assert active[0].id == draft.id
        assert len(archived) == 1
        assert archived[0].version_number == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_unassign_resource_keeps_source(migrated_database_url: str) -> None:
    database = Database(migrated_database_url)
    service = EditorialChannelService(database)
    try:
        channel = (await service.seed_channels())[0]
        source = await _create_source(database, "unassign0001")
        await service.assign_resource(channel.id, source.id)
        assert await service.unassign_resource(channel.id, source.id) is True
        assert await service.unassign_resource(channel.id, source.id) is False
        async with database.transaction() as session:
            persisted = await session.get(Source, source.id)
        assert persisted is not None
        assert persisted.external_id == "unassign0001"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_unknown_channel_slug_raises_not_found(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    service = EditorialChannelService(database)
    try:
        await service.seed_channels()
        with pytest.raises(ChannelNotFoundError):
            await service.get_channel("does-not-exist")
    finally:
        await database.dispose()
