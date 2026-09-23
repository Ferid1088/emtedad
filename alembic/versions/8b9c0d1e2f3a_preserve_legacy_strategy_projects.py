"""Preserve historical projects when the legacy strategy tree is removed."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "8b9c0d1e2f3a"
down_revision = "7a8b9c0d1e2f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "editorial_projects",
        sa.Column("strategy_topic_snapshot", postgresql.JSONB(), nullable=True),
        schema="content",
    )
    op.drop_constraint(
        "fk_editorial_projects_strategy_node_id_topic_strategy_nodes",
        "editorial_projects",
        schema="content",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_editorial_projects_strategy_node_id_topic_strategy_nodes",
        "editorial_projects",
        "topic_strategy_nodes",
        ["strategy_node_id"],
        ["id"],
        source_schema="content",
        referent_schema="content",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_editorial_projects_strategy_node_id_topic_strategy_nodes",
        "editorial_projects",
        schema="content",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_editorial_projects_strategy_node_id_topic_strategy_nodes",
        "editorial_projects",
        "topic_strategy_nodes",
        ["strategy_node_id"],
        ["id"],
        source_schema="content",
        referent_schema="content",
        ondelete="RESTRICT",
    )
    op.drop_column("editorial_projects", "strategy_topic_snapshot", schema="content")
