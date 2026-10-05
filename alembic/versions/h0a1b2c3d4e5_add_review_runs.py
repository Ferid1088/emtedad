"""add review_runs table and review_run_id on review_findings

Revision ID: h0a1b2c3d4e5
Revises: g9a0b1c2d3e4
Create Date: 2025-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "h0a1b2c3d4e5"
down_revision: str | None = "g9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REVIEW_RUN_STATUS = postgresql.ENUM(
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    name="review_run_status",
    schema="content",
)


def upgrade() -> None:
    op.create_table(
        "review_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content_brief_id", sa.Uuid(), nullable=False),
        sa.Column("script_draft_id", sa.Uuid(), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False),
        sa.Column("draft_hash", sa.String(length=64), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            _REVIEW_RUN_STATUS,
            nullable=False,
            server_default="RUNNING",
        ),
        sa.Column(
            "critic_profile_version",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "critics_requested", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "critics_completed", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("finding_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocking_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("major_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("minor_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_brief_id"],
            ["content.content_briefs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["script_draft_id"],
            ["content.script_drafts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_brief_id", "round_number"),
        schema="content",
    )
    op.create_index(
        "ix_review_runs_content_brief_id",
        "review_runs",
        ["content_brief_id"],
        schema="content",
    )
    op.create_index(
        "ix_review_runs_script_draft_id",
        "review_runs",
        ["script_draft_id"],
        schema="content",
    )
    op.add_column(
        "review_findings",
        sa.Column("review_run_id", sa.Uuid(), nullable=True),
        schema="content",
    )
    op.create_foreign_key(
        "fk_review_findings_review_run_id",
        "review_findings",
        "review_runs",
        ["review_run_id"],
        ["id"],
        source_schema="content",
        referent_schema="content",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_review_findings_review_run_id",
        "review_findings",
        ["review_run_id"],
        schema="content",
    )
    op.add_column(
        "evidence_matrices",
        sa.Column(
            "validation_report",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        schema="content",
    )
    # Duration target becomes fractional minutes (27.5 default).
    op.alter_column(
        "content_briefs",
        "target_duration_minutes",
        existing_type=sa.Integer(),
        type_=sa.Float(),
        schema="content",
    )
    op.alter_column(
        "script_drafts",
        "target_duration_minutes",
        existing_type=sa.Integer(),
        type_=sa.Float(),
        schema="content",
    )


def downgrade() -> None:
    op.drop_column("evidence_matrices", "validation_report", schema="content")
    op.alter_column(
        "script_drafts",
        "target_duration_minutes",
        existing_type=sa.Float(),
        type_=sa.Integer(),
        schema="content",
    )
    op.alter_column(
        "content_briefs",
        "target_duration_minutes",
        existing_type=sa.Float(),
        type_=sa.Integer(),
        schema="content",
    )
    op.drop_index(
        "ix_review_findings_review_run_id",
        table_name="review_findings",
        schema="content",
    )
    op.drop_constraint(
        "fk_review_findings_review_run_id",
        "review_findings",
        schema="content",
    )
    op.drop_column("review_findings", "review_run_id", schema="content")
    op.drop_index(
        "ix_review_runs_script_draft_id",
        table_name="review_runs",
        schema="content",
    )
    op.drop_index(
        "ix_review_runs_content_brief_id",
        table_name="review_runs",
        schema="content",
    )
    op.drop_table("review_runs", schema="content")
    _REVIEW_RUN_STATUS.drop(op.get_bind(), checkfirst=True)
