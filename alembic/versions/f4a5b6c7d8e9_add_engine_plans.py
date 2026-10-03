"""add argument and narrative plans

Revision ID: f4a5b6c7d8e9
Revises: f3a4b5c6d7e8
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f4a5b6c7d8e9"
down_revision: str | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    argument_status = postgresql.ENUM(
        "DRAFT",
        "READY",
        "SUPERSEDED",
        name="argument_plan_status",
        schema="content",
    )
    narrative_status = postgresql.ENUM(
        "DRAFT",
        "READY",
        "SUPERSEDED",
        name="narrative_plan_status",
        schema="content",
    )

    op.create_table(
        "argument_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "content_brief_id",
            sa.Uuid(),
            sa.ForeignKey("content.content_briefs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "evidence_matrix_id",
            sa.Uuid(),
            sa.ForeignKey("content.evidence_matrices.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            argument_status,
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "provenance_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("content_brief_id", "version_number"),
        sa.CheckConstraint("version_number > 0", name="positive_plan_version"),
        sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="valid_plan_hash"),
        schema="content",
    )
    op.create_index(
        "ix_argument_plans_content_brief_id",
        "argument_plans",
        ["content_brief_id"],
        schema="content",
    )

    op.create_table(
        "argument_plan_sections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "argument_plan_id",
            sa.Uuid(),
            sa.ForeignKey("content.argument_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column(
            "claim_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "evidence_item_ids",
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
            "counterargument_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "transition_intent",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "must_include",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "must_not_claim",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.UniqueConstraint("argument_plan_id", "ordinal"),
        sa.CheckConstraint("ordinal > 0", name="positive_section_ordinal"),
        schema="content",
    )
    op.create_index(
        "ix_argument_plan_sections_argument_plan_id",
        "argument_plan_sections",
        ["argument_plan_id"],
        schema="content",
    )

    op.create_table(
        "narrative_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "content_brief_id",
            sa.Uuid(),
            sa.ForeignKey("content.content_briefs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "argument_plan_id",
            sa.Uuid(),
            sa.ForeignKey("content.argument_plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            narrative_status,
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "provenance_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("content_brief_id", "version_number"),
        sa.CheckConstraint("version_number > 0", name="positive_narr_version"),
        sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="valid_narr_hash"),
        schema="content",
    )
    op.create_index(
        "ix_narrative_plans_content_brief_id",
        "narrative_plans",
        ["content_brief_id"],
        schema="content",
    )

    op.create_table(
        "narrative_plan_sections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "narrative_plan_id",
            sa.Uuid(),
            sa.ForeignKey("content.narrative_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("narrative_role", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column(
            "target_seconds",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
        sa.Column(
            "argument_section_ids",
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
            "emotional_function",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column("transition_in", sa.Text(), nullable=False, server_default=""),
        sa.Column("transition_out", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "opening_method",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "ending_method",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
        sa.UniqueConstraint("narrative_plan_id", "ordinal"),
        sa.CheckConstraint("ordinal > 0", name="positive_narr_ordinal"),
        schema="content",
    )
    op.create_index(
        "ix_narrative_plan_sections_narrative_plan_id",
        "narrative_plan_sections",
        ["narrative_plan_id"],
        schema="content",
    )


def downgrade() -> None:
    op.drop_table("narrative_plan_sections", schema="content")
    op.drop_table("narrative_plans", schema="content")
    op.drop_table("argument_plan_sections", schema="content")
    op.drop_table("argument_plans", schema="content")
    for name in ("argument_plan_status", "narrative_plan_status"):
        postgresql.ENUM(name=name, schema="content").drop(
            op.get_bind(), checkfirst=True
        )
