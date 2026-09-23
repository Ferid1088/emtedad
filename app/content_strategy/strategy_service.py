"""Grounded, versioned Emtedad topic strategy and production workspace."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content_strategy.models import (
    ContentTopic,
    EditorialProject,
    TopicStrategy,
    TopicStrategyNode,
    TopicUseHistory,
)
from app.db.session import Database
from app.research.models import ResearchProject


class TopicStrategyService:
    """Build a fixed tree from the currently stored Ayin ontology."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def current(self) -> tuple[TopicStrategy | None, list[TopicStrategyNode]]:
        async with self.database.transaction() as session:
            strategy = await session.scalar(
                select(TopicStrategy).order_by(TopicStrategy.version_number.desc())
            )
            nodes = (
                list(
                    await session.scalars(
                        select(TopicStrategyNode)
                        .where(TopicStrategyNode.strategy_id == strategy.id)
                        .order_by(TopicStrategyNode.ordinal, TopicStrategyNode.title)
                    )
                )
                if strategy
                else []
            )
            return strategy, nodes

    async def generate(self) -> UUID:
        raise ValueError(
            "legacy strategy generation is disabled; the replacement strategy "
            "will be introduced in a later checkpoint"
        )

    async def reset_legacy(self, *, confirm: bool = False) -> dict[str, int | bool]:
        """Remove only the legacy fixed strategy tree.

        Historical editorial projects are detached and retain a JSON snapshot;
        dynamic topics and all research/editorial artifacts remain untouched.
        Without ``confirm`` this is a read-only preview.
        """

        async with self.database.transaction() as session:
            strategies = list(await session.scalars(select(TopicStrategy)))
            nodes = list(await session.scalars(select(TopicStrategyNode)))
            histories = list(await session.scalars(select(TopicUseHistory)))
            projects = list(
                await session.scalars(
                    select(EditorialProject).where(
                        EditorialProject.strategy_node_id.is_not(None)
                    )
                )
            )
            counts: dict[str, int | bool] = {
                "confirmed": confirm,
                "strategies": len(strategies),
                "nodes": len(nodes),
                "roots": sum(item.node_type == "ROOT" for item in nodes),
                "branches": sum(item.node_type == "BRANCH" for item in nodes),
                "fixed_topics": sum(item.node_type == "TOPIC" for item in nodes),
                "usage_records": len(histories),
                "historical_projects": len(projects),
            }
            if not confirm or not nodes and not strategies:
                return counts

            strategy_by_id = {item.id: item for item in strategies}
            node_by_id = {item.id: item for item in nodes}
            for project in projects:
                node_id = project.strategy_node_id
                if node_id is None:
                    continue
                node = node_by_id.get(node_id)
                if node is None:
                    continue
                strategy = strategy_by_id.get(node.strategy_id)
                branch = node_by_id.get(node.parent_id) if node.parent_id else None
                if (
                    branch is not None
                    and branch.node_type != "BRANCH"
                    and branch.parent_id is not None
                ):
                    branch = node_by_id.get(branch.parent_id)
                project.strategy_topic_snapshot = {
                    "strategy_id": str(strategy.id) if strategy else None,
                    "strategy_version": strategy.version_number if strategy else None,
                    "strategy_title": strategy.title if strategy else None,
                    "strategy_status": strategy.status if strategy else None,
                    "node_id": str(node.id),
                    "node_title": node.title,
                    "node_question": node.human_question,
                    "branch_title": branch.title if branch else None,
                    "captured_at": datetime.now(UTC).isoformat(),
                }
                project.strategy_node_id = None
            await session.flush()
            if histories:
                await session.execute(delete(TopicUseHistory))
            await session.execute(delete(TopicStrategyNode))
            await session.execute(delete(TopicStrategy))
            return counts

    async def approve(self, strategy_id: UUID) -> None:
        async with self.database.transaction() as session:
            strategy = await session.get(TopicStrategy, strategy_id)
            if strategy is None:
                raise ValueError("strategy not found")
            strategy.status = "APPROVED"
            strategy.approved_at = datetime.now(UTC)

    async def use_topic(
        self,
        node_id: UUID,
        *,
        owner_prompt: str | None = None,
        target_duration_minutes: int | None = None,
    ) -> UUID:
        async with self.database.transaction() as session:
            node = await session.get(TopicStrategyNode, node_id)
            if node is None or node.node_type != "TOPIC":
                raise ValueError("strategy topic not found")
            project = await self._create_project(
                session,
                title=node.title,
                human_question=node.human_question or node.title,
                strategy_node_id=node.id,
                owner_prompt=owner_prompt,
                target_duration_minutes=target_duration_minutes,
            )
            node.generation_count += 1
            node.last_generated_at = datetime.now(UTC)
            session.add(
                TopicUseHistory(
                    strategy_node_id=node.id,
                    editorial_project_id=project.id,
                    owner_prompt=owner_prompt,
                    target_duration_minutes=target_duration_minutes,
                )
            )
            return project.id

    async def use_content_topic(
        self,
        topic_id: UUID,
        *,
        owner_prompt: str | None = None,
        target_duration_minutes: int | None = None,
    ) -> UUID:
        """Enter a dynamic topic through the same production workspace as the tree."""

        async with self.database.transaction() as session:
            topic = await session.get(ContentTopic, topic_id)
            if topic is None:
                raise ValueError("topic not found")
            active_statuses = {"RESEARCH_PENDING", "IN_RESEARCH", "DRAFT"}
            existing = await session.scalar(
                select(EditorialProject)
                .where(
                    EditorialProject.content_topic_id == topic.id,
                    EditorialProject.status.in_(active_statuses),
                )
                .order_by(EditorialProject.created_at.desc())
            )
            if existing is not None:
                return existing.id
            project = await self._create_project(
                session,
                title=topic.title,
                human_question=topic.human_question or topic.title,
                content_topic_id=topic.id,
                owner_prompt=owner_prompt,
                target_duration_minutes=target_duration_minutes,
            )
            return project.id

    async def _create_project(
        self,
        session: AsyncSession,
        *,
        title: str,
        human_question: str,
        strategy_node_id: UUID | None = None,
        content_topic_id: UUID | None = None,
        owner_prompt: str | None = None,
        target_duration_minutes: int | None = None,
    ) -> EditorialProject:
        project = EditorialProject(
            strategy_node_id=strategy_node_id,
            content_topic_id=content_topic_id,
            title=title,
            human_question=human_question,
            owner_prompt=owner_prompt,
            target_duration_minutes=target_duration_minutes,
            status="RESEARCH_PENDING",
        )
        session.add(project)
        await session.flush()
        research_project = ResearchProject(
            human_question=human_question,
            created_by="owner",
        )
        session.add(research_project)
        await session.flush()
        project.research_project_id = research_project.id
        return project

    async def metrics(self, strategy_id: UUID) -> dict[str, int]:
        async with self.database.transaction() as session:
            total = int(
                await session.scalar(
                    select(func.count(TopicStrategyNode.id)).where(
                        TopicStrategyNode.strategy_id == strategy_id,
                        TopicStrategyNode.node_type == "TOPIC",
                    )
                )
                or 0
            )
            used = int(
                await session.scalar(
                    select(func.count(TopicStrategyNode.id)).where(
                        TopicStrategyNode.strategy_id == strategy_id,
                        TopicStrategyNode.node_type == "TOPIC",
                        TopicStrategyNode.generation_count > 0,
                    )
                )
                or 0
            )
            return {"total": total, "used": used, "unused": total - used}
