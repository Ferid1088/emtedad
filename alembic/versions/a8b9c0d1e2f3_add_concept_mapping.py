"""Add unit-concept links and concept relationships (Phase 6).

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "a8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    relation_type = postgresql.ENUM(
        "RELATED_TO",
        "PART_OF",
        "CAUSES",
        "MAY_CAUSE",
        "CONTRASTS",
        "SUPPORTS",
        "CHALLENGES",
        "EXAMPLE_OF",
        name="concept_relation_type",
        schema="knowledge",
        create_type=False,
    )
    relation_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "knowledge_unit_concepts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("relation_role", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_unit_id"],
            ["knowledge.knowledge_units.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"],
            ["knowledge.external_concepts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("knowledge_unit_id", "concept_id", "relation_role"),
        schema="knowledge",
    )
    op.create_index(
        "ix_knowledge_unit_concepts_knowledge_unit_id",
        "knowledge_unit_concepts",
        ["knowledge_unit_id"],
        schema="knowledge",
    )
    op.create_index(
        "ix_knowledge_unit_concepts_concept_id",
        "knowledge_unit_concepts",
        ["concept_id"],
        schema="knowledge",
    )

    op.create_table(
        "concept_relationships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", relation_type, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "provenance_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="valid_confidence"
        ),
        sa.ForeignKeyConstraint(
            ["from_concept_id"],
            ["knowledge.external_concepts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_concept_id"],
            ["knowledge.external_concepts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("from_concept_id", "to_concept_id", "relation_type"),
        schema="knowledge",
    )
    op.create_index(
        "ix_concept_relationships_from_concept_id",
        "concept_relationships",
        ["from_concept_id"],
        schema="knowledge",
    )
    op.create_index(
        "ix_concept_relationships_to_concept_id",
        "concept_relationships",
        ["to_concept_id"],
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_concept_relationships_to_concept_id",
        table_name="concept_relationships",
        schema="knowledge",
    )
    op.drop_index(
        "ix_concept_relationships_from_concept_id",
        table_name="concept_relationships",
        schema="knowledge",
    )
    op.drop_table("concept_relationships", schema="knowledge")
    op.drop_index(
        "ix_knowledge_unit_concepts_concept_id",
        table_name="knowledge_unit_concepts",
        schema="knowledge",
    )
    op.drop_index(
        "ix_knowledge_unit_concepts_knowledge_unit_id",
        table_name="knowledge_unit_concepts",
        schema="knowledge",
    )
    op.drop_table("knowledge_unit_concepts", schema="knowledge")
    op.execute("DROP TYPE IF EXISTS knowledge.concept_relation_type")
