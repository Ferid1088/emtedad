"""Add source processing states and hierarchical source structure nodes.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    processing_status = postgresql.ENUM(
        "INGESTED",
        "STRUCTURE_PENDING",
        "STRUCTURING",
        "STRUCTURED",
        "STRUCTURE_REVIEW_REQUIRED",
        "UNIT_EXTRACTION_PENDING",
        "UNIT_EXTRACTING",
        "UNIT_REVIEW_REQUIRED",
        "READY",
        "FAILED",
        name="source_processing_status",
        schema="knowledge",
        create_type=False,
    )
    node_type = postgresql.ENUM(
        "TOPIC",
        "SUBTOPIC",
        "ARGUMENT",
        "EXPLANATION",
        "STORY",
        "CASE_STUDY",
        "EXAMPLE",
        "EXPERIMENT",
        "QUESTION",
        "ANSWER",
        "COUNTERARGUMENT",
        "DEFINITION",
        "CONCLUSION",
        "OTHER",
        name="structure_node_type",
        schema="knowledge",
        create_type=False,
    )
    processing_status.create(op.get_bind(), checkfirst=True)
    node_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "source_processing_states",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", processing_status, nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge.sources.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["knowledge.source_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("source_id"),
        schema="knowledge",
    )

    op.create_table(
        "source_structure_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("node_type", node_type, nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("start_segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("end_segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_seconds", sa.Numeric(12, 3), nullable=True),
        sa.Column("end_seconds", sa.Numeric(12, 3), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("extraction_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("level >= 1", name="positive_level"),
        sa.CheckConstraint("ordinal > 0", name="positive_ordinal"),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["knowledge.source_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id", "parent_id"],
            [
                "knowledge.source_structure_nodes.source_version_id",
                "knowledge.source_structure_nodes.id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["start_segment_id", "source_version_id"],
            [
                "knowledge.source_segments.id",
                "knowledge.source_segments.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["end_segment_id", "source_version_id"],
            [
                "knowledge.source_segments.id",
                "knowledge.source_segments.source_version_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"],
            ["knowledge.extraction_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_version_id", "id"),
        schema="knowledge",
    )
    op.create_index(
        "ix_source_structure_nodes_source_version_id",
        "source_structure_nodes",
        ["source_version_id"],
        schema="knowledge",
    )
    op.create_index(
        "ix_source_structure_nodes_extraction_run_id",
        "source_structure_nodes",
        ["extraction_run_id"],
        schema="knowledge",
    )
    op.create_index(
        "uq_structure_node_sibling_ordinal",
        "source_structure_nodes",
        ["source_version_id", "parent_id", "ordinal"],
        unique=True,
        schema="knowledge",
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_structure_node_sibling_ordinal",
        table_name="source_structure_nodes",
        schema="knowledge",
    )
    op.drop_index(
        "ix_source_structure_nodes_extraction_run_id",
        table_name="source_structure_nodes",
        schema="knowledge",
    )
    op.drop_index(
        "ix_source_structure_nodes_source_version_id",
        table_name="source_structure_nodes",
        schema="knowledge",
    )
    op.drop_table("source_structure_nodes", schema="knowledge")
    op.drop_table("source_processing_states", schema="knowledge")
    op.execute("DROP TYPE IF EXISTS knowledge.structure_node_type")
    op.execute("DROP TYPE IF EXISTS knowledge.source_processing_status")
