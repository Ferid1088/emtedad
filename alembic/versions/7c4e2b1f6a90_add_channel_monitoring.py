"""Add owner-controlled YouTube channel monitoring candidates.

Revision ID: 7c4e2b1f6a90
Revises: 9a1f0d4e3b2c
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "7c4e2b1f6a90"
down_revision = "9a1f0d4e3b2c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    status = postgresql.ENUM(
        "NEW",
        "SELECTED",
        "IMPORTING",
        "IMPORTED",
        "IGNORED",
        "FAILED",
        name="channel_candidate_status",
        schema="knowledge",
        create_type=False,
    )
    status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "monitored_channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("external_channel_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("channel_url", sa.Text(), nullable=False),
        sa.Column("handle", sa.String(length=255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_successful_check_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "external_channel_id"),
        schema="knowledge",
    )
    op.create_table(
        "channel_video_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("youtube_video_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", status, nullable=False),
        sa.Column("imported_source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["channel_id"], ["knowledge.monitored_channels.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["imported_source_id"], ["knowledge.sources.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel_id", "youtube_video_id"),
        schema="knowledge",
    )
    op.create_index(
        "ix_channel_video_candidates_channel_id",
        "channel_video_candidates",
        ["channel_id"],
        schema="knowledge",
    )
    op.create_index(
        "ix_channel_video_candidates_youtube_video_id",
        "channel_video_candidates",
        ["youtube_video_id"],
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_channel_video_candidates_youtube_video_id",
        table_name="channel_video_candidates",
        schema="knowledge",
    )
    op.drop_index(
        "ix_channel_video_candidates_channel_id",
        table_name="channel_video_candidates",
        schema="knowledge",
    )
    op.drop_table("channel_video_candidates", schema="knowledge")
    op.drop_table("monitored_channels", schema="knowledge")
    op.execute("DROP TYPE IF EXISTS knowledge.channel_candidate_status")
