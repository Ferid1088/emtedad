import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

from app.channel_monitoring.models import ChannelVideoCandidate, MonitoredChannel
from app.channel_monitoring.service import ChannelDiscoveryService
from app.db.session import Database
from app.knowledge.adapters.base import ChannelSnapshot, ChannelVideoSnapshot


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
        async with database.transaction() as session:
            count = await session.scalar(
                delete(ChannelVideoCandidate)
                .where(ChannelVideoCandidate.channel_id == channel.id)
                .returning(ChannelVideoCandidate.id)
            )
            await session.execute(
                delete(MonitoredChannel).where(MonitoredChannel.id == channel.id)
            )
        assert count is not None
    finally:
        await database.dispose()
