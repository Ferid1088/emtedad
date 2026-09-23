"""Add research-bound Persian editorial drafts and review findings."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "editorial_projects",
        sa.Column("research_package_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="content",
    )
    op.add_column(
        "editorial_projects",
        sa.Column("semantic_master_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="content",
    )
    op.create_foreign_key(
        "fk_editorial_projects_research_package",
        "editorial_projects",
        "research_packages",
        ["research_package_id"],
        ["id"],
        source_schema="content",
        referent_schema="content",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_editorial_projects_semantic_master",
        "editorial_projects",
        "lecture_master_versions",
        ["semantic_master_id"],
        ["id"],
        source_schema="content",
        referent_schema="content",
        ondelete="RESTRICT",
    )
    op.create_table(
        "persian_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "editorial_project_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("parent_draft_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("semantic_master_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("variant_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("owner_prompt", sa.Text(), nullable=True),
        sa.Column("target_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("target_word_count_min", sa.Integer(), nullable=False),
        sa.Column("target_word_count_max", sa.Integer(), nullable=False),
        sa.Column("actual_word_count", sa.Integer(), nullable=False),
        sa.Column("estimated_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("speaking_rate_profile", sa.String(length=64), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["editorial_project_id"],
            ["content.editorial_projects.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_draft_id"], ["content.persian_drafts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["semantic_master_id"],
            ["content.lecture_master_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="content",
    )
    op.create_table(
        "persian_review_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("blocking", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["draft_id"], ["content.persian_drafts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="content",
    )


def downgrade() -> None:
    op.drop_table("persian_review_findings", schema="content")
    op.drop_table("persian_drafts", schema="content")
    op.drop_constraint(
        "fk_editorial_projects_semantic_master",
        "editorial_projects",
        schema="content",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_editorial_projects_research_package",
        "editorial_projects",
        schema="content",
        type_="foreignkey",
    )
    op.drop_column("editorial_projects", "semantic_master_id", schema="content")
    op.drop_column("editorial_projects", "research_package_id", schema="content")
