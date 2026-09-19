"""Phase 2 migrations, importer, constraints, API, and rollback tests."""

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from psycopg.errors import (
    CheckViolation,
    IntegrityConstraintViolation,
    NotNullViolation,
    UniqueViolation,
)
from pydantic import SecretStr
from sqlalchemy import select

from alembic import command
from app.core.ayin.domain import (
    CorpusZone,
    DiscourseType,
    DistinctionRelation,
    EditorialStatus,
    ReviewReason,
)
from app.core.ayin.extractor import (
    ExtractedPassage,
    PdfExtraction,
    PopplerPdfExtractor,
)
from app.core.ayin.importer import AyinImporter, AyinImportError, default_seed_manifest
from app.core.ayin.models import (
    AyinConcept,
    AyinRelation,
    CanonPassage,
)
from app.core.ayin.service import AyinExtractionService
from app.core.ayin.validator import AyinStructuralValidator
from app.core.config import Environment, Settings
from app.db.session import Database
from app.main import create_app
from app.storage.local import LocalObjectStore

pytestmark = pytest.mark.integration

SOURCE = Path("docs/source_material/Ayin_Emtedad_Baznevisi_Shodeh.pdf")


def _sync_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


class _FakeExtractor(PopplerPdfExtractor):
    def __init__(
        self,
        *,
        version: str = "1",
        raw: str = "متن خام",
        review_reasons: tuple[ReviewReason, ...] = (),
    ) -> None:
        self._fixture_version = version
        self._raw = raw
        self._review_reasons = review_reasons

    def extract(self, _source: Path) -> PdfExtraction:
        passage = ExtractedPassage(
            sequence=1,
            page_number=1,
            printed_page_label="1",
            heading_path=("آزمون",),
            paragraph_index=1,
            raw_text=self._raw,
            normalized_text=self._raw,
            content_hash=hashlib.sha256(self._raw.encode()).hexdigest(),
            review_reasons=self._review_reasons,
        )
        return PdfExtraction(
            page_count=1,
            extractor_name="test",
            extractor_version=self._fixture_version,
            normalization_version="test-normalization-v1",
            segmentation_version="test-segmentation-v1",
            configuration={"fixture": self._fixture_version},
            passages=(passage,),
        )


def test_phase2_data_migrates_to_one_source_version_and_one_run(
    pre_stabilization_database_url: str,
) -> None:
    sync_url = _sync_url(pre_stabilization_database_url)
    document_id = uuid4()
    version_id = uuid4()
    asset_id = uuid4()
    passage_id = uuid4()
    review_id = uuid4()
    source_hash = "a" * 64
    raw = "legacy extraction"
    content_hash = hashlib.sha256(raw.encode()).hexdigest()
    with psycopg.connect(sync_url) as connection:
        connection.execute(
            "INSERT INTO ops.object_assets "
            "(id, checksum_algorithm, sha256, byte_size, media_type, "
            "storage_backend, storage_key, original_filename, verified_at, created_at) "
            "VALUES (%s, 'sha256', %s, 1, 'application/pdf', 'local', %s, "
            "'legacy.pdf', now(), now())",
            (asset_id, source_hash, f"sha256/aa/{source_hash}"),
        )
        connection.execute(
            "INSERT INTO core.canon_documents "
            "(id, slug, document_type, title, original_language, corpus_zone, "
            "created_at) VALUES (%s, 'legacy-ayin', 'ayin', 'legacy', 'fa', "
            "'AYIN_WORKING', now())",
            (document_id,),
        )
        connection.execute(
            "INSERT INTO core.canon_versions "
            "(id, document_id, status, corpus_zone, source_file_hash, "
            "importer_version, extractor_name, extractor_version, page_count, "
            "change_summary, created_at) VALUES (%s, %s, 'draft', "
            "'AYIN_WORKING', %s, %s, 'poppler-pdftotext', "
            "'pdftotext version 26.08.0', 1, 'legacy fixture', now())",
            (
                version_id,
                document_id,
                source_hash,
                "ayin-pdf-v1:poppler-pdftotext:pdftotext version 26.08.0",
            ),
        )
        connection.execute(
            "INSERT INTO core.canon_version_source_assets "
            "(canon_version_id, source_asset_id) VALUES (%s, %s)",
            (version_id, asset_id),
        )
        connection.execute(
            "INSERT INTO core.canon_passages "
            "(id, canon_version_id, source_asset_id, sequence, page_number, "
            "heading_path, paragraph_index, raw_text, normalized_text, "
            "content_hash, language, created_at) VALUES "
            "(%s, %s, %s, 1, 1, '[\"fixture\"]'::jsonb, 1, %s, %s, %s, "
            "'fa', now())",
            (passage_id, version_id, asset_id, raw, raw, content_hash),
        )
        connection.execute(
            "INSERT INTO core.ayin_review_items "
            "(id, canon_version_id, kind, status, page_number, message, created_at) "
            "VALUES (%s, %s, 'extraction_ambiguity', 'open', 1, "
            "'legacy review', now())",
            (review_id, version_id),
        )
        connection.execute(
            "INSERT INTO core.ayin_passage_reviews (review_item_id, passage_id) "
            "VALUES (%s, %s)",
            (review_id, passage_id),
        )

    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url", pre_stabilization_database_url.replace("%", "%%")
    )
    command.upgrade(config, "head")

    with psycopg.connect(sync_url) as connection:
        migrated = connection.execute(
            "SELECT v.source_file_hash, r.canon_version_id, r.extractor_version, "
            "r.passage_count, p.extraction_run_id, i.reason_for_review, "
            "i.status, i.reviewer_notes, i.reviewed_at "
            "FROM core.canon_versions v "
            "JOIN core.extraction_runs r ON r.canon_version_id = v.id "
            "JOIN core.canon_passages p ON p.canon_version_id = v.id "
            "JOIN core.ayin_review_items i ON i.canon_version_id = v.id"
        ).fetchone()
        assert migrated is not None
        assert migrated[:4] == (
            source_hash,
            version_id,
            "pdftotext version 26.08.0",
            1,
        )
        assert migrated[4] is not None
        assert migrated[5:] == ("character_corruption", "open", None, None)
        assert connection.execute(
            "SELECT count(*) FROM core.preferred_extraction_runs"
        ).fetchone() == (0,)

    command.downgrade(config, "20260918_0002")
    command.upgrade(config, "head")
    with psycopg.connect(sync_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM core.extraction_runs"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM core.ayin_review_items "
            "WHERE reason_for_review='character_corruption'"
        ).fetchone() == (1,)


def test_migration_refuses_unsafe_automatic_duplicate_source_merge(
    pre_stabilization_database_url: str,
) -> None:
    sync_url = _sync_url(pre_stabilization_database_url)
    document_id = uuid4()
    source_hash = "b" * 64
    with psycopg.connect(sync_url) as connection:
        connection.execute(
            "INSERT INTO core.canon_documents "
            "(id, slug, document_type, title, original_language, corpus_zone, "
            "created_at) VALUES (%s, 'duplicate-legacy-ayin', 'ayin', 'legacy', "
            "'fa', 'AYIN_WORKING', now())",
            (document_id,),
        )
        for index in (1, 2):
            connection.execute(
                "INSERT INTO core.canon_versions "
                "(id, document_id, status, corpus_zone, source_file_hash, "
                "importer_version, extractor_name, extractor_version, page_count, "
                "change_summary, created_at) VALUES (%s, %s, 'draft', "
                "'AYIN_WORKING', %s, %s, 'poppler-pdftotext', %s, 1, "
                "'duplicate legacy fixture', now())",
                (
                    uuid4(),
                    document_id,
                    source_hash,
                    f"ayin-pdf-v1:{index}",
                    f"pdftotext version {index}",
                ),
            )

    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url", pre_stabilization_database_url.replace("%", "%%")
    )
    with pytest.raises(RuntimeError, match="cannot safely infer how to merge"):
        command.upgrade(config, "head")
    with psycopg.connect(sync_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM core.canon_versions"
        ).fetchone() == (2,)


@pytest.mark.asyncio
async def test_current_working_import_is_idempotent_and_exposed_by_api(
    phase2_database_url: str, tmp_path: Path
) -> None:
    database = Database(phase2_database_url)
    store = LocalObjectStore(tmp_path / "storage")
    importer = AyinImporter(database, store)
    try:
        first = await importer.import_file(
            SOURCE, seed_manifest=default_seed_manifest()
        )
        second = await importer.import_file(
            SOURCE, seed_manifest=default_seed_manifest()
        )
        assert first.source_version_created is True
        assert first.extraction_run_created is True
        assert second.source_version_created is False
        assert second.extraction_run_created is False
        assert first.document_id == second.document_id
        assert first.version_id == second.version_id
        assert first.extraction_run_id == second.extraction_run_id
        assert first.source_sha256 == (
            "676c210e0ef6be5f0fe5228190f63d9e38f39dccc7a9ea6b0b815d487124566c"
        )
        assert first.page_count == 146
        assert first.passage_count == 1019
        assert first.concept_count == 20
        assert first.distinction_count == 11
        assert first.principle_count == 12
        assert first.open_question_count == 5
        assert first.term_count == 6
        assert first.term_form_count == 15
        assert first.review_item_count == 56
        assert first.corpus_zone is CorpusZone.AYIN_WORKING
        assert first.status is EditorialStatus.DRAFT
        assert first.is_preferred is False

        alternate = await AyinImporter(
            database,
            store,
            extractor=_FakeExtractor(
                version="2",
                raw="مرزبندی جایگزین",
                review_reasons=(ReviewReason.BROKEN_PARAGRAPH,),
            ),
        ).import_file(SOURCE)
        assert alternate.source_version_created is False
        assert alternate.extraction_run_created is True
        assert alternate.version_id == first.version_id
        assert alternate.extraction_run_id != first.extraction_run_id
        assert alternate.output_hash != first.output_hash
        assert alternate.passage_count == 1
        assert alternate.review_item_count == 1
        assert alternate.concept_count == 20

        async with database.transaction() as session:
            first_preference = await AyinExtractionService(session).prefer(
                first.extraction_run_id,
                selected_by="integration-editor",
                reason="First deterministic QA fixture.",
            )
        assert first_preference.extraction_run_id == first.extraction_run_id
        async with database.transaction() as session:
            second_preference = await AyinExtractionService(session).prefer(
                alternate.extraction_run_id,
                selected_by="integration-editor",
                reason="Explicit comparison selected alternate fixture.",
            )
        assert second_preference.extraction_run_id == alternate.extraction_run_id

        async with database.transaction() as session:
            bon_id = await session.scalar(
                select(AyinConcept.id).where(AyinConcept.stable_key == "bon")
            )
            jan_id = await session.scalar(
                select(AyinConcept.id).where(AyinConcept.stable_key == "jan")
            )
            source_passage_id = await session.scalar(
                select(CanonPassage.id)
                .where(CanonPassage.extraction_run_id == first.extraction_run_id)
                .order_by(CanonPassage.sequence)
                .limit(1)
            )
            assert bon_id is not None
            assert jan_id is not None
            assert source_passage_id is not None
            session.add(
                AyinRelation(
                    subject_concept_id=bon_id,
                    relation_type=DistinctionRelation.OPEN_RELATION,
                    object_concept_id=jan_id,
                    explanation="Typed source-backed relation test fixture.",
                    discourse_type=DiscourseType.CONCEPTUAL,
                    canon_version_id=first.version_id,
                    source_passage_id=source_passage_id,
                    status=EditorialStatus.REVIEW,
                )
            )

        async with database.transaction() as session:
            report = await AyinStructuralValidator(session, store).validate()
        assert report.valid is True

        settings = Settings(
            _env_file=None,
            environment=Environment.TEST,
            database_url=SecretStr(phase2_database_url),
            storage_root=tmp_path / "api-storage",
            log_level="INFO",
            log_json=True,
        )
        app = create_app(settings)
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            documents = await client.get("/ayin/documents")
            document = await client.get(f"/ayin/documents/{first.document_id}")
            concepts = await client.get("/ayin/concepts")
            bon = await client.get("/ayin/concepts/bon")
            distinctions = await client.get("/ayin/distinctions")
            relations = await client.get("/ayin/relations")
            principles = await client.get("/ayin/principles")
            questions = await client.get("/ayin/open-questions")
            terms = await client.get("/ayin/terms?query=Bon")
        assert documents.status_code == 200
        assert documents.json()[0]["corpus_zone"] == "AYIN_WORKING"
        version_payload = document.json()["versions"][0]
        assert len(version_payload["extraction_runs"]) == 2
        assert version_payload["preferred_extraction_run_id"] == str(
            alternate.extraction_run_id
        )
        assert len(concepts.json()) == 20
        assert bon.json()["stable_key"] == "bon"
        assert len(distinctions.json()) == 11
        assert len(relations.json()) == 1
        assert relations.json()[0]["relation_type"] == "OPEN_RELATION"
        assert len(principles.json()) == 12
        assert len(questions.json()) == 5
        assert terms.json()[0]["stable_key"] == "bon"
    finally:
        await database.dispose()

    with psycopg.connect(_sync_url(phase2_database_url)) as connection:
        counts = connection.execute(
            "SELECT "
            "(SELECT count(*) FROM core.canon_documents), "
            "(SELECT count(*) FROM core.canon_versions), "
            "(SELECT count(*) FROM core.extraction_runs), "
            "(SELECT count(*) FROM core.canon_passages), "
            "(SELECT count(*) FROM core.ayin_review_items), "
            "(SELECT count(*) FROM core.preferred_extraction_runs), "
            "(SELECT count(*) FROM core.ayin_concepts), "
            "(SELECT count(*) FROM core.ayin_concept_versions), "
            "(SELECT count(*) FROM core.canon_versions "
            " WHERE corpus_zone = 'AYIN_CANON')"
        ).fetchone()
        forbidden = connection.execute(
            "SELECT count(*) FROM core.term_forms "
            "WHERE form_type = 'forbidden_equivalent'"
        ).fetchone()
        review_metadata = connection.execute(
            "SELECT reason_for_review, status, reviewer_notes, reviewed_at "
            "FROM core.ayin_review_items WHERE extraction_run_id = %s",
            (alternate.extraction_run_id,),
        ).fetchone()
        concept_source = connection.execute(
            "SELECT cv.concept_id, cv.canon_version_id, cv.source_passage_id, "
            "cv.definition FROM core.ayin_concept_versions cv "
            "JOIN core.ayin_concepts c ON c.id = cv.concept_id "
            "WHERE c.stable_key = 'bon'"
        ).fetchone()
        assert concept_source is not None
        connection.execute(
            "INSERT INTO core.ayin_concept_versions "
            "(id, concept_id, canon_version_id, source_passage_id, "
            "version_number, definition, approval_status) "
            "VALUES (%s, %s, %s, %s, 2, 'reviewed revision fixture', 'review')",
            (uuid4(), concept_source[0], concept_source[1], concept_source[2]),
        )
        definitions = connection.execute(
            "SELECT definition FROM core.ayin_concept_versions "
            "WHERE concept_id = %s ORDER BY version_number",
            (concept_source[0],),
        ).fetchall()
        question_id = connection.execute(
            "SELECT id FROM core.ayin_open_question_versions LIMIT 1"
        ).fetchone()
        assert question_id is not None
        connection.execute(
            "UPDATE core.ayin_open_question_versions SET status='under_review' "
            "WHERE id=%s",
            (question_id[0],),
        )
        lifecycle = connection.execute(
            "SELECT status FROM core.ayin_open_question_versions WHERE id=%s",
            (question_id[0],),
        ).fetchone()
    assert counts == (1, 1, 2, 1020, 57, 1, 20, 20, 0)
    assert forbidden == (3,)
    assert review_metadata == ("broken_paragraph", "open", None, None)
    assert definitions == [(concept_source[3],), ("reviewed revision fixture",)]
    assert lifecycle == ("under_review",)


@pytest.mark.asyncio
async def test_different_hash_creates_new_version_and_keeps_history(
    phase2_database_url: str, tmp_path: Path
) -> None:
    first_source = tmp_path / "one.pdf"
    second_source = tmp_path / "two.pdf"
    first_source.write_bytes(b"one")
    second_source.write_bytes(b"two")
    database = Database(phase2_database_url)
    importer = AyinImporter(
        database,
        LocalObjectStore(tmp_path / "storage"),
        extractor=_FakeExtractor(),
    )
    try:
        first = await importer.import_file(first_source)
        second = await importer.import_file(second_source)
        changed_importer = AyinImporter(
            database,
            LocalObjectStore(tmp_path / "storage"),
            extractor=_FakeExtractor(),
            importer_version="ayin-pdf-v2-test",
        )
        third = await changed_importer.import_file(first_source)
        conflicting = AyinImporter(
            database,
            LocalObjectStore(tmp_path / "storage"),
            extractor=_FakeExtractor(raw="contradictory output"),
        )
        with pytest.raises(
            AyinImportError, match="identical extraction identity produced"
        ):
            await conflicting.import_file(first_source)
    finally:
        await database.dispose()
    assert first.document_id == second.document_id
    assert first.version_id != second.version_id
    assert first.source_sha256 != second.source_sha256
    assert third.source_sha256 == first.source_sha256
    assert third.version_id == first.version_id
    assert third.extraction_run_id != first.extraction_run_id
    with psycopg.connect(_sync_url(phase2_database_url)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM core.canon_versions"
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT count(*) FROM core.extraction_runs"
        ).fetchone() == (3,)
        assert connection.execute(
            "SELECT count(*) FROM core.canon_passages"
        ).fetchone() == (3,)


@pytest.mark.asyncio
async def test_failed_import_rolls_back_all_relational_rows(
    phase2_database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(phase2_database_url)
    importer = AyinImporter(database, LocalObjectStore(tmp_path / "storage"))

    async def fail_seed(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("injected seed failure")

    monkeypatch.setattr(importer, "_load_seed", fail_seed)
    with pytest.raises(RuntimeError, match="injected seed failure"):
        await importer.import_file(SOURCE, seed_manifest=default_seed_manifest())
    await database.dispose()
    with psycopg.connect(_sync_url(phase2_database_url)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM core.canon_documents"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM ops.object_assets"
        ).fetchone() == (0,)


def test_database_enforces_approved_immutability_and_zone_metadata(
    phase2_database_url: str,
) -> None:
    document_id = uuid4()
    version_id = uuid4()
    with psycopg.connect(_sync_url(phase2_database_url)) as connection:
        connection.execute(
            "INSERT INTO core.canon_documents "
            "(id, slug, document_type, title, original_language, corpus_zone, "
            "created_at) "
            "VALUES (%s, 'approved-fixture', 'ayin', 'fixture', 'fa', "
            "'AYIN_CANON', now())",
            (document_id,),
        )
        connection.execute(
            "INSERT INTO core.canon_versions "
            "(id, document_id, semantic_version, status, corpus_zone, "
            "source_file_hash, effective_from, change_summary, approved_by, "
            "approved_at, created_at) VALUES "
            "(%s, %s, '1.0.0', 'approved', 'AYIN_CANON', "
            "%s, %s, 'approved fixture', "
            "'editor-fixture', %s, now())",
            (
                version_id,
                document_id,
                "a" * 64,
                date(2026, 9, 18),
                datetime.now(UTC),
            ),
        )
        connection.commit()
        with pytest.raises(IntegrityConstraintViolation):
            connection.execute(
                "UPDATE core.canon_versions SET change_summary='overwritten' "
                "WHERE id=%s",
                (version_id,),
            )
        connection.rollback()

        with pytest.raises(CheckViolation):
            connection.execute(
                "INSERT INTO core.canon_versions "
                "(id, document_id, status, corpus_zone, source_file_hash, "
                "change_summary, created_at) VALUES (%s, %s, 'approved', "
                "'AYIN_WORKING', %s, 'bad', now())",
                (uuid4(), document_id, "b" * 64),
            )
        connection.rollback()


def test_stable_keys_provenance_and_open_question_lifecycle(
    phase2_database_url: str,
) -> None:
    with psycopg.connect(_sync_url(phase2_database_url)) as connection:
        concept_id = uuid4()
        connection.execute(
            "INSERT INTO core.ayin_concepts (id, stable_key, status, created_at) "
            "VALUES (%s, 'majal', 'review', now())",
            (concept_id,),
        )
        with pytest.raises(UniqueViolation):
            connection.execute(
                "INSERT INTO core.ayin_concepts "
                "(id, stable_key, status, created_at) "
                "VALUES (%s, 'majal', 'draft', now())",
                (uuid4(),),
            )
        connection.rollback()

        with pytest.raises(NotNullViolation):
            connection.execute(
                "INSERT INTO core.ayin_concept_versions "
                "(id, concept_id, canon_version_id, source_passage_id, "
                "version_number, definition, approval_status) "
                "VALUES (%s, %s, %s, NULL, 1, 'invalid', 'review')",
                (uuid4(), concept_id, uuid4()),
            )
        connection.rollback()

        assert connection.execute(
            "SELECT 'under_review'::core.open_question_status"
        ).fetchone() == ("under_review",)
        assert connection.execute(
            "SELECT 'OPTIONAL_METAPHYSICAL'::core.discourse_type"
        ).fetchone() == ("OPTIONAL_METAPHYSICAL",)
