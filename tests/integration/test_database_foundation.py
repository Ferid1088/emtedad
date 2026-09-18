"""PostgreSQL, pgvector, namespace, migration, and readiness integration tests."""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url

from alembic import command
from app.core.config import Environment, Settings
from app.db.base import SCHEMA_NAMES
from app.db.health import DatabaseReadinessService
from app.db.session import Database
from app.main import create_app

pytestmark = pytest.mark.integration


def _database_url() -> str:
    try:
        return os.environ["EMTEDAD_DATABASE_URL"]
    except KeyError as exc:
        raise RuntimeError(
            "EMTEDAD_DATABASE_URL is required for integration tests"
        ) from exc


def _sync_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _url_for_database(url: str, database: str) -> str:
    parsed: URL = make_url(url)
    return parsed.set(database=database).render_as_string(hide_password=False)


@pytest.fixture
def disposable_database_url() -> Iterator[str]:
    """Create a dedicated database so migration rollback cannot touch dev data."""

    base_url = _database_url()
    database_name = f"emtedad_test_{uuid4().hex}"
    admin_url = _sync_url(_url_for_database(base_url, "postgres"))

    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )

    test_url = _url_for_database(base_url, database_name)
    try:
        yield test_url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            connection.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name))
            )


def _alembic_config(database_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _schema_names(database_url: str) -> set[str]:
    with psycopg.connect(_sync_url(database_url)) as connection:
        rows = connection.execute(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name = ANY(%s)",
            (list(SCHEMA_NAMES),),
        ).fetchall()
    return {str(row[0]) for row in rows}


def test_clean_migration_downgrade_and_second_upgrade_are_safe(
    disposable_database_url: str,
) -> None:
    config = _alembic_config(disposable_database_url)

    command.upgrade(config, "head")
    command.check(config)

    with psycopg.connect(_sync_url(disposable_database_url)) as connection:
        version_row = connection.execute("SHOW server_version_num").fetchone()
        vector_version = connection.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
        domain_table_count_row = connection.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = ANY(%s)",
            (list(SCHEMA_NAMES),),
        ).fetchone()

    assert version_row is not None
    assert domain_table_count_row is not None
    version = int(version_row[0])
    domain_table_count = int(domain_table_count_row[0])

    assert version // 10_000 == 17
    assert vector_version is not None
    assert _schema_names(disposable_database_url) == set(SCHEMA_NAMES)
    assert domain_table_count == 0

    command.downgrade(config, "base")
    assert _schema_names(disposable_database_url) == set()

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    assert _schema_names(disposable_database_url) == set(SCHEMA_NAMES)


@pytest.mark.asyncio
async def test_database_readiness_and_transaction_contract() -> None:
    database = Database(_database_url())
    try:
        readiness = await DatabaseReadinessService(database.engine).check()
        assert readiness.ready is True
        assert all(readiness.checks.values())

        async with database.transaction() as session:
            assert await session.scalar(text("SELECT 1")) == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_application_reports_ready_against_migrated_database(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=SecretStr(_database_url()),
        storage_root=tmp_path / "storage",
        log_level="INFO",
        log_json=True,
    )
    app = create_app(settings)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
