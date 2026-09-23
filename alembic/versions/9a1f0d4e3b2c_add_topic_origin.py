"""Add origin metadata to content topics.

Revision ID: 9a1f0d4e3b2c
Revises: 6338422a845d
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "9a1f0d4e3b2c"
down_revision = "6338422a845d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    topic_origin = postgresql.ENUM(
        "AI_SUGGESTED", "USER_CREATED", "LEGACY", name="topic_origin", schema="content"
    )
    topic_origin.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "content_topics",
        sa.Column(
            "origin",
            topic_origin,
            nullable=False,
            server_default=sa.text("'LEGACY'"),
        ),
        schema="content",
    )
    op.alter_column("content_topics", "origin", server_default=None, schema="content")


def downgrade() -> None:
    op.drop_column("content_topics", "origin", schema="content")
    op.execute("DROP TYPE IF EXISTS content.topic_origin")
