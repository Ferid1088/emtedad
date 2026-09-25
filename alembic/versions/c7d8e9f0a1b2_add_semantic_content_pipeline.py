"""add hierarchical semantic content pipeline

Revision ID: c7d8e9f0a1b2
Revises: b5c6d7e8f9a0
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7d8e9f0a1b2"
down_revision: str | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "semantic_structure_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("window_count", sa.Integer(), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["knowledge.source_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_version_id",
            "input_hash",
            "prompt_version",
            "provider",
            "model",
            name="uq_semantic_structure_run_identity",
        ),
        sa.UniqueConstraint(
            "id",
            "source_version_id",
            name="uq_semantic_structure_run_id_source",
        ),
        sa.CheckConstraint(
            "input_hash ~ '^[0-9a-f]{64}$'",
            name="ck_semantic_structure_runs_valid_input_hash",
        ),
        sa.CheckConstraint(
            "output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'",
            name="ck_semantic_structure_runs_valid_output_hash",
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_semantic_structure_runs_source_status",
        "semantic_structure_runs",
        ["source_version_id", "status"],
        schema="knowledge",
    )

    op.create_table(
        "preferred_semantic_structure_runs",
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "semantic_structure_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["knowledge.source_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["semantic_structure_run_id", "source_version_id"],
            [
                "knowledge.semantic_structure_runs.id",
                "knowledge.semantic_structure_runs.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("source_version_id"),
        sa.UniqueConstraint(
            "semantic_structure_run_id",
            name="uq_preferred_semantic_structure_run",
        ),
        schema="knowledge",
    )

    op.create_table(
        "semantic_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "semantic_structure_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("path", sa.String(128), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("node_kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(1024), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("main_idea", sa.Text(), nullable=False),
        sa.Column("claims", postgresql.JSONB(), nullable=False),
        sa.Column("definitions", postgresql.JSONB(), nullable=False),
        sa.Column("examples", postgresql.JSONB(), nullable=False),
        sa.Column("qualifications", postgresql.JSONB(), nullable=False),
        sa.Column("start_sequence", sa.Integer(), nullable=False),
        sa.Column("end_sequence", sa.Integer(), nullable=False),
        sa.Column("start_seconds", sa.Numeric(12, 3), nullable=False),
        sa.Column("end_seconds", sa.Numeric(12, 3), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["semantic_structure_run_id"],
            ["knowledge.semantic_structure_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["knowledge.semantic_nodes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "semantic_structure_run_id",
            "path",
            name="uq_semantic_node_run_path",
        ),
        sa.UniqueConstraint(
            "semantic_structure_run_id",
            "ordinal",
            name="uq_semantic_node_run_ordinal",
        ),
        sa.CheckConstraint("depth > 0", name="ck_semantic_nodes_positive_depth"),
        sa.CheckConstraint("ordinal > 0", name="ck_semantic_nodes_positive_ordinal"),
        sa.CheckConstraint(
            "start_sequence > 0",
            name="ck_semantic_nodes_positive_start_sequence",
        ),
        sa.CheckConstraint(
            "end_sequence >= start_sequence",
            name="ck_semantic_nodes_valid_sequence_range",
        ),
        sa.CheckConstraint(
            "end_seconds >= start_seconds",
            name="ck_semantic_nodes_valid_time_range",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_semantic_nodes_valid_content_hash",
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_semantic_nodes_run_parent",
        "semantic_nodes",
        ["semantic_structure_run_id", "parent_id"],
        schema="knowledge",
    )
    op.create_index(
        "ix_semantic_nodes_run_depth",
        "semantic_nodes",
        ["semantic_structure_run_id", "depth"],
        schema="knowledge",
    )

    op.create_table(
        "semantic_node_segments",
        sa.Column("semantic_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["semantic_node_id"],
            ["knowledge.semantic_nodes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_segment_id"],
            ["knowledge.source_segments.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("semantic_node_id", "source_segment_id"),
        sa.UniqueConstraint(
            "semantic_node_id",
            "position",
            name="uq_semantic_node_segment_position",
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_semantic_node_segments_source_segment_id",
        "semantic_node_segments",
        ["source_segment_id"],
        schema="knowledge",
    )

    op.create_table(
        "generated_content_projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("target_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("target_word_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("chunking_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_expansion_mode", sa.String(32), nullable=False),
        sa.Column("plan", postgresql.JSONB(), nullable=False),
        sa.Column("retrieval_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("synthesis", postgresql.JSONB(), nullable=False),
        sa.Column("outline", postgresql.JSONB(), nullable=False),
        sa.Column("coherence_report", postgresql.JSONB(), nullable=False),
        sa.Column("final_script", sa.Text(), nullable=True),
        sa.Column("provenance_complete", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["chunking_run_id"],
            ["retrieval.chunking_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_model_id"],
            ["retrieval.embedding_models.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "target_duration_seconds >= 60",
            name="ck_generated_content_projects_valid_duration",
        ),
        sa.CheckConstraint(
            "target_word_count >= 100",
            name="ck_generated_content_projects_valid_word_count",
        ),
        schema="content",
    )

    op.create_table(
        "generated_content_sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(1024), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("transition_from_previous", sa.Text(), nullable=True),
        sa.Column("target_word_count", sa.Integer(), nullable=False),
        sa.Column("evidence_pack", postgresql.JSONB(), nullable=False),
        sa.Column("draft_text", sa.Text(), nullable=True),
        sa.Column("revision_notes", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["content.generated_content_projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "ordinal",
            name="uq_generated_content_section_ordinal",
        ),
        sa.CheckConstraint("ordinal > 0", name="ck_semantic_nodes_positive_ordinal"),
        sa.CheckConstraint(
            "target_word_count > 0",
            name="ck_generated_content_sections_positive_target_word_count",
        ),
        schema="content",
    )
    op.create_index(
        "ix_generated_content_sections_project_id",
        "generated_content_sections",
        ["project_id"],
        schema="content",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_generated_content_sections_project_id",
        table_name="generated_content_sections",
        schema="content",
    )
    op.drop_table("generated_content_sections", schema="content")
    op.drop_table("generated_content_projects", schema="content")
    op.drop_index(
        "ix_semantic_node_segments_source_segment_id",
        table_name="semantic_node_segments",
        schema="knowledge",
    )
    op.drop_table("semantic_node_segments", schema="knowledge")
    op.drop_index(
        "ix_semantic_nodes_run_depth",
        table_name="semantic_nodes",
        schema="knowledge",
    )
    op.drop_index(
        "ix_semantic_nodes_run_parent",
        table_name="semantic_nodes",
        schema="knowledge",
    )
    op.drop_table("semantic_nodes", schema="knowledge")
    op.drop_table("preferred_semantic_structure_runs", schema="knowledge")
    op.drop_index(
        "ix_semantic_structure_runs_source_status",
        table_name="semantic_structure_runs",
        schema="knowledge",
    )
    op.drop_table("semantic_structure_runs", schema="knowledge")
