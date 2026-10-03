"""add content briefs

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    brief_status = postgresql.ENUM(
        "DRAFT",
        "READY",
        "LOCKED",
        "ARCHIVED",
        name="content_brief_status",
        schema="content",
    )
    op.create_table(
        "content_briefs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "topic_candidate_id",
            sa.Uuid(),
            sa.ForeignKey("content.topic_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "editorial_channel_id",
            sa.Uuid(),
            sa.ForeignKey("content.editorial_channels.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "strategy_version_id",
            sa.Uuid(),
            sa.ForeignKey("content.channel_strategy_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=False),
        sa.Column(
            "target_audience",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column("angle", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "primary_concepts_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "required_evidence_roles_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("preferred_story_role", sa.Text(), nullable=True),
        sa.Column("required_counterargument", sa.Text(), nullable=True),
        sa.Column(
            "forbidden_claims_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "forbidden_repetitions_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("target_duration_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            brief_status,
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "target_duration_minutes > 0", name="positive_target_duration"
        ),
        schema="content",
    )
    op.create_index(
        "ix_content_briefs_topic_candidate_id",
        "content_briefs",
        ["topic_candidate_id"],
        schema="content",
    )


def downgrade() -> None:
    op.drop_table("content_briefs", schema="content")
    postgresql.ENUM(name="content_brief_status", schema="content").drop(
        op.get_bind(), checkfirst=True
    )
