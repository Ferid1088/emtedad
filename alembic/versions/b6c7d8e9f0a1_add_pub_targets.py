"""add publication targets

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b6c7d8e9f0a1"
down_revision: str | None = "a5b6c7d8e9f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    status = postgresql.ENUM(
        "ACTIVE",
        "PAUSED",
        "RETIRED",
        name="publication_target_status",
        schema="content",
    )
    op.create_table(
        "publication_targets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "editorial_channel_id",
            sa.Uuid(),
            sa.ForeignKey("content.editorial_channels.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "platform",
            sa.String(length=64),
            nullable=False,
            server_default="youtube",
        ),
        sa.Column(
            "language",
            sa.String(length=16),
            nullable=False,
            server_default="fa",
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", status, nullable=False, server_default="ACTIVE"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="content",
    )
    op.create_index(
        "ix_publication_targets_editorial_channel_id",
        "publication_targets",
        ["editorial_channel_id"],
        schema="content",
    )


def downgrade() -> None:
    op.drop_table("publication_targets", schema="content")
    postgresql.ENUM(name="publication_target_status", schema="content").drop(
        op.get_bind(), checkfirst=True
    )
