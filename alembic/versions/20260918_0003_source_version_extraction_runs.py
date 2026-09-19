"""separate source versions from extraction runs

Revision ID: 20260918_0003
Revises: 20260918_0002
Create Date: 2026-09-18
"""

import hashlib
import json
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260918_0003"
down_revision: str | None = "20260918_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXTRACTION_CONFIGURATION = {"encoding": "UTF-8", "layout": True, "ocr": False}
_REVIEW_REASONS = (
    "suspicious_extraction",
    "heading_uncertainty",
    "broken_paragraph",
    "character_corruption",
    "page_layout_ambiguity",
    "possible_missing_content",
    "seed_provenance",
)


def _configuration_hash() -> str:
    encoded = json.dumps(
        _EXTRACTION_CONFIGURATION,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _passage_set_hash(passages: Sequence[sa.RowMapping]) -> str:
    digest = hashlib.sha256()
    for passage in passages:
        fingerprint = json.dumps(
            [
                passage["sequence"],
                passage["page_number"],
                passage["printed_page_label"],
                passage["heading_path"],
                passage["paragraph_index"],
                passage["content_hash"],
                passage["normalized_text"],
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        digest.update(fingerprint.encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _reject_duplicate_source_versions(connection: sa.Connection) -> None:
    duplicate = (
        connection.execute(
            sa.text(
                "SELECT document_id, source_file_hash, corpus_zone, "
                "COALESCE(semantic_version, '') AS semantic_version, count(*) AS count "
                "FROM core.canon_versions "
                "GROUP BY document_id, source_file_hash, corpus_zone, "
                "COALESCE(semantic_version, '') HAVING count(*) > 1 LIMIT 1"
            )
        )
        .mappings()
        .first()
    )
    if duplicate is not None:
        raise RuntimeError(
            "Phase 2.1 cannot safely infer how to merge duplicate same-SHA source "
            "versions. Recreate this pre-production import from the original PDF."
        )


def _backfill_extraction_runs(connection: sa.Connection) -> None:
    configuration = json.dumps(_EXTRACTION_CONFIGURATION, sort_keys=True)
    versions = connection.execute(
        sa.text(
            "SELECT v.id, v.importer_version, v.extractor_name, "
            "v.extractor_version, v.page_count, v.created_at, a.source_asset_id "
            "FROM core.canon_versions v "
            "JOIN core.canon_version_source_assets a ON a.canon_version_id = v.id"
        )
    ).mappings()
    for version in versions:
        passages = list(
            connection.execute(
                sa.text(
                    "SELECT sequence, page_number, printed_page_label, heading_path, "
                    "paragraph_index, content_hash, normalized_text "
                    "FROM core.canon_passages WHERE canon_version_id = :version_id "
                    "ORDER BY sequence"
                ),
                {"version_id": version["id"]},
            ).mappings()
        )
        if not passages:
            continue
        run_id = uuid4()
        importer_version = str(version["importer_version"]).split(":", 1)[0]
        connection.execute(
            sa.text(
                "INSERT INTO core.extraction_runs "
                "(id, canon_version_id, source_asset_id, importer_version, "
                "extractor_name, extractor_version, normalization_version, "
                "segmentation_version, configuration, configuration_hash, "
                "output_hash, page_count, passage_count, created_at) VALUES "
                "(:id, :version_id, :asset_id, :importer_version, :extractor_name, "
                ":extractor_version, 'persian-v1', 'logical-blocks-v1', "
                "CAST(:configuration AS jsonb), :configuration_hash, :output_hash, "
                ":page_count, :passage_count, :created_at)"
            ),
            {
                "id": run_id,
                "version_id": version["id"],
                "asset_id": version["source_asset_id"],
                "importer_version": importer_version,
                "extractor_name": version["extractor_name"],
                "extractor_version": version["extractor_version"],
                "configuration": configuration,
                "configuration_hash": _configuration_hash(),
                "output_hash": _passage_set_hash(passages),
                "page_count": version["page_count"],
                "passage_count": len(passages),
                "created_at": version["created_at"],
            },
        )
        connection.execute(
            sa.text(
                "UPDATE core.canon_passages SET extraction_run_id = :run_id "
                "WHERE canon_version_id = :version_id"
            ),
            {"run_id": run_id, "version_id": version["id"]},
        )
        connection.execute(
            sa.text(
                "UPDATE core.ayin_review_items SET extraction_run_id = :run_id, "
                "reason_for_review = CASE kind::text "
                "WHEN 'extraction_ambiguity' THEN "
                "'character_corruption'::core.ayin_review_reason "
                "WHEN 'structure_ambiguity' THEN "
                "'page_layout_ambiguity'::core.ayin_review_reason "
                "ELSE 'seed_provenance'::core.ayin_review_reason END "
                "WHERE canon_version_id = :version_id"
            ),
            {"run_id": run_id, "version_id": version["id"]},
        )
        connection.execute(
            sa.text(
                "UPDATE core.ayin_passage_reviews pr SET extraction_run_id = :run_id "
                "FROM core.canon_passages p "
                "WHERE pr.passage_id = p.id AND p.canon_version_id = :version_id"
            ),
            {"run_id": run_id, "version_id": version["id"]},
        )

    orphan_count = connection.scalar(
        sa.text(
            "SELECT (SELECT count(*) FROM core.canon_passages "
            "WHERE extraction_run_id IS NULL) + "
            "(SELECT count(*) FROM core.ayin_review_items "
            "WHERE extraction_run_id IS NULL OR reason_for_review IS NULL) + "
            "(SELECT count(*) FROM core.ayin_passage_reviews "
            "WHERE extraction_run_id IS NULL)"
        )
    )
    if orphan_count:
        raise RuntimeError(
            "Phase 2.1 could not backfill all extraction provenance; recreate the "
            "pre-production import from its source PDF."
        )


def upgrade() -> None:
    connection = op.get_bind()
    _reject_duplicate_source_versions(connection)

    review_reason = postgresql.ENUM(
        *_REVIEW_REASONS,
        name="ayin_review_reason",
        schema="core",
        create_type=False,
    )
    review_reason.create(connection, checkfirst=True)

    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canon_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_asset_id", sa.Uuid(), nullable=False),
        sa.Column("importer_version", sa.String(length=64), nullable=False),
        sa.Column("extractor_name", sa.String(length=64), nullable=False),
        sa.Column("extractor_version", sa.String(length=128), nullable=False),
        sa.Column("normalization_version", sa.String(length=64), nullable=False),
        sa.Column("segmentation_version", sa.String(length=64), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("output_hash", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("passage_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_extraction_runs_valid_configuration_hash"),
        ),
        sa.CheckConstraint(
            "output_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_extraction_runs_valid_output_hash"),
        ),
        sa.CheckConstraint(
            "page_count > 0", name=op.f("ck_extraction_runs_positive_page_count")
        ),
        sa.CheckConstraint(
            "passage_count > 0",
            name=op.f("ck_extraction_runs_positive_passage_count"),
        ),
        sa.ForeignKeyConstraint(
            ["canon_version_id", "source_asset_id"],
            [
                "core.canon_version_source_assets.canon_version_id",
                "core.canon_version_source_assets.source_asset_id",
            ],
            name=op.f(
                "fk_extraction_runs_canon_version_id_source_asset_id_canon_version_source_assets"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extraction_runs")),
        sa.UniqueConstraint(
            "canon_version_id",
            "importer_version",
            "extractor_name",
            "extractor_version",
            "normalization_version",
            "segmentation_version",
            "configuration_hash",
            name=op.f(
                "uq_extraction_runs_canon_version_id_importer_version_extractor_name_extractor_version_normalization_version_segmentation_version_configuration_hash"
            ),
        ),
        sa.UniqueConstraint(
            "id",
            "canon_version_id",
            name=op.f("uq_extraction_runs_id_canon_version_id"),
        ),
        schema="core",
    )
    op.create_index(
        op.f("ix_extraction_runs_canon_version_id"),
        "extraction_runs",
        ["canon_version_id"],
        schema="core",
    )

    op.add_column(
        "canon_passages",
        sa.Column("extraction_run_id", sa.Uuid(), nullable=True),
        schema="core",
    )
    op.add_column(
        "ayin_review_items",
        sa.Column("extraction_run_id", sa.Uuid(), nullable=True),
        schema="core",
    )
    op.add_column(
        "ayin_review_items",
        sa.Column("reason_for_review", review_reason, nullable=True),
        schema="core",
    )
    op.add_column(
        "ayin_review_items",
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        schema="core",
    )
    op.add_column(
        "ayin_review_items",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        schema="core",
    )
    op.add_column(
        "ayin_passage_reviews",
        sa.Column("extraction_run_id", sa.Uuid(), nullable=True),
        schema="core",
    )

    _backfill_extraction_runs(connection)

    op.alter_column(
        "canon_passages", "extraction_run_id", nullable=False, schema="core"
    )
    op.alter_column(
        "ayin_review_items", "extraction_run_id", nullable=False, schema="core"
    )
    op.alter_column(
        "ayin_review_items", "reason_for_review", nullable=False, schema="core"
    )
    op.alter_column(
        "ayin_passage_reviews", "extraction_run_id", nullable=False, schema="core"
    )

    op.drop_constraint(
        op.f("uq_canon_passages_canon_version_id_sequence"),
        "canon_passages",
        schema="core",
        type_="unique",
    )
    op.create_index(
        op.f("ix_canon_passages_extraction_run_id"),
        "canon_passages",
        ["extraction_run_id"],
        schema="core",
    )
    op.create_unique_constraint(
        op.f("uq_canon_passages_extraction_run_id_sequence"),
        "canon_passages",
        ["extraction_run_id", "sequence"],
        schema="core",
    )
    op.create_unique_constraint(
        op.f("uq_canon_passages_id_extraction_run_id"),
        "canon_passages",
        ["id", "extraction_run_id"],
        schema="core",
    )
    op.create_foreign_key(
        op.f("fk_canon_passages_extraction_run_id_canon_version_id_extraction_runs"),
        "canon_passages",
        "extraction_runs",
        ["extraction_run_id", "canon_version_id"],
        ["id", "canon_version_id"],
        source_schema="core",
        referent_schema="core",
        ondelete="RESTRICT",
    )

    op.create_check_constraint(
        op.f("ck_ayin_review_items_review_completion_metadata"),
        "ayin_review_items",
        "(status = 'open' AND reviewed_at IS NULL) OR "
        "(status IN ('resolved', 'dismissed') AND reviewed_at IS NOT NULL)",
        schema="core",
    )
    op.create_index(
        op.f("ix_ayin_review_items_extraction_run_id"),
        "ayin_review_items",
        ["extraction_run_id"],
        schema="core",
    )
    op.create_unique_constraint(
        op.f("uq_ayin_review_items_id_extraction_run_id"),
        "ayin_review_items",
        ["id", "extraction_run_id"],
        schema="core",
    )
    op.create_foreign_key(
        op.f("fk_ayin_review_items_extraction_run_id_canon_version_id_extraction_runs"),
        "ayin_review_items",
        "extraction_runs",
        ["extraction_run_id", "canon_version_id"],
        ["id", "canon_version_id"],
        source_schema="core",
        referent_schema="core",
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        op.f("fk_ayin_passage_reviews_passage_id_canon_passages"),
        "ayin_passage_reviews",
        schema="core",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_ayin_passage_reviews_review_item_id_ayin_review_items"),
        "ayin_passage_reviews",
        schema="core",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f(
            "fk_ayin_passage_reviews_review_item_id_extraction_run_id_ayin_review_items"
        ),
        "ayin_passage_reviews",
        "ayin_review_items",
        ["review_item_id", "extraction_run_id"],
        ["id", "extraction_run_id"],
        source_schema="core",
        referent_schema="core",
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_ayin_passage_reviews_passage_id_extraction_run_id_canon_passages"),
        "ayin_passage_reviews",
        "canon_passages",
        ["passage_id", "extraction_run_id"],
        ["id", "extraction_run_id"],
        source_schema="core",
        referent_schema="core",
        ondelete="RESTRICT",
    )

    op.create_table(
        "preferred_extraction_runs",
        sa.Column("canon_version_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column("selected_by", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["canon_version_id"],
            ["core.canon_versions.id"],
            name=op.f("fk_preferred_extraction_runs_canon_version_id_canon_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_run_id", "canon_version_id"],
            ["core.extraction_runs.id", "core.extraction_runs.canon_version_id"],
            name=op.f(
                "fk_preferred_extraction_runs_extraction_run_id_canon_version_id_extraction_runs"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "canon_version_id", name=op.f("pk_preferred_extraction_runs")
        ),
        schema="core",
    )

    op.drop_constraint(
        op.f("uq_canon_versions_document_id_source_file_hash_importer_version"),
        "canon_versions",
        schema="core",
        type_="unique",
    )
    op.create_index(
        "uq_canon_versions_source_identity",
        "canon_versions",
        [
            "document_id",
            "source_file_hash",
            "corpus_zone",
            sa.text("COALESCE(semantic_version, '')"),
        ],
        unique=True,
        schema="core",
    )
    op.drop_column("canon_versions", "extractor_name", schema="core")
    op.drop_column("canon_versions", "extractor_version", schema="core")
    op.drop_column("canon_versions", "importer_version", schema="core")
    op.drop_column("canon_versions", "page_count", schema="core")


def _reject_lossy_downgrade(connection: sa.Connection) -> None:
    invalid = connection.scalar(
        sa.text(
            "SELECT count(*) FROM core.canon_versions v WHERE "
            "(SELECT count(*) FROM core.extraction_runs r "
            "WHERE r.canon_version_id = v.id) <> 1"
        )
    )
    if invalid:
        raise RuntimeError(
            "Cannot downgrade Phase 2.1 without losing extraction-run history."
        )


def downgrade() -> None:
    connection = op.get_bind()
    _reject_lossy_downgrade(connection)

    op.add_column(
        "canon_versions",
        sa.Column("page_count", sa.Integer(), nullable=True),
        schema="core",
    )
    op.add_column(
        "canon_versions",
        sa.Column("importer_version", sa.String(length=64), nullable=True),
        schema="core",
    )
    op.add_column(
        "canon_versions",
        sa.Column("extractor_version", sa.String(length=128), nullable=True),
        schema="core",
    )
    op.add_column(
        "canon_versions",
        sa.Column("extractor_name", sa.String(length=64), nullable=True),
        schema="core",
    )
    connection.execute(
        sa.text(
            "UPDATE core.canon_versions v SET page_count = r.page_count, "
            "importer_version = r.importer_version, extractor_name = r.extractor_name, "
            "extractor_version = r.extractor_version FROM core.extraction_runs r "
            "WHERE r.canon_version_id = v.id"
        )
    )
    for column in (
        "page_count",
        "importer_version",
        "extractor_version",
        "extractor_name",
    ):
        op.alter_column("canon_versions", column, nullable=False, schema="core")

    op.drop_table("preferred_extraction_runs", schema="core")

    op.drop_constraint(
        op.f("fk_ayin_passage_reviews_passage_id_extraction_run_id_canon_passages"),
        "ayin_passage_reviews",
        schema="core",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f(
            "fk_ayin_passage_reviews_review_item_id_extraction_run_id_ayin_review_items"
        ),
        "ayin_passage_reviews",
        schema="core",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk_ayin_passage_reviews_review_item_id_ayin_review_items"),
        "ayin_passage_reviews",
        "ayin_review_items",
        ["review_item_id"],
        ["id"],
        source_schema="core",
        referent_schema="core",
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_ayin_passage_reviews_passage_id_canon_passages"),
        "ayin_passage_reviews",
        "canon_passages",
        ["passage_id"],
        ["id"],
        source_schema="core",
        referent_schema="core",
        ondelete="RESTRICT",
    )
    op.drop_column("ayin_passage_reviews", "extraction_run_id", schema="core")

    op.drop_constraint(
        op.f("fk_ayin_review_items_extraction_run_id_canon_version_id_extraction_runs"),
        "ayin_review_items",
        schema="core",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("uq_ayin_review_items_id_extraction_run_id"),
        "ayin_review_items",
        schema="core",
        type_="unique",
    )
    op.drop_constraint(
        op.f("ck_ayin_review_items_review_completion_metadata"),
        "ayin_review_items",
        schema="core",
        type_="check",
    )
    op.drop_index(
        op.f("ix_ayin_review_items_extraction_run_id"),
        table_name="ayin_review_items",
        schema="core",
    )
    op.drop_column("ayin_review_items", "reviewed_at", schema="core")
    op.drop_column("ayin_review_items", "reviewer_notes", schema="core")
    op.drop_column("ayin_review_items", "reason_for_review", schema="core")
    op.drop_column("ayin_review_items", "extraction_run_id", schema="core")

    op.drop_constraint(
        op.f("fk_canon_passages_extraction_run_id_canon_version_id_extraction_runs"),
        "canon_passages",
        schema="core",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("uq_canon_passages_id_extraction_run_id"),
        "canon_passages",
        schema="core",
        type_="unique",
    )
    op.drop_constraint(
        op.f("uq_canon_passages_extraction_run_id_sequence"),
        "canon_passages",
        schema="core",
        type_="unique",
    )
    op.drop_index(
        op.f("ix_canon_passages_extraction_run_id"),
        table_name="canon_passages",
        schema="core",
    )
    op.create_unique_constraint(
        op.f("uq_canon_passages_canon_version_id_sequence"),
        "canon_passages",
        ["canon_version_id", "sequence"],
        schema="core",
    )
    op.drop_column("canon_passages", "extraction_run_id", schema="core")

    op.drop_index(
        op.f("ix_extraction_runs_canon_version_id"),
        table_name="extraction_runs",
        schema="core",
    )
    op.drop_table("extraction_runs", schema="core")

    op.drop_index(
        "uq_canon_versions_source_identity",
        table_name="canon_versions",
        schema="core",
    )
    op.create_unique_constraint(
        op.f("uq_canon_versions_document_id_source_file_hash_importer_version"),
        "canon_versions",
        ["document_id", "source_file_hash", "importer_version"],
        schema="core",
    )

    review_reason = postgresql.ENUM(
        *_REVIEW_REASONS,
        name="ayin_review_reason",
        schema="core",
        create_type=False,
    )
    review_reason.drop(connection, checkfirst=True)
