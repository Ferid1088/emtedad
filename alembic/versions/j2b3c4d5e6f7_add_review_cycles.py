"""add owner-authorized review cycles

Revision ID: j2b3c4d5e6f7
Revises: i1a2b3c4d5e6
Create Date: 2026-10-04

The automatic revision budget applies per review cycle, not per brief
lifetime. ``review_cycles`` rows are the persisted owner authorization —
starting a cycle inserts exactly one row; every ReviewRun records the
cycle it belongs to. Pre-existing runs backfill to cycle 1 (the implicit
first cycle), so capped briefs stop at OWNER_REVIEW_REQUIRED until the
owner explicitly starts cycle 2.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "j2b3c4d5e6f7"
down_revision: str | None = "i1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_cycles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "content_brief_id",
            sa.Uuid(),
            sa.ForeignKey("content.content_briefs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cycle_number", sa.Integer(), nullable=False),
        sa.Column(
            "started_by", sa.String(length=64), nullable=False, server_default="owner"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("content_brief_id", "cycle_number"),
        schema="content",
    )
    op.create_index(
        "ix_review_cycles_content_brief_id",
        "review_cycles",
        ["content_brief_id"],
        schema="content",
    )
    # Runs that predate cycles belong to the implicit first cycle.
    op.add_column(
        "review_runs",
        sa.Column(
            "cycle_number",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        schema="content",
    )


def downgrade() -> None:
    op.drop_column("review_runs", "cycle_number", schema="content")
    op.drop_index(
        "ix_review_cycles_content_brief_id",
        table_name="review_cycles",
        schema="content",
    )
    op.drop_table("review_cycles", schema="content")
