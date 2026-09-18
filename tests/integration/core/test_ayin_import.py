"""Phase 2 migrations, importer, constraints, API, and rollback tests."""

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient
from psycopg.errors import (
    CheckViolation,
    IntegrityConstraintViolation,
    NotNullViolation,
    UniqueViolation,
)
from pydantic import SecretStr
from sqlalchemy import select

from app.core.ayin.domain import (
    CorpusZone,
    DiscourseType,
    DistinctionRelation,
    EditorialStatus,
)
from app.core.ayin.extractor import (
    ExtractedPassage,
    PdfExtraction,
    PopplerPdfExtractor,
)
from app.core.ayin.importer import AyinImporter, default_seed_manifest
from app.core.ayin.models import AyinConcept, AyinRelation, CanonPassage
from app.core.ayin.validator import AyinStructuralValidator
from app.core.config import Environment, Settings
from app.db.session import Database
from app.main import create_app
from app.storage.local import LocalObjectStore

pytestmark = pytest.mark.integration

SOURCE = Path("docs/source_material/Ayin_Emtedad_Baznevisi_Shodeh.pdf")


def _sync_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


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
        assert first.created is True
        assert second.created is False
        assert first.document_id == second.document_id
        assert first.version_id == second.version_id
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

        async with database.transaction() as session:
            bon_id = await session.scalar(
                select(AyinConcept.id).where(AyinConcept.stable_key == "bon")
            )
            jan_id = await session.scalar(
                select(AyinConcept.id).where(AyinConcept.stable_key == "jan")
            )
            source_passage_id = await session.scalar(
                select(CanonPassage.id)
                .where(CanonPassage.canon_version_id == first.version_id)
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
            concepts = await client.get("/ayin/concepts")
            bon = await client.get("/ayin/concepts/bon")
            distinctions = await client.get("/ayin/distinctions")
            relations = await client.get("/ayin/relations")
            principles = await client.get("/ayin/principles")
            questions = await client.get("/ayin/open-questions")
            terms = await client.get("/ayin/terms?query=Bon")
        assert documents.status_code == 200
        assert documents.json()[0]["corpus_zone"] == "AYIN_WORKING"
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
            "(SELECT count(*) FROM core.canon_passages), "
            "(SELECT count(*) FROM core.canon_versions "
            " WHERE corpus_zone = 'AYIN_CANON')"
        ).fetchone()
        forbidden = connection.execute(
            "SELECT count(*) FROM core.term_forms "
            "WHERE form_type = 'forbidden_equivalent'"
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
    assert counts == (1, 1, 1019, 0)
    assert forbidden == (3,)
    assert definitions == [(concept_source[3],), ("reviewed revision fixture",)]
    assert lifecycle == ("under_review",)


class _FakeExtractor(PopplerPdfExtractor):
    def extract(self, _source: Path) -> PdfExtraction:
        raw = "متن خام"
        passage = ExtractedPassage(
            sequence=1,
            page_number=1,
            printed_page_label="1",
            heading_path=("آزمون",),
            paragraph_index=1,
            raw_text=raw,
            normalized_text=raw,
            content_hash=(
                "3158b672a8d5f3d07db537c2acb811aa043678fe07bf57da3338025f50f71798"
            ),
            needs_review=False,
        )
        return PdfExtraction(
            page_count=1,
            extractor_name="test",
            extractor_version="1",
            passages=(passage,),
        )


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
    finally:
        await database.dispose()
    assert first.document_id == second.document_id
    assert first.version_id != second.version_id
    assert first.source_sha256 != second.source_sha256
    assert third.source_sha256 == first.source_sha256
    assert third.version_id != first.version_id
    with psycopg.connect(_sync_url(phase2_database_url)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM core.canon_versions"
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
            "source_file_hash, importer_version, extractor_name, extractor_version, "
            "page_count, effective_from, change_summary, approved_by, approved_at, "
            "created_at) VALUES (%s, %s, '1.0.0', 'approved', 'AYIN_CANON', "
            "%s, 'fixture', 'fixture', '1', 1, %s, 'approved fixture', "
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
                "importer_version, extractor_name, extractor_version, page_count, "
                "change_summary, created_at) VALUES (%s, %s, 'approved', "
                "'AYIN_WORKING', %s, 'bad', 'bad', '1', 1, 'bad', now())",
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
