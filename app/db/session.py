"""Async SQLAlchemy engine and application-owned transaction lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pgvector.psycopg import register_vector_async
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


class Database:
    """Own the engine and produce one transactional session per operation."""

    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            pool_pre_ping=True,
        )

        @event.listens_for(self.engine.sync_engine, "connect")
        def register_vector_types(dbapi_connection: object, _record: object) -> None:
            """Teach psycopg to encode and decode pgvector values."""

            dbapi_connection.run_async(register_vector_async)  # type: ignore[attr-defined]

        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """Yield a session whose transaction commits or rolls back as a unit."""

        async with self.session_factory() as session, session.begin():
            yield session

    async def dispose(self) -> None:
        """Release pooled database connections."""

        await self.engine.dispose()


def create_database(settings: Settings) -> Database:
    """Construct database infrastructure from redacted settings."""

    return Database(settings.database_url.get_secret_value())
