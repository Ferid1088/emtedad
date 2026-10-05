"""owner-decision provenance + true revision counting

Revision ID: k3c4d5e6f7g8
Revises: j2b3c4d5e6f7
Create Date: 2026-10-05

Phase 7 audit corrections:

- ``review_findings.resolution_actor`` / ``resolution_note`` persist WHO
  resolved a finding and WHY — a waiver is an owner editorial decision,
  so the actor and justification must be recorded, and agent
  recommendations stay distinguishable from owner waivers.
- ``script_drafts.revision_cycle`` records which owner-authorized review
  cycle produced this draft through ``revise_draft``. The revision
  budget counts *revisions* (persisted drafts with this column set), not
  completed ReviewRuns — reviews, failed runs, duplicates, retries, and
  regenerations never consume it.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "k3c4d5e6f7g8"
down_revision: str | None = "j2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTENT = "content"


def upgrade() -> None:
    op.add_column(
        "script_drafts",
        sa.Column("revision_cycle", sa.Integer(), nullable=True),
        schema=CONTENT,
    )
    op.add_column(
        "review_findings",
        sa.Column("resolution_actor", sa.String(64), nullable=True),
        schema=CONTENT,
    )
    op.add_column(
        "review_findings",
        sa.Column("resolution_note", sa.Text(), nullable=True),
        schema=CONTENT,
    )


def downgrade() -> None:
    op.drop_column("review_findings", "resolution_note", schema=CONTENT)
    op.drop_column("review_findings", "resolution_actor", schema=CONTENT)
    op.drop_column("script_drafts", "revision_cycle", schema=CONTENT)
