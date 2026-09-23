"""Grounded, versioned Emtedad topic strategy and production workspace."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select

from app.content_strategy.models import (
    EditorialProject,
    TopicStrategy,
    TopicStrategyNode,
    TopicUseHistory,
)
from app.core.ayin.models import AyinConcept, AyinConceptVersion
from app.db.session import Database


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


class TopicStrategyService:
    """Build a fixed tree from the currently stored Ayin ontology."""

    _question_forms = (
        "What does {concept} reveal about recurring human experience?",
        "How can {concept} be distinguished from its nearest confusion?",
        "What changes when we look at {concept} in everyday life?",
        "Which conditions make {concept} visible or difficult to see?",
        "How does {concept} relate to change without erasing continuity?",
        "What remains open when we ask about {concept}?",
        "How might relationships illuminate {concept}?",
        "What can external knowledge clarify about {concept}, and what can it "
        "not decide?",
        "How does {concept} shape attention to suffering and possibility?",
        "What would a careful practice of asking about {concept} require?",
    )

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
        async with self.database.transaction() as session:
            latest = await session.scalar(
                select(TopicStrategy).order_by(TopicStrategy.version_number.desc())
            )
            if latest and latest.status == "APPROVED":
                raise ValueError("approved strategy is immutable; create a new version")
            version = (latest.version_number + 1) if latest else 1
            concepts = list(
                await session.scalars(
                    select(AyinConcept).order_by(AyinConcept.stable_key)
                )
            )
            versions = list(
                await session.scalars(
                    select(AyinConceptVersion).order_by(
                        AyinConceptVersion.version_number.desc()
                    )
                )
            )
            latest_versions: dict[UUID, AyinConceptVersion] = {}
            for item in versions:
                latest_versions.setdefault(item.concept_id, item)
            selected = [
                concept for concept in concepts if concept.id in latest_versions
            ][:10]
            if not selected:
                raise ValueError("Ayin ontology has no grounded concepts")
            grounding = {
                "concept_ids": [str(item.id) for item in selected],
                "source": "core.ayin_concepts and core.ayin_concept_versions",
            }
            strategy = TopicStrategy(
                version_number=version,
                title="Emtedad / Ayin-e Emtedad",
                status="DRAFT",
                source_hash=_hash(grounding),
                grounding=grounding,
            )
            session.add(strategy)
            await session.flush()
            root = TopicStrategyNode(
                strategy_id=strategy.id,
                node_type="ROOT",
                stable_key="emtedad",
                title="Emtedad / Ayin-e Emtedad",
                rationale="Root of the grounded Emtedad strategy tree.",
                ordinal=0,
                grounding=grounding,
                generation_count=0,
            )
            session.add(root)
            await session.flush()
            ordinal = 1
            for branch_index, concept in enumerate(selected, 1):
                concept_version = latest_versions[concept.id]
                branch = TopicStrategyNode(
                    strategy_id=strategy.id,
                    parent_id=root.id,
                    node_type="BRANCH",
                    stable_key=f"branch-{concept.stable_key}",
                    title=concept.stable_key,
                    rationale=concept_version.definition,
                    ordinal=branch_index,
                    grounding={
                        "concept_id": str(concept.id),
                        "concept_version_id": str(concept_version.id),
                        "definition": concept_version.definition,
                        "source_passage_id": str(concept_version.source_passage_id),
                    },
                    generation_count=0,
                )
                session.add(branch)
                await session.flush()
                for leaf_index, form in enumerate(self._question_forms, 1):
                    question = form.format(concept=concept.stable_key)
                    session.add(
                        TopicStrategyNode(
                            strategy_id=strategy.id,
                            parent_id=branch.id,
                            node_type="TOPIC",
                            stable_key=f"{concept.stable_key}-{leaf_index}",
                            title=f"{concept.stable_key}: {question}",
                            human_question=question,
                            rationale=(
                                "Fixed topic grounded in the Ayin concept definition; "
                                "the question is an editorial angle, not a new "
                                "Ayin claim."
                            ),
                            ordinal=ordinal,
                            grounding=branch.grounding,
                            generation_count=0,
                        )
                    )
                    ordinal += 1
            return strategy.id

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
            project = EditorialProject(
                strategy_node_id=node.id,
                title=node.title,
                human_question=node.human_question or node.title,
                owner_prompt=owner_prompt,
                target_duration_minutes=target_duration_minutes,
                status="RESEARCH_PENDING",
            )
            session.add(project)
            await session.flush()
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
