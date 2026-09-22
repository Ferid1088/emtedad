"""correct manasek lecture foreign key

Revision ID: 41c0efc31348
Revises: 01376042ceb7
Create Date: 2026-09-23 00:58:39.639237
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '41c0efc31348'
down_revision: str | None = '01376042ceb7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE content.lecture_master_versions DROP CONSTRAINT IF EXISTS fk_lecture_master_versions_manasek_version_id_versions")
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_lecture_master_versions_manasek_version_id_ritual_versions'
            ) THEN
                ALTER TABLE content.lecture_master_versions
                ADD CONSTRAINT fk_lecture_master_versions_manasek_version_id_ritual_versions
                FOREIGN KEY (manasek_version_id) REFERENCES ritual.ritual_versions(id)
                ON DELETE RESTRICT;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE content.lecture_master_versions DROP CONSTRAINT IF EXISTS fk_lecture_master_versions_manasek_version_id_ritual_versions")
