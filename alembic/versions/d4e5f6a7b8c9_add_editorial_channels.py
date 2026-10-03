"""Add editorial channels, versioned strategies, and resource links.

Revision ID: d4e5f6a7b8c9
Revises: c7d8e9f0a1b2
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    channel_status = postgresql.ENUM(
        "ACTIVE",
        "INACTIVE",
        name="editorial_channel_status",
        schema="content",
        create_type=False,
    )
    strategy_status = postgresql.ENUM(
        "DRAFT",
        "ACTIVE",
        "ARCHIVED",
        name="channel_strategy_status",
        schema="content",
        create_type=False,
    )
    resource_role = postgresql.ENUM(
        "FOUNDATIONAL",
        "PRIMARY",
        "SUPPORTING",
        "REFERENCE",
        name="channel_resource_role",
        schema="content",
        create_type=False,
    )
    channel_status.create(op.get_bind(), checkfirst=True)
    strategy_status.create(op.get_bind(), checkfirst=True)
    resource_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "editorial_channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", channel_status, nullable=False),
        sa.Column("icon", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        schema="content",
    )
    op.create_table(
        "channel_strategy_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "editorial_channel_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("core_question", sa.Text(), nullable=False),
        sa.Column(
            "audience_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "audience_problems_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "domains_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "preferred_angles_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "forbidden_angles_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "source_policy_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "evidence_policy_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "topic_scoring_policy_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "narrative_policy_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "style_policy_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "hook_policy_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "ending_policy_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "agent_profile_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("status", strategy_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["editorial_channel_id"],
            ["content.editorial_channels.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("editorial_channel_id", "version_number"),
        schema="content",
    )
    op.create_index(
        "ix_channel_strategy_versions_editorial_channel_id",
        "channel_strategy_versions",
        ["editorial_channel_id"],
        schema="content",
    )
    op.create_index(
        "uq_channel_strategy_one_active",
        "channel_strategy_versions",
        ["editorial_channel_id"],
        unique=True,
        schema="content",
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_table(
        "editorial_channel_resources",
        sa.Column(
            "editorial_channel_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relevance", sa.Float(), nullable=False),
        sa.Column("role", resource_role, nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["editorial_channel_id"],
            ["content.editorial_channels.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["knowledge.sources.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("editorial_channel_id", "source_id"),
        schema="content",
    )


def downgrade() -> None:
    op.drop_table("editorial_channel_resources", schema="content")
    op.drop_index(
        "uq_channel_strategy_one_active",
        table_name="channel_strategy_versions",
        schema="content",
    )
    op.drop_index(
        "ix_channel_strategy_versions_editorial_channel_id",
        table_name="channel_strategy_versions",
        schema="content",
    )
    op.drop_table("channel_strategy_versions", schema="content")
    op.drop_table("editorial_channels", schema="content")
    op.execute("DROP TYPE IF EXISTS content.channel_resource_role")
    op.execute("DROP TYPE IF EXISTS content.channel_strategy_status")
    op.execute("DROP TYPE IF EXISTS content.editorial_channel_status")
