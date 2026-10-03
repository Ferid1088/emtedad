"""add generic master origin and provenance fields

Revision ID: b7c8d9e0f1a2
Revises: b6c7d8e9f0a1
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "b6c7d8e9f0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Generic section role for CONTENT_BRIEF productions.
    op.execute(
        "ALTER TYPE content.lecture_section_role "
        "ADD VALUE IF NOT EXISTS 'NARRATIVE_BEAT'"
    )
    origin = postgresql.ENUM(
        "LEGACY_AYIN",
        "LEGACY_LESSON",
        "CONTENT_BRIEF",
        name="master_origin_type",
        schema="content",
    )
    origin.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "lecture_master_versions",
        sa.Column("origin_type", origin, nullable=True),
        schema="content",
    )
    op.add_column(
        "lecture_master_versions",
        sa.Column(
            "content_brief_id",
            sa.Uuid(),
            sa.ForeignKey("content.content_briefs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        schema="content",
    )
    op.add_column(
        "lecture_master_versions",
        sa.Column(
            "channel_strategy_version_id",
            sa.Uuid(),
            sa.ForeignKey("content.channel_strategy_versions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        schema="content",
    )
    op.add_column(
        "lecture_master_versions",
        sa.Column(
            "argument_plan_id",
            sa.Uuid(),
            sa.ForeignKey("content.argument_plans.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        schema="content",
    )
    op.add_column(
        "lecture_master_versions",
        sa.Column(
            "narrative_plan_id",
            sa.Uuid(),
            sa.ForeignKey("content.narrative_plans.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        schema="content",
    )
    op.add_column(
        "lecture_master_versions",
        sa.Column(
            "evidence_matrix_id",
            sa.Uuid(),
            sa.ForeignKey("content.evidence_matrices.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        schema="content",
    )
    op.create_index(
        "ix_lecture_master_versions_content_brief_id",
        "lecture_master_versions",
        ["content_brief_id"],
        schema="content",
    )
    op.create_check_constraint(
        "content_brief_origin",
        "lecture_master_versions",
        "origin_type IS DISTINCT FROM 'CONTENT_BRIEF'::content.master_origin_type"
        " OR content_brief_id IS NOT NULL",
        schema="content",
    )
    op.add_column(
        "script_drafts",
        sa.Column(
            "lecture_master_version_id",
            sa.Uuid(),
            sa.ForeignKey("content.lecture_master_versions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        schema="content",
    )


def downgrade() -> None:
    op.drop_column("script_drafts", "lecture_master_version_id", schema="content")
    op.drop_constraint(
        "ck_lecture_master_versions_content_brief_origin",
        "lecture_master_versions",
        schema="content",
    )
    op.drop_index(
        "ix_lecture_master_versions_content_brief_id",
        table_name="lecture_master_versions",
        schema="content",
    )
    for column in (
        "evidence_matrix_id",
        "narrative_plan_id",
        "argument_plan_id",
        "channel_strategy_version_id",
        "content_brief_id",
        "origin_type",
    ):
        op.drop_column("lecture_master_versions", column, schema="content")
    postgresql.ENUM(name="master_origin_type", schema="content").drop(
        op.get_bind(), checkfirst=True
    )
