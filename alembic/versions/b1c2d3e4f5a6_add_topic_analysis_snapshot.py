"""Persist grounded topic analysis snapshots."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "7c4e2b1f6a90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "content_topics",
        "primary_concept_key",
        existing_type=sa.String(length=255),
        nullable=True,
        schema="content",
    )
    op.add_column(
        "content_topics",
        sa.Column("analysis_json", postgresql.JSONB(), nullable=True),
        schema="content",
    )


def downgrade() -> None:
    op.drop_column("content_topics", "analysis_json", schema="content")
    op.execute(
        "UPDATE content.content_topics SET primary_concept_key = 'unassigned' "
        "WHERE primary_concept_key IS NULL"
    )
    op.alter_column(
        "content_topics",
        "primary_concept_key",
        existing_type=sa.String(length=255),
        nullable=False,
        schema="content",
    )
