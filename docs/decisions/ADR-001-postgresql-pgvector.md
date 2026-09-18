# ADR-001: PostgreSQL 17 with pgvector

- Status: Accepted
- Date: 2026-09-18

## Context

The platform needs relational integrity, versioning, provenance, transactions,
multilingual full-text search, vector retrieval, review queues, and dependency
tracking. Splitting the first production version across unrelated persistence
systems would increase operational and consistency costs.

## Decision

Use PostgreSQL 17 as the primary relational source of truth, with pgvector for
dense retrieval and PostgreSQL full-text search for lexical retrieval. Use
SQLAlchemy 2 and Alembic for persistence and migrations.

## Consequences

- Canonical integrity and retrieval metadata share transactions.
- Hybrid retrieval can start with one operational database.
- Language-specific text search configuration and vector indexes require
  explicit evaluation.
- Vector scaling and index parameters must be benchmarked rather than assumed.

## Alternatives considered

- Separate relational and vector databases: deferred until measured scale or
  operational requirements justify the added complexity.
- Local-only vector store: rejected as the production system of record.
