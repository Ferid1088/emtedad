"""Add FTS search vector on knowledge units and unit embeddings.

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_units",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple', coalesce(title, '') || ' ' || "
                "coalesce(summary, '') || ' ' || coalesce(full_text, ''))",
                persisted=True,
            ),
            nullable=True,
        ),
        schema="knowledge",
    )
    op.create_index(
        "ix_knowledge_units_search_vector",
        "knowledge_units",
        ["search_vector"],
        schema="knowledge",
        postgresql_using="gin",
    )

    op.create_table(
        "knowledge_unit_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", VECTOR(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name="valid_content_hash"
        ),
        sa.CheckConstraint("kind IN ('SUMMARY', 'FULL_TEXT')", name="valid_kind"),
        sa.ForeignKeyConstraint(
            ["knowledge_unit_id"],
            ["knowledge.knowledge_units.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_model_id"],
            ["retrieval.embedding_models.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "knowledge_unit_id",
            "embedding_model_id",
            "kind",
            "content_hash",
        ),
        schema="retrieval",
    )
    op.create_index(
        "ix_knowledge_unit_embeddings_knowledge_unit_id",
        "knowledge_unit_embeddings",
        ["knowledge_unit_id"],
        schema="retrieval",
    )
    op.create_index(
        "ix_knowledge_unit_embeddings_embedding_model_id",
        "knowledge_unit_embeddings",
        ["embedding_model_id"],
        schema="retrieval",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_unit_embeddings_embedding_model_id",
        table_name="knowledge_unit_embeddings",
        schema="retrieval",
    )
    op.drop_index(
        "ix_knowledge_unit_embeddings_knowledge_unit_id",
        table_name="knowledge_unit_embeddings",
        schema="retrieval",
    )
    op.drop_table("knowledge_unit_embeddings", schema="retrieval")
    op.drop_index(
        "ix_knowledge_units_search_vector",
        table_name="knowledge_units",
        schema="knowledge",
    )
    op.drop_column("knowledge_units", "search_vector", schema="knowledge")
