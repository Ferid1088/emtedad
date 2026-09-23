import asyncio
import os
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.content_strategy.models import (
    EditorialProject,
    TopicStrategy,
    TopicStrategyNode,
    TopicUseHistory,
)
from app.core.config import Environment, Settings
from app.db.session import Database
from app.main import create_app


@pytest.mark.integration
def test_strategy_tree_is_grounded_and_topic_use_is_repeatable() -> None:
    database_url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not database_url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    database = Database(database_url)

    async def unused_node() -> tuple[UUID, int]:
        async with database.transaction() as session:
            strategy = await session.scalar(
                select(TopicStrategy).order_by(TopicStrategy.version_number.desc())
            )
            assert strategy is not None
            node = await session.scalar(
                select(TopicStrategyNode)
                .where(
                    TopicStrategyNode.strategy_id == strategy.id,
                    TopicStrategyNode.node_type == "TOPIC",
                    TopicStrategyNode.generation_count == 0,
                )
                .order_by(TopicStrategyNode.ordinal)
            )
            assert node is not None
            return node.id, node.generation_count

    node_id, count_before = asyncio.run(unused_node())
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(database_url),
        storage_root=Path("/tmp/emtedad-topic-strategy-test"),
    )
    with TestClient(create_app(settings)) as client:
        tree = client.get("/strategy")
        assert tree.status_code == 200
        assert "Emtedad Themenbaum" in tree.text
        assert "unbenutzt" in tree.text
        detail = client.get(f"/strategy/topics/{node_id}")
        assert detail.status_code == 200
        used = client.post(
            f"/strategy/topics/{node_id}/use",
            data={
                "owner_prompt": "Persian-first focus",
                "target_duration_minutes": "10",
            },
            follow_redirects=False,
        )
        assert used.status_code == 303
        workspace = client.get(used.headers["location"])
        assert workspace.status_code == 200
        assert "Recherche" in workspace.text

    async def cleanup() -> None:
        async with database.transaction() as session:
            project = await session.get(
                EditorialProject, UUID(used.headers["location"].split("/")[-1])
            )
            if project is not None:
                await session.execute(
                    delete(TopicUseHistory).where(
                        TopicUseHistory.editorial_project_id == project.id
                    )
                )
                await session.delete(project)
            node = await session.get(TopicStrategyNode, node_id)
            assert node is not None
            node.generation_count = count_before
            node.last_generated_at = None

    asyncio.run(cleanup())
    asyncio.run(database.dispose())
