"""patch-repair section ids on findings, protocol truth on call events

Revision ID: m5e6f7g8h9i0
Revises: l4d5e6f7g8h9
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "m5e6f7g8h9i0"
down_revision: str | None = "l4d5e6f7g8h9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "review_findings",
        sa.Column(
            "section_id", sa.String(length=32), nullable=False, server_default=""
        ),
        schema="content",
    )
    op.add_column(
        "llm_call_events",
        sa.Column("requested_protocol", sa.String(length=16), nullable=True),
        schema="ops",
    )
    op.add_column(
        "llm_call_events",
        sa.Column("actual_protocol", sa.String(length=16), nullable=True),
        schema="ops",
    )
    op.add_column(
        "llm_call_events",
        sa.Column(
            "fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        schema="ops",
    )
    op.add_column(
        "llm_call_events",
        sa.Column("fallback_reason", sa.String(length=64), nullable=True),
        schema="ops",
    )


def downgrade() -> None:
    op.drop_column("llm_call_events", "fallback_reason", schema="ops")
    op.drop_column("llm_call_events", "fallback_used", schema="ops")
    op.drop_column("llm_call_events", "actual_protocol", schema="ops")
    op.drop_column("llm_call_events", "requested_protocol", schema="ops")
    op.drop_column("review_findings", "section_id", schema="content")
