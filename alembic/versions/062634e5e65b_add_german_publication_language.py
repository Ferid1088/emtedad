"""add German publication language

Revision ID: 062634e5e65b
Revises: 41c0efc31348
Create Date: 2026-09-23 01:14:55.131243
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '062634e5e65b'
down_revision: str | None = '41c0efc31348'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE core.language_code ADD VALUE IF NOT EXISTS 'de'")
    op.execute("ALTER TYPE retrieval.query_language ADD VALUE IF NOT EXISTS 'de'")


def downgrade() -> None:
    # PostgreSQL enum values are additive. Retaining the value on downgrade is
    # safer than rebuilding shared enums and invalidating existing records.
    pass
