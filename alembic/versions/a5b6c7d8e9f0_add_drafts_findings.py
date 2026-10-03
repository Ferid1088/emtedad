"""add script drafts and review findings

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a5b6c7d8e9f0"
down_revision: str | None = "f4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    draft_status = postgresql.ENUM(
        "DRAFT",
        "IN_REVIEW",
        "REVISED",
        "APPROVED",
        "ARCHIVED",
        name="script_draft_status",
        schema="content",
    )
    severity = postgresql.ENUM(
        "INFO",
        "WARNING",
        "BLOCKER",
        name="finding_severity",
        schema="content",
    )
    finding_status = postgresql.ENUM(
        "OPEN",
        "ADDRESSED",
        "WAIVED",
        name="finding_status",
        schema="content",
    )

    op.create_table(
        "script_drafts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "content_brief_id",
            sa.Uuid(),
            sa.ForeignKey("content.content_briefs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "narrative_plan_id",
            sa.Uuid(),
            sa.ForeignKey("content.narrative_plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("editorial_project_id", sa.Uuid(), nullable=True),
        sa.Column(
            "language",
            sa.String(length=16),
            nullable=False,
            server_default="fa",
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "variant_index",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", draft_status, nullable=False, server_default="DRAFT"),
        sa.Column(
            "provenance_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("target_duration_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "actual_word_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "estimated_duration_seconds",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("content_brief_id", "language", "version_number"),
        sa.CheckConstraint("version_number > 0", name="positive_draft_version"),
        sa.CheckConstraint("variant_index >= 0", name="nonnegative_variant"),
        sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="valid_draft_hash"),
        schema="content",
    )
    op.create_index(
        "ix_script_drafts_content_brief_id",
        "script_drafts",
        ["content_brief_id"],
        schema="content",
    )

    op.create_table(
        "review_findings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "script_draft_id",
            sa.Uuid(),
            sa.ForeignKey("content.script_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("critic_role", sa.String(length=64), nullable=False),
        sa.Column("severity", severity, nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "correction_constraint",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "status",
            finding_status,
            nullable=False,
            server_default="OPEN",
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
        "ix_review_findings_script_draft_id",
        "review_findings",
        ["script_draft_id"],
        schema="content",
    )


def downgrade() -> None:
    op.drop_table("review_findings", schema="content")
    op.drop_table("script_drafts", schema="content")
    for name in (
        "script_draft_status",
        "finding_severity",
        "finding_status",
    ):
        postgresql.ENUM(name=name, schema="content").drop(
            op.get_bind(), checkfirst=True
        )
