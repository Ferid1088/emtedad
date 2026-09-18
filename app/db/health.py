"""Database-aware readiness checks kept outside HTTP route handlers."""

from dataclasses import dataclass
from typing import Protocol

import structlog
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.base import SCHEMA_NAMES

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    """Internal readiness result; details are not exposed by the public API."""

    ready: bool
    checks: dict[str, bool]


class ReadinessService(Protocol):
    """Port used by the system readiness route."""

    async def check(self) -> ReadinessResult:
        """Return dependency readiness without raising expected outages."""


class DatabaseReadinessService:
    """Verify PostgreSQL version, pgvector, and required namespaces."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def check(self) -> ReadinessResult:
        checks = {
            "database": False,
            "postgresql_17": False,
            "pgvector": False,
            "schemas": False,
        }
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                checks["database"] = True

                version_number = await connection.scalar(
                    text("SELECT current_setting('server_version_num')::integer")
                )
                checks["postgresql_17"] = (
                    isinstance(version_number, int) and version_number // 10_000 == 17
                )

                vector_version = await connection.scalar(
                    text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                )
                checks["pgvector"] = isinstance(vector_version, str)

                schema_rows = await connection.execute(
                    text(
                        "SELECT schema_name FROM information_schema.schemata "
                        "WHERE schema_name = ANY(:schema_names)"
                    ),
                    {"schema_names": list(SCHEMA_NAMES)},
                )
                existing_schemas = set(schema_rows.scalars())
                checks["schemas"] = existing_schemas == set(SCHEMA_NAMES)
        except SQLAlchemyError as exc:
            logger.warning(
                "database.readiness_failed",
                error_type=type(exc).__name__,
            )

        return ReadinessResult(ready=all(checks.values()), checks=checks)
