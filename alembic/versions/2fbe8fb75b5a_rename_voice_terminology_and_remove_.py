"""rename voice terminology and remove audio QA

Revision ID: 2fbe8fb75b5a
Revises: 0aa9c737356c
Create Date: 2026-09-23 07:06:04.910084
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '2fbe8fb75b5a'
down_revision: str | None = '0aa9c737356c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE content.localization_status ADD VALUE IF NOT EXISTS 'NOT_READY_FOR_VOICE'")
    op.execute("ALTER TYPE content.localization_status ADD VALUE IF NOT EXISTS 'READY_FOR_VOICE'")
    op.drop_table('audio_pronunciation_qa', schema='content')


def downgrade() -> None:
    # Enum values are additive and the removed audio table is intentionally not
    # restored: Phase 9 is text-only and has no audio-QA implementation.
    pass
