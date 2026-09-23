"""Add persistent dynamic topic discovery batches and workspace state."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f6a7b8c9d0e1"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topic_suggestion_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("owner_instruction", sa.Text(), nullable=True),
        sa.Column("generator", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("corpus_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="content",
    )
    op.add_column(
        "content_topics",
        sa.Column(
            "workspace_status",
            sa.String(length=32),
            nullable=False,
            server_default="NEW",
        ),
        schema="content",
    )
    op.add_column(
        "content_topics",
        sa.Column(
            "suggestion_batch_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        schema="content",
    )
    op.create_foreign_key(
        "fk_content_topics_suggestion_batch",
        "content_topics",
        "topic_suggestion_batches",
        ["suggestion_batch_id"],
        ["id"],
        source_schema="content",
        referent_schema="content",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_content_topics_suggestion_batch", "content_topics", schema="content"
    )
    op.drop_column("content_topics", "suggestion_batch_id", schema="content")
    op.drop_column("content_topics", "workspace_status", schema="content")
    op.drop_table("topic_suggestion_batches", schema="content")
