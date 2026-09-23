"""Add approved-Persian sourced language tracks."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "editorial_language_tracks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("editorial_project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_persian_draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("semantic_master_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("display_text", sa.Text(), nullable=False),
        sa.Column("voice_ready_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("semantic_validation_status", sa.String(length=32), nullable=False),
        sa.Column("actual_word_count", sa.Integer(), nullable=False),
        sa.Column("estimated_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["editorial_project_id"], ["content.editorial_projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_persian_draft_id"], ["content.persian_drafts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["semantic_master_id"], ["content.lecture_master_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), schema="content",
    )


def downgrade() -> None:
    op.drop_table("editorial_language_tracks", schema="content")
