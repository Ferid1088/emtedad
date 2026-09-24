"""add direct lesson-canon research packages

Revision ID: a4b5c6d7e8f9
Revises: 8b9c0d1e2f3a
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: str | None = "8b9c0d1e2f3a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "research_packages",
        "ayin_spine_id",
        existing_type=sa.Uuid(),
        nullable=True,
        schema="content",
    )
    op.alter_column(
        "research_packages",
        "research_plan_id",
        existing_type=sa.Uuid(),
        nullable=True,
        schema="content",
    )
    op.alter_column(
        "research_packages",
        "canon_version_id",
        existing_type=sa.Uuid(),
        nullable=True,
        schema="content",
    )
    op.add_column(
        "research_packages",
        sa.Column("lesson_id", sa.String(length=64), nullable=True),
        schema="content",
    )
    op.add_column(
        "research_packages",
        sa.Column("lesson_canon_hash", sa.String(length=64), nullable=True),
        schema="content",
    )
    op.add_column(
        "research_packages",
        sa.Column(
            "lesson_content_package_version", sa.String(length=32), nullable=True
        ),
        schema="content",
    )
    op.add_column(
        "research_packages",
        sa.Column(
            "lesson_content_package_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema="content",
    )
    op.create_index(
        op.f("ix_research_packages_lesson_id"),
        "research_packages",
        ["lesson_id"],
        unique=False,
        schema="content",
    )
    op.create_check_constraint(
        "valid_research_origin",
        "research_packages",
        "(lesson_id IS NOT NULL AND lesson_canon_hash IS NOT NULL "
        "AND lesson_content_package_version IS NOT NULL "
        "AND lesson_content_package_snapshot IS NOT NULL "
        "AND ayin_spine_id IS NULL AND research_plan_id IS NULL "
        "AND canon_version_id IS NULL) OR "
        "(lesson_id IS NULL AND ayin_spine_id IS NOT NULL "
        "AND research_plan_id IS NOT NULL AND canon_version_id IS NOT NULL)",
        schema="content",
    )
    op.alter_column(
        "lecture_master_versions",
        "canon_version_id",
        existing_type=sa.Uuid(),
        nullable=True,
        schema="content",
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION content.prevent_frozen_research_package_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status = 'FROZEN' AND (
                TG_OP = 'DELETE'
                OR NEW.status IS DISTINCT FROM OLD.status
                OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
                OR NEW.input_hash IS DISTINCT FROM OLD.input_hash
                OR NEW.retrieval_snapshot IS DISTINCT FROM OLD.retrieval_snapshot
                OR NEW.unresolved_issues IS DISTINCT FROM OLD.unresolved_issues
                OR NEW.lesson_id IS DISTINCT FROM OLD.lesson_id
                OR NEW.lesson_canon_hash IS DISTINCT FROM OLD.lesson_canon_hash
                OR NEW.lesson_content_package_version
                    IS DISTINCT FROM OLD.lesson_content_package_version
                OR NEW.lesson_content_package_snapshot
                    IS DISTINCT FROM OLD.lesson_content_package_snapshot
            ) THEN
                RAISE EXCEPTION 'frozen ResearchPackage % is immutable', OLD.id;
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION content.prevent_frozen_research_package_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status = 'FROZEN' AND (
                TG_OP = 'DELETE'
                OR NEW.status <> 'FROZEN'
                OR NEW.content_hash <> OLD.content_hash
                OR NEW.input_hash <> OLD.input_hash
                OR NEW.retrieval_snapshot <> OLD.retrieval_snapshot
                OR NEW.unresolved_issues <> OLD.unresolved_issues
            ) THEN
                RAISE EXCEPTION 'frozen ResearchPackage % is immutable', OLD.id;
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$;
        """
    )
    op.alter_column(
        "lecture_master_versions",
        "canon_version_id",
        existing_type=sa.Uuid(),
        nullable=False,
        schema="content",
    )
    op.drop_constraint(
        "valid_research_origin",
        "research_packages",
        type_="check",
        schema="content",
    )
    op.drop_index(
        op.f("ix_research_packages_lesson_id"),
        table_name="research_packages",
        schema="content",
    )
    for column in (
        "lesson_content_package_snapshot",
        "lesson_content_package_version",
        "lesson_canon_hash",
        "lesson_id",
    ):
        op.drop_column("research_packages", column, schema="content")
    for column in ("canon_version_id", "research_plan_id", "ayin_spine_id"):
        op.alter_column(
            "research_packages",
            column,
            existing_type=sa.Uuid(),
            nullable=False,
            schema="content",
        )
