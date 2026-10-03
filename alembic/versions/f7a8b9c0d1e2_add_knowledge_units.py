"""Add Knowledge Units anchored to structure nodes and segment spans.

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f7a8b9c0d1e2"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    unit_type = postgresql.ENUM(
        "CLAIM",
        "DEFINITION",
        "EXPLANATION",
        "STORY",
        "CASE_STUDY",
        "EXAMPLE",
        "EXPERIMENT",
        "QUOTE",
        "COUNTERARGUMENT",
        "OPEN_QUESTION",
        "SYNTHESIS",
        name="knowledge_unit_type",
        schema="knowledge",
        create_type=False,
    )
    evidence_level = postgresql.ENUM(
        "PRIMARY",
        "SECONDARY",
        "ANECDOTAL",
        "NONE",
        name="evidence_level",
        schema="knowledge",
        create_type=False,
    )
    claim_type = postgresql.ENUM(
        "FACT",
        "INTERPRETATION",
        "OPINION",
        "NORMATIVE",
        "UNKNOWN",
        name="claim_type",
        schema="knowledge",
        create_type=False,
    )
    unit_type.create(op.get_bind(), checkfirst=True)
    evidence_level.create(op.get_bind(), checkfirst=True)
    claim_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "knowledge_units",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("structure_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unit_type", unit_type, nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("full_text", sa.Text(), nullable=False),
        sa.Column("start_segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("end_segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("atomic", sa.Boolean(), nullable=False),
        sa.Column("evidence_level", evidence_level, nullable=False),
        sa.Column("claim_type", claim_type, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("extraction_version", sa.String(length=128), nullable=False),
        sa.Column("extraction_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name="valid_content_hash"
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["knowledge.source_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["structure_node_id", "source_version_id"],
            [
                "knowledge.source_structure_nodes.id",
                "knowledge.source_structure_nodes.source_version_id",
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
        sa.UniqueConstraint(
            "source_version_id",
            "unit_type",
            "content_hash",
            name="uq_knowledge_unit_dedup",
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_knowledge_units_source_version_id",
        "knowledge_units",
        ["source_version_id"],
        schema="knowledge",
    )
    op.create_index(
        "ix_knowledge_units_extraction_run_id",
        "knowledge_units",
        ["extraction_run_id"],
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_units_extraction_run_id",
        table_name="knowledge_units",
        schema="knowledge",
    )
    op.drop_index(
        "ix_knowledge_units_source_version_id",
        table_name="knowledge_units",
        schema="knowledge",
    )
    op.drop_table("knowledge_units", schema="knowledge")
    op.execute("DROP TYPE IF EXISTS knowledge.claim_type")
    op.execute("DROP TYPE IF EXISTS knowledge.evidence_level")
    op.execute("DROP TYPE IF EXISTS knowledge.knowledge_unit_type")
