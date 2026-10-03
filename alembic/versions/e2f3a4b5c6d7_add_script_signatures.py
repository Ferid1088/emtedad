"""add script signatures

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "script_signatures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "editorial_channel_id",
            sa.Uuid(),
            sa.ForeignKey("content.editorial_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "topic_candidate_id",
            sa.Uuid(),
            sa.ForeignKey("content.topic_candidates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=False),
        sa.Column("angle", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "concept_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "story_unit_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "argument_signature",
            sa.String(length=1024),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "hook_type",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "ending_type",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="content",
    )
    op.create_index(
        "ix_script_signatures_editorial_channel_id",
        "script_signatures",
        ["editorial_channel_id"],
        schema="content",
    )
    op.create_index(
        "ix_script_signatures_topic_candidate_id",
        "script_signatures",
        ["topic_candidate_id"],
        schema="content",
    )


def downgrade() -> None:
    op.drop_table("script_signatures", schema="content")
