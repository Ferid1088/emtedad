"""add isolated speech structure interpretation tables

Revision ID: c7d8e9f0a1b2
Revises: b5c6d7e8f9a0
"""


import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c7d8e9f0a1b2"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    schema = "knowledge"
    op.create_table(
        "speech_structures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("title", sa.String(1024), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge.sources.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"], ["knowledge.source_versions.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("source_id", "version"),
        schema=schema,
    )
    op.create_index(
        "ix_speech_structures_source_id",
        "speech_structures",
        ["source_id"],
        schema=schema,
    )
    op.create_index(
        "ix_speech_structures_source_version_id",
        "speech_structures",
        ["source_version_id"],
        schema=schema,
    )
    op.create_table(
        "speech_structure_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("speech_structure_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("model", sa.String(256), nullable=False),
        sa.Column("prompt_version", sa.String(128), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["speech_structure_id"],
            ["knowledge.speech_structures.id"],
            ondelete="CASCADE",
        ),
        schema=schema,
    )
    op.create_index(
        "ix_speech_structure_runs_structure_id",
        "speech_structure_runs",
        ["speech_structure_id"],
        schema=schema,
    )
    op.create_table(
        "speech_sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("speech_structure_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True)),
        sa.Column("root_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section_number", sa.String(64), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(1024), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("section_role", sa.String(32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["speech_structure_id"],
            ["knowledge.speech_structures.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["knowledge.speech_sections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["root_id"], ["knowledge.speech_sections.id"], ondelete="CASCADE"
        ),
        schema=schema,
    )
    for name, column in (
        ("ix_speech_sections_structure_id", "speech_structure_id"),
        ("ix_speech_sections_parent_id", "parent_id"),
        ("ix_speech_sections_root_id", "root_id"),
    ):
        op.create_index(name, "speech_sections", [column], schema=schema)
    op.create_table(
        "speech_section_segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("section_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["section_id"], ["knowledge.speech_sections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_segment_id"], ["knowledge.source_segments.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("section_id", "source_segment_id", "relation_type"),
        sa.UniqueConstraint("section_id", "sequence"),
        schema=schema,
    )
    op.create_index(
        "ix_speech_section_segments_section_id",
        "speech_section_segments",
        ["section_id"],
        schema=schema,
    )
    op.create_index(
        "ix_speech_section_segments_source_segment_id",
        "speech_section_segments",
        ["source_segment_id"],
        schema=schema,
    )


def downgrade() -> None:
    schema = "knowledge"
    op.drop_table("speech_section_segments", schema=schema)
    op.drop_table("speech_sections", schema=schema)
    op.drop_table("speech_structure_runs", schema=schema)
    op.drop_table("speech_structures", schema=schema)
