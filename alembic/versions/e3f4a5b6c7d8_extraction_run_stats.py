"""Add stats_json to extraction_runs (rejected-proposal telemetry).

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "extraction_runs",
        sa.Column(
            "stats_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema="knowledge",
    )


def downgrade() -> None:
    op.drop_column("extraction_runs", "stats_json", schema="knowledge")
