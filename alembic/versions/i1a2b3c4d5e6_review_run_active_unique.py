"""partial unique index: one active review run per exact draft state

Revision ID: i1a2b3c4d5e6
Revises: h0a1b2c3d4e5
Create Date: 2025-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "i1a2b3c4d5e6"
down_revision: str | None = "h0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # At most one PENDING/RUNNING run may exist for the same draft row at
    # the same content hash — concurrent review POSTs cannot create
    # ambiguous active runs. Completed history is unrestricted, and a new
    # hash (manual edit) may start a fresh run while an old-hash run is
    # still in flight.
    op.create_index(
        "uq_review_runs_active_draft",
        "review_runs",
        ["script_draft_id", "draft_hash"],
        schema="content",
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'RUNNING')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_review_runs_active_draft",
        table_name="review_runs",
        schema="content",
    )
