"""Shared integration fixtures.

Integration tests must never touch the owner's corpus. Several suites used
to connect straight to ``EMTEDAD_DATABASE_URL`` and wrote channels,
candidates and sources into the live database — the dev corpus then carried
"Test Channel" and ``V0000000000`` sources that topic mining would pick up.
Every test that writes takes a disposable migrated database instead.
"""

import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

from alembic import command


def _base_database_url() -> str:
    url = os.environ.get("EMTEDAD_DATABASE_URL")
    if not url:
        pytest.skip("EMTEDAD_DATABASE_URL is required")
    return url


@pytest.fixture
def migrated_database_url() -> Iterator[str]:
    """A throwaway database at the current migration head."""

    base_url = _base_database_url()
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
