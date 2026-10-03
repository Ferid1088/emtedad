"""add processing attempt counter to source_processing_states

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Retry bookkeeping for the canonical processing scheduler: one counter
    # per source, incremented on FAILED transitions, reset on success.
    op.add_column(
        "source_processing_states",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_column("source_processing_states", "attempt_count", schema="knowledge")
