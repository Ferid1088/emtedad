"""add web_research_runs table for persisted research provenance

Revision ID: g9a0b1c2d3e4
Revises: g8a9b0c1d2e3
Create Date: 2025-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "g9a0b1c2d3e4"
down_revision: str | None = "g8a9b0c1d2e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "web_research_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content_brief_id", sa.Uuid(), nullable=True),
        sa.Column(
            "trigger",
            sa.String(length=32),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="OK"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("findings_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ingested_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "new_source_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["content_brief_id"],
            ["content.content_briefs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="ops",
    )
    op.create_index(
        "ix_web_research_runs_content_brief_id",
        "web_research_runs",
        ["content_brief_id"],
        schema="ops",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_web_research_runs_content_brief_id",
        table_name="web_research_runs",
        schema="ops",
    )
    op.drop_table("web_research_runs", schema="ops")
