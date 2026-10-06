"""multi-model routing telemetry, semantic packages, pipeline runs

Revision ID: l4d5e6f7g8h9
Revises: k3c4d5e6f7g8
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "l4d5e6f7g8h9"
down_revision: str | None = "k3c4d5e6f7g8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PIPELINE_STAGES = (
    "PENDING",
    "SEMANTIC_ALIGNED",
    "COVERAGE_TRANSLATED",
    "NATIVE_DRAFTED",
    "NATIVE_REVIEW",
    "FIDELITY_REVIEW",
    "FINAL_FIDELITY",
    "DURATION_READY",
    "READY_FOR_VOICE",
    "BLOCKED",
    "STALE_SOURCE",
    "FAILED",
)


def upgrade() -> None:
    op.add_column(
        "script_drafts",
        sa.Column(
            "lineage", sa.String(length=16), nullable=False, server_default="primary"
        ),
        schema="content",
    )
    stage_enum = postgresql.ENUM(
        *_PIPELINE_STAGES,
        name="localization_pipeline_stage",
        schema="content",
    )
    stage_enum.create(op.get_bind())

    op.create_table(
        "llm_call_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("upstream_provider", sa.String(length=128), nullable=True),
        sa.Column(
            "agent_role", sa.String(length=64), nullable=False, server_default=""
        ),
        sa.Column("task", sa.String(length=128), nullable=False, server_default=""),
        sa.Column(
            "prompt_version", sa.String(length=64), nullable=False, server_default=""
        ),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("content_brief_id", sa.UUID(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schema_repairs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_kind", sa.String(length=64), nullable=True),
        sa.Column(
            "run_scope",
            sa.String(length=32),
            nullable=False,
            server_default="production",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="ops",
    )
    op.create_table(
        "localization_semantic_packages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("script_draft_id", sa.UUID(), nullable=False),
        sa.Column("content_brief_id", sa.UUID(), nullable=False),
        sa.Column("lecture_master_version_id", sa.UUID(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source_draft_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "provenance_json", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_by",
            sa.String(length=255),
            nullable=False,
            server_default="pipeline",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["script_draft_id"], ["content.script_drafts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["content_brief_id"], ["content.content_briefs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["lecture_master_version_id"],
            ["content.lecture_master_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "script_draft_id", "version_number", name="uq_semantic_package_version"
        ),
        sa.CheckConstraint("version_number > 0", name="positive_package_version"),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name="valid_package_hash"
        ),
        schema="content",
    )
    op.create_table(
        "localization_pipeline_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("semantic_package_id", sa.UUID(), nullable=False),
        sa.Column(
            "language",
            postgresql.ENUM(
                "fa",
                "de",
                "en",
                "ar",
                name="publication_language",
                schema="content",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "stage",
            postgresql.ENUM(
                *_PIPELINE_STAGES,
                name="localization_pipeline_stage",
                schema="content",
                create_type=False,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("script_draft_id", sa.UUID(), nullable=True),
        sa.Column(
            "fidelity_status",
            sa.String(length=32),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "native_status",
            sa.String(length=32),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("review_loop", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("work_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["semantic_package_id"],
            ["content.localization_semantic_packages.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["script_draft_id"], ["content.script_drafts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "semantic_package_id", "language", name="uq_pipeline_run_language"
        ),
        schema="content",
    )


def downgrade() -> None:
    op.drop_column("script_drafts", "lineage", schema="content")
    op.drop_table("localization_pipeline_runs", schema="content")
    op.drop_table("localization_semantic_packages", schema="content")
    op.drop_table("llm_call_events", schema="ops")
    postgresql.ENUM(name="localization_pipeline_stage", schema="content").drop(
        op.get_bind()
    )
