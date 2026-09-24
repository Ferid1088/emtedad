"""add lesson research plans and published channel ledger

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-09-24
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b5c6d7e8f9a0"
down_revision: str | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for value in (
        "EMPIRICAL_CONTEXT",
        "HISTORICAL_CONTEXT",
        "EXAMPLE",
        "ILLUSTRATION",
        "COUNTERARGUMENT",
        "CHALLENGE",
        "NON_EQUIVALENCE",
        "OPEN_QUESTION",
    ):
        op.execute(
            f"ALTER TYPE content.evidence_selection_role "
            f"ADD VALUE IF NOT EXISTS '{value}'"
        )

    op.alter_column(
        "research_plans",
        "ayin_spine_id",
        existing_type=sa.Uuid(),
        nullable=True,
        schema="content",
    )
    op.add_column(
        "research_plans",
        sa.Column("lesson_id", sa.String(length=64), nullable=True),
        schema="content",
    )
    op.add_column(
        "research_plans",
        sa.Column("lesson_canon_hash", sa.String(length=64), nullable=True),
        schema="content",
    )
    op.add_column(
        "research_plans",
        sa.Column(
            "lesson_content_package_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema="content",
    )
    op.add_column(
        "research_plans",
        sa.Column("human_question", sa.Text(), nullable=True),
        schema="content",
    )
    op.add_column(
        "research_plans",
        sa.Column(
            "query_provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="content",
    )
    op.create_index(
        op.f("ix_research_plans_lesson_id"),
        "research_plans",
        ["lesson_id"],
        unique=False,
        schema="content",
    )
    op.create_unique_constraint(
        "uq_research_plan_lesson_version",
        "research_plans",
        ["lesson_id", "lesson_canon_hash", "version_number"],
        schema="content",
    )
    op.create_check_constraint(
        "valid_research_plan_origin",
        "research_plans",
        "(ayin_spine_id IS NOT NULL AND lesson_id IS NULL "
        "AND lesson_canon_hash IS NULL AND lesson_content_package_snapshot IS NULL) "
        "OR (ayin_spine_id IS NULL AND lesson_id IS NOT NULL "
        "AND lesson_canon_hash IS NOT NULL "
        "AND lesson_content_package_snapshot IS NOT NULL)",
        schema="content",
    )

    op.drop_constraint(
        "valid_research_origin",
        "research_packages",
        type_="check",
        schema="content",
    )

    # Preserve already-frozen lesson packages by attaching a historical plan
    # snapshot before the stronger package-origin constraint is installed.
    bind = op.get_bind()
    historical = list(
        bind.execute(
            sa.text(
                "SELECT id, lesson_id, lesson_canon_hash, "
                "lesson_content_package_snapshot, retrieval_snapshot, input_hash "
                "FROM content.research_packages "
                "WHERE lesson_id IS NOT NULL AND research_plan_id IS NULL "
                "ORDER BY created_at, id"
            )
        ).mappings()
    )
    versions: defaultdict[tuple[str, str], int] = defaultdict(int)
    plan_table = sa.table(
        "research_plans",
        sa.column("id", sa.Uuid()),
        sa.column("ayin_spine_id", sa.Uuid()),
        sa.column("lesson_id", sa.String()),
        sa.column("lesson_canon_hash", sa.String()),
        sa.column("lesson_content_package_snapshot", postgresql.JSONB()),
        sa.column("human_question", sa.Text()),
        sa.column("query_provenance", postgresql.JSONB()),
        sa.column("version_number", sa.Integer()),
        sa.column("manasek_relevant", sa.Boolean()),
        sa.column("manasek_reason", sa.Text()),
        sa.column("prohibited_conflations", postgresql.JSONB()),
        sa.column("retrieval_configuration", postgresql.JSONB()),
        sa.column("input_hash", sa.String()),
        sa.column(
            "status",
            postgresql.ENUM(
                name="research_plan_status", schema="content", create_type=False
            ),
        ),
        sa.column("created_by", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        schema="content",
    )
    for item in historical:
        lesson_id = str(item["lesson_id"])
        canon_hash = str(item["lesson_canon_hash"])
        key = (lesson_id, canon_hash)
        versions[key] += 1
        plan_id = uuid4()
        snapshot = item["lesson_content_package_snapshot"] or {}
        retrieval = item["retrieval_snapshot"] or {}
        human_question = str(
            retrieval.get("human_question")
            or snapshot.get("central_question")
            or snapshot.get("canonical_lesson_title")
            or lesson_id
        )
        bind.execute(
            plan_table.insert().values(
                id=plan_id,
                ayin_spine_id=None,
                lesson_id=lesson_id,
                lesson_canon_hash=canon_hash,
                lesson_content_package_snapshot=snapshot,
                human_question=human_question,
                query_provenance={
                    "planner": "historical-lesson-research-backfill",
                    "derived_from": "FROZEN_RETRIEVAL_SNAPSHOT",
                    "generative_lanes": ["external"],
                },
                version_number=versions[key],
                manasek_relevant=False,
                manasek_reason=None,
                prohibited_conflations=[
                    "External knowledge may not redefine the canonical lesson"
                ],
                retrieval_configuration={"lanes": ["external"]},
                input_hash=str(item["input_hash"]),
                status="READY",
                created_by="migration-backfill",
                created_at=datetime.now(UTC),
            )
        )
        bind.execute(
            sa.text(
                "UPDATE content.research_packages "
                "SET research_plan_id = :plan_id WHERE id = :package_id"
            ),
            {"plan_id": plan_id, "package_id": item["id"]},
        )

    op.create_check_constraint(
        "valid_research_origin",
        "research_packages",
        "(lesson_id IS NOT NULL AND lesson_canon_hash IS NOT NULL "
        "AND lesson_content_package_version IS NOT NULL "
        "AND lesson_content_package_snapshot IS NOT NULL "
        "AND ayin_spine_id IS NULL AND research_plan_id IS NOT NULL "
        "AND canon_version_id IS NULL) OR "
        "(lesson_id IS NULL AND ayin_spine_id IS NOT NULL "
        "AND research_plan_id IS NOT NULL AND canon_version_id IS NOT NULL)",
        schema="content",
    )

    op.create_table(
        "channel_ledger_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("editorial_project_id", sa.Uuid(), nullable=False),
        sa.Column("published_draft_id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.String(length=64), nullable=True),
        sa.Column("published_title", sa.String(length=512), nullable=False),
        sa.Column("concept_keys", postgresql.JSONB(), nullable=False),
        sa.Column("canonical_definitions", postgresql.JSONB(), nullable=False),
        sa.Column("examples", postgresql.JSONB(), nullable=False),
        sa.Column("open_promises", postgresql.JSONB(), nullable=False),
        sa.Column("fulfilled_promises", postgresql.JSONB(), nullable=False),
        sa.Column("title_history", postgresql.JSONB(), nullable=False),
        sa.Column("coverage_summary", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name="valid_content_hash"
        ),
        sa.ForeignKeyConstraint(
            ["editorial_project_id"],
            ["content.editorial_projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["published_draft_id"],
            ["content.persian_drafts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("editorial_project_id"),
        schema="content",
    )
    op.create_index(
        op.f("ix_channel_ledger_entries_lesson_id"),
        "channel_ledger_entries",
        ["lesson_id"],
        unique=False,
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
                OR NEW.ayin_spine_id IS DISTINCT FROM OLD.ayin_spine_id
                OR NEW.research_plan_id IS DISTINCT FROM OLD.research_plan_id
                OR NEW.canon_version_id IS DISTINCT FROM OLD.canon_version_id
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
    op.drop_index(
        op.f("ix_channel_ledger_entries_lesson_id"),
        table_name="channel_ledger_entries",
        schema="content",
    )
    op.drop_table("channel_ledger_entries", schema="content")
    op.drop_constraint(
        "valid_research_origin",
        "research_packages",
        type_="check",
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
    op.drop_constraint(
        "valid_research_plan_origin",
        "research_plans",
        type_="check",
        schema="content",
    )
    op.drop_constraint(
        "uq_research_plan_lesson_version",
        "research_plans",
        type_="unique",
        schema="content",
    )
    op.drop_index(
        op.f("ix_research_plans_lesson_id"),
        table_name="research_plans",
        schema="content",
    )
    for column in (
        "query_provenance",
        "human_question",
        "lesson_content_package_snapshot",
        "lesson_canon_hash",
        "lesson_id",
    ):
        op.drop_column("research_plans", column, schema="content")
    op.alter_column(
        "research_plans",
        "ayin_spine_id",
        existing_type=sa.Uuid(),
        nullable=False,
        schema="content",
    )
