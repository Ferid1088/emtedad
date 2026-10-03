"""add brief research origin and evidence matrices

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for value in (
        "PRIMARY_EVIDENCE",
        "SUPPORTING_EVIDENCE",
        "CASE_STUDY",
        "PHILOSOPHICAL_CONTEXT",
    ):
        op.execute(
            "ALTER TYPE content.evidence_selection_role "
            f"ADD VALUE IF NOT EXISTS '{value}'"
        )

    op.add_column(
        "research_plans",
        sa.Column(
            "content_brief_id",
            sa.Uuid(),
            sa.ForeignKey("content.content_briefs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        schema="content",
    )
    op.create_index(
        "ix_research_plans_content_brief_id",
        "research_plans",
        ["content_brief_id"],
        schema="content",
    )
    op.drop_constraint(
        "ck_research_plans_valid_research_plan_origin",
        "research_plans",
        schema="content",
    )
    op.create_check_constraint(
        "valid_research_plan_origin",
        "research_plans",
        "num_nonnulls(ayin_spine_id, lesson_id, content_brief_id) = 1 "
        "AND (lesson_id IS NULL OR (lesson_canon_hash IS NOT NULL "
        "AND lesson_content_package_snapshot IS NOT NULL))",
        schema="content",
    )

    op.add_column(
        "research_packages",
        sa.Column(
            "content_brief_id",
            sa.Uuid(),
            sa.ForeignKey("content.content_briefs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        schema="content",
    )
    op.create_index(
        "ix_research_packages_content_brief_id",
        "research_packages",
        ["content_brief_id"],
        schema="content",
    )
    op.drop_constraint(
        "ck_research_packages_valid_research_origin",
        "research_packages",
        schema="content",
    )
    op.create_check_constraint(
        "valid_research_origin",
        "research_packages",
        "research_plan_id IS NOT NULL AND ("
        "(lesson_id IS NOT NULL AND lesson_canon_hash IS NOT NULL "
        "AND lesson_content_package_version IS NOT NULL "
        "AND lesson_content_package_snapshot IS NOT NULL "
        "AND ayin_spine_id IS NULL AND canon_version_id IS NULL "
        "AND content_brief_id IS NULL) OR "
        "(lesson_id IS NULL AND ayin_spine_id IS NOT NULL "
        "AND canon_version_id IS NOT NULL AND content_brief_id IS NULL) OR "
        "(lesson_id IS NULL AND ayin_spine_id IS NULL "
        "AND canon_version_id IS NULL AND content_brief_id IS NOT NULL))",
        schema="content",
    )

    matrix_status = postgresql.ENUM(
        "DRAFT",
        "READY",
        "FROZEN",
        "SUPERSEDED",
        name="evidence_matrix_status",
        schema="content",
    )
    evidence_role = postgresql.ENUM(
        name="evidence_selection_role", schema="content", create_type=False
    )
    op.create_table(
        "evidence_matrices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "content_brief_id",
            sa.Uuid(),
            sa.ForeignKey("content.content_briefs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            matrix_status,
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("content_brief_id", "version_number"),
        sa.CheckConstraint("version_number > 0", name="positive_matrix_version"),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="valid_matrix_content_hash",
        ),
        schema="content",
    )
    op.create_index(
        "ix_evidence_matrices_content_brief_id",
        "evidence_matrices",
        ["content_brief_id"],
        schema="content",
    )

    op.create_table(
        "evidence_matrix_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "evidence_matrix_id",
            sa.Uuid(),
            sa.ForeignKey("content.evidence_matrices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("role", evidence_role, nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column(
            "claim_type",
            sa.String(length=64),
            nullable=False,
            server_default="UNKNOWN",
        ),
        sa.Column(
            "epistemic_status",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "supporting_unit_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "counterevidence_unit_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "alternative_unit_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "source_quality",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
        sa.Column("limitations", sa.Text(), nullable=False, server_default=""),
        sa.Column("allowed_wording", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "forbidden_wording",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("evidence_matrix_id", "ordinal"),
        sa.CheckConstraint("ordinal > 0", name="positive_matrix_ordinal"),
        schema="content",
    )
    op.create_index(
        "ix_evidence_matrix_items_evidence_matrix_id",
        "evidence_matrix_items",
        ["evidence_matrix_id"],
        schema="content",
    )


def downgrade() -> None:
    op.drop_table("evidence_matrix_items", schema="content")
    op.drop_table("evidence_matrices", schema="content")
    # Restore the pre-brief origin constraints (last defined by
    # b5c6d7e8f9a0); upgrade drops them by their emitted ck_-prefixed names,
    # so a second upgrade needs them back.
    op.drop_constraint(
        "ck_research_packages_valid_research_origin",
        "research_packages",
        schema="content",
    )
    op.create_check_constraint(
        "valid_research_origin",
        "research_packages",
        "research_plan_id IS NOT NULL AND ("
        "(lesson_id IS NOT NULL AND lesson_canon_hash IS NOT NULL "
        "AND lesson_content_package_version IS NOT NULL "
        "AND lesson_content_package_snapshot IS NOT NULL "
        "AND ayin_spine_id IS NULL AND canon_version_id IS NULL) OR "
        "(lesson_id IS NULL AND ayin_spine_id IS NOT NULL "
        "AND canon_version_id IS NOT NULL))",
        schema="content",
    )
    op.drop_constraint(
        "ck_research_plans_valid_research_plan_origin",
        "research_plans",
        schema="content",
    )
    op.create_check_constraint(
        "valid_research_plan_origin",
        "research_plans",
        "(ayin_spine_id IS NOT NULL AND lesson_id IS NULL "
        "AND lesson_canon_hash IS NULL "
        "AND lesson_content_package_snapshot IS NULL) OR "
        "(ayin_spine_id IS NULL AND lesson_id IS NOT NULL "
        "AND lesson_canon_hash IS NOT NULL "
        "AND lesson_content_package_snapshot IS NOT NULL)",
        schema="content",
    )
    op.drop_column("research_packages", "content_brief_id", schema="content")
    op.drop_column("research_plans", "content_brief_id", schema="content")
    postgresql.ENUM(name="evidence_matrix_status", schema="content").drop(
        op.get_bind(), checkfirst=True
    )
