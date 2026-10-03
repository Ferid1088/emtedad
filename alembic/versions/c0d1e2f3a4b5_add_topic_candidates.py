"""add topic candidates

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: str | None = "b9c0d1e2f3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    topic_status = postgresql.ENUM(
        "CANDIDATE",
        "SHORTLISTED",
        "SELECTED",
        "IN_RESEARCH",
        "READY_FOR_PRODUCTION",
        "IN_PRODUCTION",
        "PUBLISHED",
        "REJECTED",
        "ARCHIVED",
        "NEEDS_RESEARCH",
        name="topic_status",
        schema="content",
    )

    op.create_table(
        "topic_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "editorial_channel_id",
            sa.Uuid(),
            sa.ForeignKey("content.editorial_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "strategy_version_id",
            sa.Uuid(),
            sa.ForeignKey("content.channel_strategy_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("video_question", sa.Text(), nullable=False),
        sa.Column("tentative_thesis", sa.Text(), nullable=False),
        sa.Column("angle", sa.Text(), nullable=False),
        sa.Column("knowledge_coverage_score", sa.Float(), nullable=False),
        sa.Column("channel_fit_score", sa.Float(), nullable=False),
        sa.Column("novelty_score", sa.Float(), nullable=False),
        sa.Column("curiosity_score", sa.Float(), nullable=False),
        sa.Column("emotional_score", sa.Float(), nullable=False),
        sa.Column("practical_value_score", sa.Float(), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column(
            "status",
            topic_status,
            nullable=False,
            server_default="CANDIDATE",
        ),
        sa.Column(
            "provenance_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "knowledge_coverage_score >= 0 AND knowledge_coverage_score <= 1",
            name="valid_coverage",
        ),
        sa.CheckConstraint(
            "channel_fit_score >= 0 AND channel_fit_score <= 1",
            name="valid_channel_fit",
        ),
        sa.CheckConstraint(
            "novelty_score >= 0 AND novelty_score <= 1", name="valid_novelty"
        ),
        sa.CheckConstraint(
            "curiosity_score >= 0 AND curiosity_score <= 1",
            name="valid_curiosity",
        ),
        sa.CheckConstraint(
            "emotional_score >= 0 AND emotional_score <= 1",
            name="valid_emotional",
        ),
        sa.CheckConstraint(
            "practical_value_score >= 0 AND practical_value_score <= 1",
            name="valid_practical",
        ),
        sa.CheckConstraint("total_score >= 0 AND total_score <= 1", name="valid_total"),
        schema="content",
    )
    op.create_index(
        "ix_topic_candidates_editorial_channel_id",
        "topic_candidates",
        ["editorial_channel_id"],
        schema="content",
    )
    op.create_index(
        "ix_topic_candidates_total_score",
        "topic_candidates",
        ["total_score"],
        schema="content",
    )

    op.create_table(
        "topic_candidate_units",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "topic_candidate_id",
            sa.Uuid(),
            sa.ForeignKey("content.topic_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "knowledge_unit_id",
            sa.Uuid(),
            sa.ForeignKey("knowledge.knowledge_units.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "topic_candidate_id",
            "knowledge_unit_id",
            name="uq_topic_candidate_unit",
        ),
        schema="content",
    )
    op.create_index(
        "ix_topic_candidate_units_topic_candidate_id",
        "topic_candidate_units",
        ["topic_candidate_id"],
        schema="content",
    )
    op.create_index(
        "ix_topic_candidate_units_knowledge_unit_id",
        "topic_candidate_units",
        ["knowledge_unit_id"],
        schema="content",
    )

    op.create_table(
        "topic_candidate_concepts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "topic_candidate_id",
            sa.Uuid(),
            sa.ForeignKey("content.topic_candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "concept_id",
            sa.Uuid(),
            sa.ForeignKey("knowledge.external_concepts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "topic_candidate_id",
            "concept_id",
            name="uq_topic_candidate_concept",
        ),
        schema="content",
    )
    op.create_index(
        "ix_topic_candidate_concepts_topic_candidate_id",
        "topic_candidate_concepts",
        ["topic_candidate_id"],
        schema="content",
    )
    op.create_index(
        "ix_topic_candidate_concepts_concept_id",
        "topic_candidate_concepts",
        ["concept_id"],
        schema="content",
    )


def downgrade() -> None:
    op.drop_table("topic_candidate_concepts", schema="content")
    op.drop_table("topic_candidate_units", schema="content")
    op.drop_table("topic_candidates", schema="content")
    postgresql.ENUM(name="topic_status", schema="content").drop(
        op.get_bind(), checkfirst=True
    )
