"""Destructive legacy strategy reset acceptance coverage."""

import asyncio
import os
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import func, select

from alembic import command
from app.content_strategy.domain import (
    ContentStatus,
    LectureAngle,
    TopicOrigin,
    TopicWorkspaceStatus,
)
from app.content_strategy.models import (
    ContentTopic,
    EditorialProject,
    TopicStrategy,
    TopicStrategyNode,
    TopicUseHistory,
)
from app.content_strategy.strategy_service import TopicStrategyService
from app.db.session import Database
from app.research.models import ResearchProject

pytestmark = pytest.mark.skipif(
    not os.environ.get("EMTEDAD_DATABASE_URL"),
    reason="EMTEDAD_DATABASE_URL is required",
)


@pytest.mark.integration
def test_legacy_strategy_reset_preserves_dynamic_topics_and_projects(
    phase2_database_url: str,
) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", phase2_database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    database = Database(phase2_database_url)

    async def exercise() -> None:
        async with database.transaction() as session:
            strategy = TopicStrategy(
                version_number=1,
                title="Legacy",
                status="APPROVED",
                source_hash="a" * 64,
                grounding={"source": "test"},
            )
            session.add(strategy)
            await session.flush()
            node = TopicStrategyNode(
                strategy_id=strategy.id,
                node_type="TOPIC",
                stable_key="legacy-topic",
                title="Legacy topic",
                human_question="What continues?",
                rationale="test",
                ordinal=1,
                grounding={},
                generation_count=1,
            )
            topic = ContentTopic(
                stable_key=f"dynamic-{uuid4().hex}",
                title="Dynamic topic",
                human_question="What is new?",
                primary_concept_key="pattern",
                life_domain="self",
                lecture_angle=LectureAngle.HUMAN_QUESTION,
                status=ContentStatus.PLANNED,
                origin=TopicOrigin.USER_CREATED,
                semantic_hash="b" * 64,
                workspace_status=TopicWorkspaceStatus.LATER,
            )
            session.add_all([node, topic])
            await session.flush()
            research = ResearchProject(
                human_question="What continues?", created_by="test"
            )
            session.add(research)
            await session.flush()
            project = EditorialProject(
                strategy_node_id=node.id,
                title=node.title,
                human_question=node.human_question or node.title,
                research_project_id=research.id,
                status="RESEARCH_PENDING",
            )
            session.add(project)
            await session.flush()
            session.add(
                TopicUseHistory(
                    strategy_node_id=node.id,
                    editorial_project_id=project.id,
                )
            )

        result = await TopicStrategyService(database).reset_legacy(confirm=True)
        assert result["fixed_topics"] == 1
        async with database.transaction() as session:
            assert await session.scalar(select(TopicStrategy)) is None
            assert await session.scalar(select(TopicStrategyNode)) is None
            assert await session.scalar(select(TopicUseHistory)) is None
            preserved_topic = await session.scalar(
                select(ContentTopic).where(ContentTopic.title == "Dynamic topic")
            )
            assert preserved_topic is not None
            preserved_project = await session.scalar(select(EditorialProject))
            assert preserved_project is not None
            assert preserved_project.strategy_node_id is None
            assert preserved_project.strategy_topic_snapshot is not None
            assert preserved_project.research_project_id == research.id

        second = await TopicStrategyService(database).reset_legacy(confirm=True)
        assert second["strategies"] == 0
        assert second["nodes"] == 0
        async with database.transaction() as session:
            assert (
                int(
                    await session.scalar(select(func.count()).select_from(ContentTopic))
                    or 0
                )
                == 1
            )

    try:
        asyncio.run(exercise())
    finally:
        asyncio.run(database.dispose())
