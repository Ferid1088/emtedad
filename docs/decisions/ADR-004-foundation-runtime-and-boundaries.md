# ADR-004: Foundation Runtime and Boundaries

- Status: Accepted
- Date: 2026-09-18

## Context

Phase 1 must establish reproducible runtime, persistence, transaction, and
module conventions without creating later-phase domain behavior. The repository
already selects Python 3.11+, FastAPI, PostgreSQL 17, pgvector, SQLAlchemy 2,
Alembic, and a modular monolith, but it did not select an exact initial runtime,
session strategy, identifier convention, or local job boundary.

## Decision

- Use CPython 3.13 for the initial locked development and production runtime.
  The project may broaden its tested range later; it does not claim untested
  compatibility.
- Use `uv` with `pyproject.toml` and a committed `uv.lock` for reproducible
  dependency resolution.
- Use a top-level `app` modular-monolith package. Create only Phase 1 packages;
  later domains add their own modules in their owning phases.
- Use SQLAlchemy 2 async sessions with psycopg 3. Application services own
  transaction boundaries. Repositories may flush but do not commit.
- Generate UUIDv4 identifiers in application code and store timestamps as
  timezone-aware UTC values. Phase 1 defines the convention but creates no
  domain tables merely to demonstrate it.
- Use PostgreSQL schemas `core`, `knowledge`, `ritual`, `retrieval`, `content`,
  and `ops`. PostgreSQL remains the canonical relational source of truth.
- Enable pgvector in the baseline migration, but defer vector columns and
  indexes until Phase 5 benchmarks a real multilingual retrieval model.
- Keep Phase 1 request and CLI work in-process. Add a database-backed job
  contract only when an owning phase introduces a real asynchronous job. Do not
  add a distributed queue preemptively.
- Provide an immutable-object storage protocol with a content-addressed local
  adapter. A production cloud adapter and deployment topology remain review
  items.
- Use structured JSON logs by default, with correlation IDs and recursive
  redaction of fields whose names indicate secrets.

## Consequences

- Local setup and the application image use the same Python minor version and
  lockfile.
- Async database access fits FastAPI without blocking request workers, while
  migrations retain explicit Alembic control.
- No job, review, asset-metadata, Canon, ritual, or retrieval tables are created
  before their behavior and constraints exist.
- Broadening Python support, adding workers, or selecting cloud storage requires
  tests and, where compatibility or operations materially change, a new ADR.
- UUIDv4 does not provide insertion ordering. If measured database locality
  later justifies UUIDv7, migration and compatibility require a separate ADR.

## Alternatives considered

- Synchronous SQLAlchemy in async routes: rejected because it requires careful
  threadpool boundaries for every database operation.
- A distributed task queue in Phase 1: rejected as premature because no domain
  job exists yet.
- Integer primary keys: viable, but UUIDs better support independently created
  versioned artifacts and future external boundaries without exposing row
  counts.
- Creating placeholder tables for future domains: rejected because it would
  make later-phase behavior appear implemented and lock in speculative schema.
