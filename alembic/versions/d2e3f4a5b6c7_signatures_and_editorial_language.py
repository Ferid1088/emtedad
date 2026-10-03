"""script signature provenance + channel editorial language

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-10-03

Additive only:
- ``content.script_signatures``: link to the approved ScriptDraft
  (unique → idempotent signature creation), optional editorial project,
  and a content hash pinning the approved text.
- ``content.channel_strategy_versions``: ``editorial_language`` — the
  channel's working language for mined topics/questions, independent of
  source language or publication target language.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: str | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "script_signatures",
        sa.Column(
            "script_draft_id",
            sa.UUID(),
            sa.ForeignKey("content.script_drafts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        schema="content",
    )
    op.add_column(
        "script_signatures",
        sa.Column("editorial_project_id", sa.UUID(), nullable=True),
        schema="content",
    )
    op.add_column(
        "script_signatures",
        sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
        schema="content",
    )
    op.create_unique_constraint(
        "uq_script_signatures_draft",
        "script_signatures",
        ["script_draft_id"],
        schema="content",
    )
    op.add_column(
        "channel_strategy_versions",
        sa.Column(
            "editorial_language",
            sa.String(8),
            nullable=False,
            server_default="fa",
        ),
        schema="content",
    )


def downgrade() -> None:
    op.drop_column("channel_strategy_versions", "editorial_language", schema="content")
    op.drop_constraint(
        "uq_script_signatures_draft", "script_signatures", schema="content"
    )
    op.drop_column("script_signatures", "content_hash", schema="content")
    op.drop_column("script_signatures", "editorial_project_id", schema="content")
    op.drop_column("script_signatures", "script_draft_id", schema="content")
