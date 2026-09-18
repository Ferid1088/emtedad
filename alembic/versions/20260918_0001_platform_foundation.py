"""Establish pgvector and bounded PostgreSQL namespaces.

Revision ID: 20260918_0001
Revises:
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db.base import SCHEMA_NAMES

revision: str = "20260918_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enable pgvector and create empty phase-owned namespaces."""

    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    for schema_name in SCHEMA_NAMES:
        op.execute(sa.schema.CreateSchema(schema_name, if_not_exists=True))


def downgrade() -> None:
    """Remove only empty Phase 1 schemas; retain the shared extension safely."""

    for schema_name in reversed(SCHEMA_NAMES):
        op.execute(sa.schema.DropSchema(schema_name, cascade=False, if_exists=True))

    # Extensions are cluster-level resources and may predate this application.
    # Retaining pgvector avoids deleting a resource that this revision cannot
    # prove it owns. A disposable database is removed in its entirety by tests.
