"""Phase 4 §36-39: duration-aware localization adjustment.

``LocalizationService.adjust_duration`` must correct spoken length toward
the master's target while preserving the exact claim set — never by
dropping or inventing claims — and must persist the correction as a new
immutable version, not an in-place edit.
"""

import json
from collections.abc import Iterator
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from alembic import command
from app.db.session import Database
from app.lecture.domain import PublicationLanguage
from app.lecture.generic_service import GenericMasterService
from app.localization.domain import LocalizationStatus
from app.localization.models import (
    LocalizationProject,
    LocalizationStatement,
    LocalizationVersion,
)
from app.localization.service import LocalizationService
from app.localization.validators import LocalizationFinding
from app.ops.settings.service import StudioSettingsService
from tests.integration.test_stage_truth import _draft_pipeline
from tests.integration.test_studio_ui import _database_url
from tests.integration.test_topics import _Provider

pytestmark = pytest.mark.integration


@pytest.fixture
def migrated_database_url() -> Iterator[str]:
    base_url = _database_url()
    name = f"emtedad_test_{uuid4().hex}"
    admin_url = (
        make_url(base_url.replace("postgresql+psycopg://", "postgresql://", 1))
        .set(database="postgres")
        .render_as_string(hide_password=False)
    )
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = make_url(base_url).set(database=name).render_as_string(hide_password=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        yield url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


class _LocalizationProvider(_Provider):
    """Returns deterministic localizations with a controlled word count."""

    def __init__(self, create_total_words: int = 110, adjust_words: int = 5) -> None:
        self.create_total_words = create_total_words
        self.adjust_words = adjust_words
        self.adjust_calls = 0

    async def extract(self, request):
        if request.task == "semantic lecture localization":
            claims = json.loads(request.input_text)["claims"]
            base = max(1, self.create_total_words // len(claims))
            remainder = self.create_total_words - base * len(claims)
            statements = []
            for index, claim in enumerate(claims):
                words = base + (remainder if index == 0 else 0)
                statements.append(
                    {
                        "claim_id": str(claim["id"]),
                        "display_text": "wort " * max(1, words),
                    }
                )
            return request.output_model.model_validate({"statements": statements})
        if request.task == "localization duration adjustment":
            self.adjust_calls += 1
            statements = json.loads(request.input_text)["statements"]
            # Faithful shape: same claim IDs, differently-sized texts.
            return request.output_model.model_validate(
                {
                    "statements": [
                        {
                            "claim_id": item["claim_id"],
                            "display_text": "wort " * self.adjust_words,
                        }
                        for item in statements
                    ]
                }
            )
        return await super().extract(request)


class _DroppingProvider(_LocalizationProvider):
    """A misbehaving adjuster that silently drops the last claim."""

    async def extract(self, request):
        if request.task == "localization duration adjustment":
            self.adjust_calls += 1
            statements = json.loads(request.input_text)["statements"][:-1]
            return request.output_model.model_validate(
                {
                    "statements": [
                        {"claim_id": item["claim_id"], "display_text": "wort"}
                        for item in statements
                    ]
                }
            )
        return await super().extract(request)


async def _localized_version(
    database: Database, provider: _LocalizationProvider
) -> tuple[LocalizationService, UUID]:
    """Real master → real create() with the stub provider → version id."""

    brief, _scripts, _draft = await _draft_pipeline(database, provider)
    master = await GenericMasterService(database).latest_ready_for_brief(brief.id)
    assert master is not None
    service = LocalizationService(database)
    service.provider = provider
    version_id = await service.create(master.id, PublicationLanguage.EN)
    return service, version_id


@pytest.mark.asyncio
async def test_adjust_duration_noop_within_tolerance(
    migrated_database_url: str,
) -> None:
    """Within ±10 % of the target, no provider call and no new version."""

    database = Database(migrated_database_url)
    try:
        provider = _LocalizationProvider(create_total_words=110)
        service, version_id = await _localized_version(database, provider)
        # target = 27.5 min * wpm = 110 words: dead-center of the band.
        await StudioSettingsService(database).set_many({"speech_wpm_en": 4})
        same = await service.adjust_duration(version_id)
        assert same == version_id
        assert provider.adjust_calls == 0
        async with database.transaction() as session:
            count = await session.scalar(select(func.count(LocalizationVersion.id)))
        assert count == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_adjust_duration_expand_persists_new_version(
    migrated_database_url: str,
) -> None:
    """A too-short realization is expanded into a new READY version."""

    database = Database(migrated_database_url)
    try:
        provider = _LocalizationProvider(create_total_words=10, adjust_words=5)
        service, version_id = await _localized_version(database, provider)
        await StudioSettingsService(database).set_many({"speech_wpm_en": 40})
        new_id = await service.adjust_duration(version_id)
        assert new_id != version_id
        assert provider.adjust_calls == 1
        async with database.transaction() as session:
            new_version = await session.get(LocalizationVersion, new_id)
            assert new_version is not None
            assert new_version.version_number == 2
            assert new_version.status == LocalizationStatus.READY_FOR_VOICE
            rows = list(
                await session.scalars(
                    select(LocalizationStatement).where(
                        LocalizationStatement.localization_version_id == new_id
                    )
                )
            )
            old_rows = list(
                await session.scalars(
                    select(LocalizationStatement).where(
                        LocalizationStatement.localization_version_id == version_id
                    )
                )
            )
        assert {row.lecture_claim_id for row in rows} == {
            row.lecture_claim_id for row in old_rows
        }
        assert all(
            row.claim_metadata.get("duration_adjusted") is True
            and row.claim_metadata.get("adjustment_direction") == "expand"
            for row in rows
        )
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_adjust_duration_condense_direction(
    migrated_database_url: str,
) -> None:
    """A too-long realization is condensed, direction recorded."""

    database = Database(migrated_database_url)
    try:
        provider = _LocalizationProvider(create_total_words=300, adjust_words=3)
        service, version_id = await _localized_version(database, provider)
        await StudioSettingsService(database).set_many({"speech_wpm_en": 1})
        new_id = await service.adjust_duration(version_id)
        assert new_id != version_id
        async with database.transaction() as session:
            row = await session.scalar(
                select(LocalizationStatement).where(
                    LocalizationStatement.localization_version_id == new_id
                )
            )
            assert row is not None
            assert row.claim_metadata["adjustment_direction"] == "condense"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_adjust_duration_rejects_claim_set_mismatch(
    migrated_database_url: str,
) -> None:
    """A provider that drops a claim must fail loudly — nothing persisted."""

    database = Database(migrated_database_url)
    try:
        provider = _DroppingProvider(create_total_words=10)
        service, version_id = await _localized_version(database, provider)
        await StudioSettingsService(database).set_many({"speech_wpm_en": 40})
        with pytest.raises(ValueError, match="same claim set"):
            await service.adjust_duration(version_id)
        async with database.transaction() as session:
            count = await session.scalar(select(func.count(LocalizationVersion.id)))
        assert count == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_adjust_duration_quality_gate_marks_failed(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the re-run quality gate fails, the new version is FAILED."""

    class _FailingGate:
        def validate(self, *args: object) -> list[LocalizationFinding]:
            return [LocalizationFinding("CLAIM_OMISSION", "forced")]

    database = Database(migrated_database_url)
    try:
        provider = _LocalizationProvider(create_total_words=10, adjust_words=5)
        service, version_id = await _localized_version(database, provider)
        monkeypatch.setattr(
            "app.localization.service.LocalizationQualityGate", _FailingGate
        )
        await StudioSettingsService(database).set_many({"speech_wpm_en": 40})
        new_id = await service.adjust_duration(version_id)
        async with database.transaction() as session:
            new_version = await session.get(LocalizationVersion, new_id)
            assert new_version is not None
            assert new_version.status == LocalizationStatus.FAILED
            project = await session.get(
                LocalizationProject, new_version.localization_project_id
            )
            assert project is not None
            assert project.status == LocalizationStatus.FAILED
    finally:
        await database.dispose()
