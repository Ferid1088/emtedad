"""Phase 3 source, structure, safety, API, and database integrity tests."""

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.core.ayin.importer import AyinImporter, default_seed_manifest
from app.core.config import Environment, Settings
from app.db.session import Database
from app.main import create_app
from app.ritual.domain import RitualPieceType
from app.ritual.extractor import PopplerRitualExtractor, RitualPdfExtraction
from app.ritual.importer import ManasekImporter
from app.ritual.models import (
    LocalizationSafetyRule,
    RitualLocalization,
    RitualVersion,
)
from app.ritual.safety import RitualSafetyValidator
from app.ritual.validator import RitualStructuralValidator
from app.storage.local import LocalObjectStore

AYIN_SOURCE = Path("docs/source_material/Ayin_Emtedad_Baznevisi_Shodeh.pdf")
MANASEK_SOURCE = Path("docs/source_material/Manasek_V1.pdf")


def _sync_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _make_changed_source(target: Path) -> None:
    target.write_bytes(MANASEK_SOURCE.read_bytes() + b"\n% reviewed working revision\n")


def _required_row(row: tuple[Any, ...] | None) -> tuple[Any, ...]:
    assert row is not None
    return row


class AlternateExtractor(PopplerRitualExtractor):
    def extract(self, source: Path) -> RitualPdfExtraction:
        return replace(super().extract(source), extractor_version="alternate-v2")


async def _import_ayin(database: Database, store: LocalObjectStore) -> None:
    await AyinImporter(database, store).import_file(
        AYIN_SOURCE, seed_manifest=default_seed_manifest()
    )


@pytest.mark.asyncio
async def test_manasek_import_is_idempotent_structured_and_exposed_by_api(
    phase3_database_url: str, tmp_path: Path
) -> None:
    database = Database(phase3_database_url)
    store = LocalObjectStore(tmp_path / "storage")
    try:
        await _import_ayin(database, store)
        first = await ManasekImporter(database, store).import_file(MANASEK_SOURCE)
        second = await ManasekImporter(database, store).import_file(MANASEK_SOURCE)
        assert first.source_version_created is True
        assert first.extraction_run_created is True
        assert second.source_version_created is False
        assert second.extraction_run_created is False
        assert first.source_version_id == second.source_version_id
        assert first.extraction_run_id == second.extraction_run_id
        assert first.source_sha256 == (
            "f5f07580d10b165b07513fe802ca86d8969cbe24a9d110d208b424c58c73f1af"
        )
        assert (first.page_count, first.passage_count) == (42, 42)
        assert (first.gate_count, first.stage_count) == (5, 7)
        assert (first.gate_ritual_count, first.return_count) == (35, 7)
        assert first.collective_count == 1
        assert first.cue_count == 224
        assert first.music_specification_count == 43
        assert first.safety_rule_count == 33

        async with database.transaction() as session:
            report = await RitualStructuralValidator(session, store).validate()
            ritual = await session.scalar(
                select(RitualVersion).where(
                    RitualVersion.piece_type == RitualPieceType.GATE
                )
            )
            assert ritual is not None
            safety = await RitualSafetyValidator(session).validate_version(ritual.id)
        assert report.valid is True
        assert safety.valid is True
        assert safety.publishable is False

        settings = Settings(
            _env_file=None,
            environment=Environment.TEST,
            database_url=SecretStr(phase3_database_url),
            storage_root=tmp_path / "storage",
            log_level="INFO",
            log_json=True,
        )
        app = create_app(settings)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            families = await client.get("/ritual/families")
            gates = await client.get("/ritual/gates")
            stages = await client.get("/ritual/stages")
            rituals = await client.get("/ritual/rituals")
            rules = await client.get("/ritual/safety-rules")
            review = await client.get("/ritual/review-queue")
        assert len(families.json()) == 3
        assert len(gates.json()) == 5
        assert len(stages.json()) == 7
        assert len(rituals.json()) == 43
        assert len(rules.json()) == 33
        assert len(review.json()) == 1
    finally:
        await database.dispose()

    with psycopg.connect(_sync_url(phase3_database_url)) as connection:
        counts = connection.execute(
            "SELECT "
            "(SELECT count(*) FROM ritual.versions "
            " WHERE corpus_zone='MANASEK_WORKING'), "
            "(SELECT count(*) FROM ritual.versions WHERE corpus_zone='MANASEK_CANON'), "
            "(SELECT count(*) FROM core.canon_versions "
            " WHERE corpus_zone='AYIN_CANON'), "
            "(SELECT count(*) FROM ritual.returns), "
            "(SELECT count(*) FROM ritual.ritual_sequence_items)"
        ).fetchone()
        assert counts == (1, 0, 0, 7, 43)
        columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='ritual' AND table_name='stages'"
            )
        }
        assert "stage_day" not in columns
        assert "sequence_position" in columns
        working_links = connection.execute(
            "SELECT count(*) FROM ritual.concept_links link "
            "JOIN core.ayin_concept_versions concept "
            "ON concept.id=link.ayin_concept_version_id "
            "JOIN core.canon_versions source ON source.id=concept.canon_version_id "
            "WHERE source.corpus_zone='AYIN_WORKING'"
        ).fetchone()
        assert working_links == (43,)
        assert connection.execute(
            "SELECT count(*) FROM ritual.concept_links WHERE source_passage_id IS NULL"
        ).fetchone() == (0,)
        music = _required_row(
            connection.execute(
                "SELECT original_prompt, sonic_family, emotional_arc "
                "FROM ritual.music_specifications "
                "JOIN ritual.ritual_versions ON ritual_versions.id="
                "music_specifications.ritual_version_id "
                "WHERE ritual_versions.piece_type='RETURN' LIMIT 1"
            ).fetchone()
        )
        assert "Create a complete 10-minute Return composition" in music[0]
        assert str(music[1]).startswith("Earth =")
        assert str(music[2]).startswith("Do not make a medley")


@pytest.mark.asyncio
async def test_same_source_different_extractor_retains_separate_run(
    phase3_database_url: str, tmp_path: Path
) -> None:
    database = Database(phase3_database_url)
    store = LocalObjectStore(tmp_path / "storage")
    try:
        await _import_ayin(database, store)
        first = await ManasekImporter(database, store).import_file(MANASEK_SOURCE)
        alternate = await ManasekImporter(
            database, store, extractor=AlternateExtractor()
        ).import_file(MANASEK_SOURCE)
    finally:
        await database.dispose()
    assert alternate.source_version_id == first.source_version_id
    assert alternate.extraction_run_id != first.extraction_run_id
    assert alternate.output_hash == first.output_hash
    with psycopg.connect(_sync_url(phase3_database_url)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM ritual.versions"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM ritual.extraction_runs"
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT count(*) FROM ritual.passages"
        ).fetchone() == (84,)
        assert connection.execute(
            "SELECT count(*) FROM ritual.review_flags"
        ).fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM ritual.rituals").fetchone() == (
            43,
        )


@pytest.mark.asyncio
async def test_new_source_hash_creates_new_source_version(
    phase3_database_url: str, tmp_path: Path
) -> None:
    changed = tmp_path / "Manasek_changed.pdf"
    await asyncio.to_thread(_make_changed_source, changed)
    database = Database(phase3_database_url)
    store = LocalObjectStore(tmp_path / "storage")
    try:
        await _import_ayin(database, store)
        first = await ManasekImporter(database, store).import_file(MANASEK_SOURCE)
        second = await ManasekImporter(database, store).import_file(changed)
    finally:
        await database.dispose()
    assert first.source_sha256 != second.source_sha256
    assert first.source_version_id != second.source_version_id
    with psycopg.connect(_sync_url(phase3_database_url)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM ritual.versions"
        ).fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM ritual.rituals").fetchone() == (
            43,
        )
        assert connection.execute(
            "SELECT count(*) FROM ritual.ritual_versions"
        ).fetchone() == (86,)


@pytest.mark.asyncio
async def test_failed_structural_load_rolls_back_relational_graph(
    phase3_database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(phase3_database_url)
    store = LocalObjectStore(tmp_path / "storage")
    try:
        await _import_ayin(database, store)
        importer = ManasekImporter(database, store)

        async def fail_structure(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("deliberate structure failure")

        monkeypatch.setattr(importer, "_load_structure", fail_structure)
        with pytest.raises(RuntimeError, match="deliberate structure failure"):
            await importer.import_file(MANASEK_SOURCE)
    finally:
        await database.dispose()
    with psycopg.connect(_sync_url(phase3_database_url)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM ritual.documents"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM ritual.ritual_versions"
        ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_localization_cannot_drop_safety_bindings(
    phase3_database_url: str, tmp_path: Path
) -> None:
    database = Database(phase3_database_url)
    store = LocalObjectStore(tmp_path / "storage")
    try:
        await _import_ayin(database, store)
        await ManasekImporter(database, store).import_file(MANASEK_SOURCE)
        async with database.transaction() as session:
            ritual = await session.scalar(select(RitualVersion))
            assert ritual is not None
            localization = await session.scalar(
                select(RitualLocalization).where(
                    RitualLocalization.ritual_version_id == ritual.id
                )
            )
            assert localization is not None
            binding_id = await session.scalar(
                select(LocalizationSafetyRule.safety_rule_version_id).where(
                    LocalizationSafetyRule.localization_id == localization.id
                )
            )
            assert binding_id is not None
            await session.execute(
                delete(LocalizationSafetyRule).where(
                    LocalizationSafetyRule.localization_id == localization.id,
                    LocalizationSafetyRule.safety_rule_version_id == binding_id,
                )
            )
            report = await RitualSafetyValidator(session).validate_version(ritual.id)
            assert any(
                issue.code == "localization_weakened_safety" for issue in report.issues
            )
            session.add(
                LocalizationSafetyRule(
                    localization_id=localization.id,
                    safety_rule_version_id=binding_id,
                )
            )
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_database_rejects_return_as_gate_and_working_approval(
    phase3_database_url: str, tmp_path: Path
) -> None:
    database = Database(phase3_database_url)
    store = LocalObjectStore(tmp_path / "storage")

    try:
        await _import_ayin(database, store)
        await ManasekImporter(database, store).import_file(MANASEK_SOURCE)
    finally:
        await database.dispose()
    with psycopg.connect(_sync_url(phase3_database_url)) as connection:
        return_id = _required_row(
            connection.execute(
                "SELECT id FROM ritual.ritual_versions "
                "WHERE piece_type='RETURN' LIMIT 1"
            ).fetchone()
        )[0]
        gate_id = _required_row(
            connection.execute("SELECT id FROM ritual.gates LIMIT 1").fetchone()
        )[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE ritual.ritual_versions SET gate_id=%s WHERE id=%s",
                (gate_id, return_id),
            )
        connection.rollback()
        architecture_id = _required_row(
            connection.execute(
                "SELECT id FROM ritual.architecture_versions WHERE mode='INDIVIDUAL'"
            ).fetchone()
        )[0]
        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute(
                "UPDATE ritual.architecture_versions SET status='approved' WHERE id=%s",
                (architecture_id,),
            )
            connection.commit()
        connection.rollback()
        gate_version_id = _required_row(
            connection.execute("SELECT id FROM ritual.gate_versions LIMIT 1").fetchone()
        )[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE ritual.gate_versions SET is_bon_component=true WHERE id=%s",
                (gate_version_id,),
            )
        connection.rollback()
        working_version = _required_row(
            connection.execute(
                "SELECT id FROM ritual.versions WHERE corpus_zone='MANASEK_WORKING'"
            ).fetchone()
        )[0]
        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute(
                "UPDATE ritual.versions SET corpus_zone='MANASEK_CANON' WHERE id=%s",
                (working_version,),
            )
        connection.rollback()
        document_id, ayin_version_id, source_hash = _required_row(
            connection.execute(
                "SELECT document_id, designed_against_ayin_version_id, "
                "source_file_hash FROM ritual.versions WHERE id=%s",
                (working_version,),
            ).fetchone()
        )
        approved_id = _required_row(
            connection.execute(
                "INSERT INTO ritual.versions "
                "(id, document_id, designed_against_ayin_version_id, "
                "semantic_version, status, corpus_zone, source_file_hash, "
                "effective_from, change_summary, approved_by, approved_at, "
                "created_at) VALUES "
                "(gen_random_uuid(), %s, %s, '1.0.0', 'approved', "
                "'MANASEK_CANON', %s, CURRENT_DATE, 'approved fixture', "
                "'editor-fixture', now(), now()) RETURNING id",
                (document_id, ayin_version_id, source_hash),
            ).fetchone()
        )[0]
        connection.commit()
        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute(
                "UPDATE ritual.versions SET change_summary='mutated' WHERE id=%s",
                (approved_id,),
            )
        connection.rollback()
        cue_id = _required_row(
            connection.execute("SELECT id FROM ritual.cues LIMIT 1").fetchone()
        )[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE ritual.cues SET start_seconds=-1 WHERE id=%s", (cue_id,)
            )
        connection.rollback()
        flag_id = _required_row(
            connection.execute("SELECT id FROM ritual.review_flags LIMIT 1").fetchone()
        )[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE ritual.review_flags SET status='resolved' WHERE id=%s",
                (flag_id,),
            )
