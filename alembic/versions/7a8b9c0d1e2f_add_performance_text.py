"""Add provider-specific performance text beside editorial voice text."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7a8b9c0d1e2f"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "editorial_language_tracks",
        sa.Column("elevenlabs_performance_text", sa.Text(), nullable=True),
        schema="content",
    )


def downgrade() -> None:
    op.drop_column(
        "editorial_language_tracks",
        "elevenlabs_performance_text",
        schema="content",
    )
