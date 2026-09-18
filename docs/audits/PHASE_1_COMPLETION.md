# Phase 1 Completion Evidence

- Completion date: 2026-09-18
- Phase: 1 - Platform Foundation
- Result: Complete
- Git checkpoint: recorded after final verification

## Scope result

Phase 1 established a reproducible Python/FastAPI/PostgreSQL foundation without
adding Phase 2 or later domain behavior. PostgreSQL remains the canonical
database. The migration enables pgvector and creates six empty namespace
schemas; it creates no Ayin, Manasek, external-knowledge, retrieval, research,
lecture, localization, publication, evaluation, or generic-owner tables.

The repository-owner decisions are recorded: the Ayin source is
`AYIN_WORKING`, the Manasek source is `MANASEK_WORKING`, and neither may be
silently promoted to Canon.

## Files created or modified

### Runtime and tooling

- `pyproject.toml` and `uv.lock`
- `.python-version`
- `.env.example`, `.gitignore`, and `.dockerignore`
- `Dockerfile` and `docker-compose.yml`

### Application

- `app/main.py`: FastAPI factory, lifespan, correlation middleware, and error
  translation
- `app/api/routes/health.py`: thin liveness/readiness routes
- `app/core/config.py`: required typed settings and production validation
- `app/core/exceptions.py`: stable application/storage exception contracts
- `app/db/base.py`: schema and naming conventions
- `app/db/session.py`: async engine, sessions, and application-owned
  transactions
- `app/db/health.py`: PostgreSQL 17, pgvector, and namespace readiness service
- `app/ops/logging.py`: JSON logging, context correlation, and recursive
  sensitive-field redaction
- `app/storage/base.py`: immutable-object storage protocol
- `app/storage/local.py`: SHA-256 content addressing, streaming writes,
  deduplication, non-overwriting atomic publication, fsync, corruption checks,
  and traversal/symlink containment
- package `__init__.py` files for Phase 1 modules only

### Database

- `alembic.ini`
- `alembic/env.py`
- `alembic/script.py.mako`
- `alembic/versions/20260918_0001_platform_foundation.py`

### Tests

- `tests/conftest.py`
- `tests/unit/test_app.py`
- `tests/unit/test_config.py`
- `tests/unit/test_logging.py`
- `tests/unit/test_storage.py`
- `tests/integration/test_database_foundation.py`

### Documentation

- `README.md`
- `docs/decisions/ADR-004-foundation-runtime-and-boundaries.md`
- `docs/audits/PHASE_0_REPOSITORY_AUDIT.md`
- `docs/audits/README.md`
- `docs/audits/PHASE_1_COMPLETION.md`
- `docs/execution/MASTER_PLAN.md`
- `docs/execution/CURRENT_PHASE.md`

## Architecture implemented

- CPython 3.13 and a frozen `uv` environment;
- FastAPI application factory with no import-time settings side effects;
- async SQLAlchemy 2 and psycopg 3;
- service-owned transaction boundary;
- PostgreSQL schemas `core`, `knowledge`, `ritual`, `retrieval`, `content`, and
  `ops`;
- dependency-aware readiness separated from process liveness;
- structured logs with correlation IDs and no connection detail in readiness
  failures;
- local immutable storage behind a replaceable protocol;
- local PostgreSQL 17/pgvector Compose service;
- reproducible application image that excludes source PDFs, tests, `.env`, and
  local/generated storage.

ADR-004 records UUIDv4 application-generated identifiers, timezone-aware UTC
timestamps, async sessions, application-owned transactions, and the decision
not to create a queue or placeholder job/domain tables in Phase 1.

## Database and migration state

- PostgreSQL server: 17.8 (`server_version_num = 170008`)
- pgvector extension: 0.8.1
- Alembic head: `20260918_0001`
- Created schemas: `content`, `core`, `knowledge`, `ops`, `retrieval`, `ritual`
- Tables in those six schemas: zero
- Vector indexes: zero
- Alembic drift: none

The migration's downgrade removes the six empty Phase 1 schemas with
`RESTRICT`. It intentionally retains the cluster-level pgvector extension
because it cannot prove exclusive ownership. Integration tests use and then
drop a dedicated disposable database, so this retention leaves no test data.

## Commands executed and final results

### Environment and static quality

```bash
uv lock
uv venv --clear --python 3.13
uv sync --all-groups --frozen
uv run ruff format --check .
uv run ruff check .
uv run mypy app tests
```

Final result: lock resolved 47 packages; environment uses CPython 3.13.15;
47 files formatted; Ruff passed; strict mypy passed for 26 source files.

The first async migration attempt failed because plain SQLAlchemy did not pull
the required `greenlet` runtime. The dependency was corrected to
`sqlalchemy[asyncio]`, the lockfile was regenerated, and all migration and test
commands then passed. Initial formatter/import-order findings were also fixed
and rerun cleanly.

### Docker and PostgreSQL

```bash
docker info --format '{{.ServerVersion}}'
docker compose config
docker compose pull db
docker compose up -d db
docker compose ps
docker compose exec -T db psql ...
docker build -t emtedad-platform:phase1 .
```

Final result: Docker Engine 29.4.3; Compose v5.1.3; database container healthy;
PostgreSQL 17.8 verified; pgvector 0.8.1 verified; application image built and
started successfully on the Compose network. Image inspection confirmed
`app/storage` is present and source PDFs, tests, `.env`, and local storage are
absent.

### Migrations

```bash
uv run alembic upgrade head
uv run alembic current
uv run alembic check
uv run pytest tests/integration -q
```

Final result: clean upgrade passed; current is `20260918_0001 (head)`; no new
upgrade operations detected. The isolated integration test passed upgrade,
check, downgrade to base, re-upgrade, a second idempotent upgrade, schema
verification, no-domain-table verification, readiness, and session transaction
checks.

### Application health

```bash
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
```

Final healthy result: both endpoints returned HTTP 200 with `live` and `ready`.
With the database deliberately stopped, liveness remained HTTP 200 and
readiness returned HTTP 503 with `not_ready`; the log exposed only
`OperationalError`, not a connection URL or password. The database was then
restarted and returned healthy.

### Tests

```bash
uv run pytest tests/unit -q
uv run pytest tests/integration -q
uv run pytest -q
```

Final result:

- unit: 25 passed;
- integration: 3 passed;
- full suite: 28 passed;
- warnings: zero in the final runs.

## Repository hygiene

- `.env`, `.venv`, caches, coverage, root local storage, temporary output,
  databases, and OS metadata are ignored.
- Dry-run staging includes `app/storage` and excludes `.env`, `.DS_Store`,
  `.venv`, caches, and local storage.
- A credential-pattern scan found no likely private keys or service tokens.
- Local Compose data is held in a Docker named volume and is not in the
  repository.

## Remaining Phase 1 issues

None. All written Phase 1 acceptance criteria passed.

## Deliberately deferred decisions

- source rights and redistribution policy;
- production deployment and network boundary;
- backups, retention, restore objectives, and audit retention;
- privacy policy and whether sensitive participant/user text will be stored;
- authentication, editor identities, roles, and Canon approval authority;
- production object-storage provider;
- a worker/queue mechanism until a real phase-owned job exists;
- broader Python-version support beyond the tested 3.13 runtime;
- exact passage location semantics and editorial semantic versions;
- all Ayin, Manasek, ingestion, retrieval, research, lecture, localization,
  publishing, and evaluation behavior.

## Phase boundary confirmation

No Phase 2 implementation was introduced. There are no Ayin tables, importers,
concepts, passages, terms, approval services, or source-processing dependencies.
`CURRENT_PHASE.md` contains a Phase 2 plan marked pending user review; execution
must not start until the repository owner approves it.
