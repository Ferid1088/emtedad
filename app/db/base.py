"""SQLAlchemy metadata and PostgreSQL namespace conventions."""

from enum import StrEnum

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


class PostgresSchema(StrEnum):
    """Owned PostgreSQL namespaces; domain tables arrive in later phases."""

    CORE = "core"
    KNOWLEDGE = "knowledge"
    RITUAL = "ritual"
    RETRIEVAL = "retrieval"
    CONTENT = "content"
    OPS = "ops"


SCHEMA_NAMES: tuple[str, ...] = tuple(schema.value for schema in PostgresSchema)

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by phase-owned SQLAlchemy models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
