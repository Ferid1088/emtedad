import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from app.channel_monitoring.models import ChannelVideoCandidate
from app.channel_monitoring.service import ChannelDiscoveryService
from app.core.config import Environment, Settings
from app.db.session import Database
from app.knowledge.adapters.base import ChannelSnapshot, ChannelVideoSnapshot
from app.main import create_app


class FakeChannelAdapter:
    async def resolve_channel(self, _locator: str) -> ChannelSnapshot:
        return ChannelSnapshot(
            external_channel_id="UC1234567890123456789012",
            name="Test Channel",
            channel_url="https://www.youtube.com/channel/UC1234567890123456789012",
            handle="@test-channel",
        )

    async def list_channel_videos(
        self, _locator: str
    ) -> tuple[ChannelVideoSnapshot, ...]:
        return (
            ChannelVideoSnapshot(
                youtube_video_id="ZZZZZZZZZZ1",
                title="New video",
                published_at=datetime.now(UTC),
                thumbnail_url=None,
                duration_seconds=60,
            ),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_discovery_is_approval_gated_and_idempotent() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    database = Database(database_url)
    service = ChannelDiscoveryService(
        database,
        adapter=FakeChannelAdapter(),  # type: ignore[arg-type]
    )
    channel = await service.register("https://www.youtube.com/@test-channel")
    try:
        first = await service.discover(channel.id)
        second = await service.discover(channel.id)
        assert len(first) == 1
        assert len(second) == 1
        assert first[0].youtube_video_id == "ZZZZZZZZZZ1"
        assert first[0].status.value == "NEW"
        source_count = await _source_count(database)
        assert await service.delete_channel(channel.id)
        async with database.transaction() as session:
            pending = await session.scalar(
                select(func.count(ChannelVideoCandidate.id)).where(
                    ChannelVideoCandidate.channel_id == channel.id
                )
            )
        assert pending == 0
        assert await _source_count(database) == source_count
        readded = await service.register("https://www.youtube.com/@test-channel")
        assert readded.external_channel_id == channel.external_channel_id
        rediscovered = await service.discover(readded.id)
        assert len(rediscovered) == 1
    finally:
        await database.dispose()


async def _source_count(database: Database) -> int:
    from app.knowledge.models import Source

    async with database.transaction() as session:
        return int(await session.scalar(select(func.count(Source.id))) or 0)


def test_unknown_channel_delete_returns_404() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(database_url),
        storage_root=Path("/tmp/emtedad-owner-web-test"),
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(f"/channels/{uuid4()}/delete")
    assert response.status_code == 404
