"""Add versioned Emtedad strategy tree and editorial workspace."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topic_strategies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("grounding", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_number"),
        schema="content",
    )
    op.create_table(
        "topic_strategy_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("node_type", sa.String(length=16), nullable=False),
        sa.Column("stable_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("human_question", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("grounding", postgresql.JSONB(), nullable=False),
        sa.Column("generation_count", sa.Integer(), nullable=False),
        sa.Column("last_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["content.topic_strategies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["content.topic_strategy_nodes.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("strategy_id", "stable_key"),
        schema="content",
    )
    op.create_index(
        "ix_topic_strategy_nodes_strategy_id",
        "topic_strategy_nodes",
        ["strategy_id"],
        schema="content",
    )
    op.create_table(
        "editorial_projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_node_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_topic_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("research_project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("human_question", sa.Text(), nullable=False),
        sa.Column("owner_prompt", sa.Text(), nullable=True),
        sa.Column("target_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["strategy_node_id"],
            ["content.topic_strategy_nodes.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["content_topic_id"], ["content.content_topics.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["research_project_id"],
            ["content.research_projects.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="content",
    )
    op.create_table(
        "topic_use_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "editorial_project_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("owner_prompt", sa.Text(), nullable=True),
        sa.Column("target_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["strategy_node_id"],
            ["content.topic_strategy_nodes.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["editorial_project_id"],
            ["content.editorial_projects.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="content",
    )


def downgrade() -> None:
    op.drop_table("topic_use_history", schema="content")
    op.drop_table("editorial_projects", schema="content")
    op.drop_index(
        "ix_topic_strategy_nodes_strategy_id",
        table_name="topic_strategy_nodes",
        schema="content",
    )
    op.drop_table("topic_strategy_nodes", schema="content")
    op.drop_table("topic_strategies", schema="content")
