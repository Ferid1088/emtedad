# Phase 2 Completion — Ayin Knowledge Core

Date: 2026-09-18

Status: complete; Phase 3 is pending repository-owner review.

> Historical note: Phase 2.1 corrected the extractor/source-version identity
> described in this report. See `PHASE_2_1_STABILIZATION.md` and ADR-005.

## A. Files created or modified

Created:

- `alembic/versions/20260918_0002_ayin_working_canon.py`
- `app/api/routes/ayin.py`
- `app/cli.py`
- `app/core/ayin/` domain types, models, extraction, import, repository,
  service, schemas, seed loading, normalization, and validation modules
- `app/core/terminology/` term and term-form models
- `app/ops/assets/` immutable asset metadata and repository modules
- `resources/ayin/working_seed.v1.json`
- `tests/importers/`
- `tests/integration/core/`
- `tests/unit/core/`
- this completion report

Modified:

- `Dockerfile`
- `README.md`
- `alembic/env.py`
- `app/core/exceptions.py`
- `app/main.py`
- `docs/audits/README.md`
- `docs/execution/CURRENT_PHASE.md`
- `docs/execution/MASTER_PLAN.md`
- `pyproject.toml`
- `tests/integration/test_database_foundation.py`
- `uv.lock`

## B. Architecture implemented

- Added a typed, versioned Ayin knowledge core inside the existing modular
  monolith. Routes are read-only and thin; services and repositories contain
  query and persistence behavior; repositories never commit.
- Kept `AYIN_WORKING` and `AYIN_CANON` distinct in enums, database constraints,
  import behavior, API output, and tests. The supplied source is only
  `AYIN_WORKING` with `draft` status.
- Added immutable, content-addressed source-asset metadata and a typed
  Ayin-version/source-asset join. No generic `owner_type`/`owner_id` relation
  was introduced.
- Preserved exact PDF bytes outside PostgreSQL. Passages retain raw and
  normalized text separately with source asset, document version, page,
  paragraph, sequence, heading path, hash, extractor, and importer provenance.
- Added stable concepts with versioned definitions, distinctions, typed concept
  relations, principles, open questions, and Persian/English/Arabic-ready
  terminology forms. All seeded assertions remain draft/review Working data
  and pin a source passage.
- Added typed extraction and provenance review records. Ambiguous extraction is
  retained and queued; no OCR, LLM extraction, or guessed replacement text is
  used.
- Added an idempotent transactional CLI importer, structural validator,
  inspection commands, and read-only FastAPI endpoints.

## C. Database and migration state

Alembic head is `20260918_0002`. It creates 18 Phase 2 tables:

- `ops.object_assets`
- `core.canon_documents`, `core.canon_versions`,
  `core.canon_version_source_assets`, and `core.canon_passages`
- `core.ayin_concepts` and `core.ayin_concept_versions`
- `core.ayin_distinctions` and `core.ayin_distinction_versions`
- `core.ayin_relations`
- `core.ayin_principles` and `core.ayin_principle_versions`
- `core.ayin_open_questions` and `core.ayin_open_question_versions`
- `core.ayin_review_items` and `core.ayin_passage_reviews`
- `core.terms` and `core.term_forms`

Foreign keys, unique and check constraints, explicit delete behavior, partial
term-form uniqueness, and database triggers protect provenance and approved
history. Approved versions require Canon zone plus semantic version, approver,
approval time, and effective date; approved rows cannot be updated or deleted.
No approval command or endpoint exists.

The clean host import produced:

| Item | Count/state |
|---|---:|
| Source SHA-256 | `676c210e0ef6be5f0fe5228190f63d9e38f39dccc7a9ea6b0b815d487124566c` |
| Pages | 146 |
| Passages | 1,019 |
| Concepts | 20 |
| Distinctions | 11 |
| Principles | 12 |
| Open questions | 5 |
| Terms / forms | 6 / 15 |
| Extraction review items | 56 |
| Canon versions | 0 |
| Zone/status | `AYIN_WORKING` / `draft` |

The second import reused the same document/version IDs and all counts. A full
downgrade to Phase 1, re-upgrade, repeated upgrade, drift check, and second pair
of imports also passed.

## D. Exact verification commands executed

Infrastructure and dependency checks:

```bash
docker compose up -d db
docker compose ps
docker compose exec -T db pg_isready -U emtedad -d emtedad
docker compose exec -T db psql -U emtedad -d emtedad -Atc \
  "SELECT current_setting('server_version'), extversion FROM pg_extension WHERE extname='vector';"
uv sync --all-groups --frozen
```

Disposable database migration and import checks were run with
`EMTEDAD_ENVIRONMENT=test`, the disposable `emtedad_phase2_verify` database,
and an isolated `mktemp` storage root:

```bash
uv run alembic upgrade 20260918_0001
uv run alembic upgrade head
uv run alembic upgrade head
uv run alembic current
uv run alembic check
uv run python -m app.cli ayin import \
  docs/source_material/Ayin_Emtedad_Baznevisi_Shodeh.pdf
uv run python -m app.cli ayin import \
  docs/source_material/Ayin_Emtedad_Baznevisi_Shodeh.pdf
uv run python -m app.cli ayin validate
uv run alembic downgrade 20260918_0001
uv run alembic upgrade head
uv run alembic upgrade head
uv run alembic current
uv run alembic check
```

Static analysis and tests:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy app tests
uv run pytest tests/unit -q
uv run pytest tests/importers -q
uv run pytest tests/integration -q
uv run pytest -q
git diff --check
```

Container verification:

```bash
docker build -t emtedad-platform:phase2 .
docker run --rm emtedad-platform:phase2 sh -c \
  'pdftotext -v 2>&1 | head -1; test -f resources/ayin/working_seed.v1.json; uv run --no-sync python -m app.cli --help >/dev/null'
```

The container importer and validator were also run twice against the disposable
database with the source PDF mounted read-only and storage mounted at `/data`.

One initial disposable-database command stopped before running any migration
because `EMTEDAD_ENVIRONMENT` was omitted and the storage variable had incorrect
case. The corrected command recreated the database and completed all checks
above. No failure was suppressed.

## E. Verification results

- PostgreSQL: 17.8, healthy
- pgvector: 0.8.1, available
- Alembic: clean upgrade, repeat upgrade, downgrade/re-upgrade, current head,
  and no drift
- Ruff format: 74 files already formatted
- Ruff lint: passed
- strict mypy: 51 source files, no issues
- unit tests: 33 passed
- importer tests: 5 passed
- integration tests: 8 passed
- full suite: 46 passed with no warnings
- structural validator: valid, zero issues
- Docker image: built successfully; seed and CLI present
- Git whitespace check: passed
- Git ignored-state inspection: local caches, `.venv`, `.DS_Store`, and `tmp/`
  are ignored; no `.env`, source-derived storage object, database, or secret is
  staged for the checkpoint

Manual source QA rendered and inspected source pages 5, 13, 128, 130, 131,
132, 136, and 137, covering core distinctions, hierarchy, the five open
questions, glossary, and principles.

## F. Remaining Phase 2 review items

- Fifty-six source passages contain extraction patterns that require human
  editorial review. Their raw text and typed review records are retained; they
  do not invalidate the structural import.
- Poppler 26.08.0 on the host yields 1,019 passages; Poppler 25.03.0 in the
  current Debian image yields 1,018 because one wrapped segment is grouped
  differently. Phase 2 initially represented these as distinct Working
  versions. Phase 2.1 superseded that model: they are now distinct extraction
  runs under one immutable Working source version and asset.
- Rights, public-distribution permission, Canon approval authority, editorial
  governance, production deployment, backup/restore, and privacy remain the
  previously recorded review items. None was technically required for this
  local Working import.

## G. Decisions deliberately deferred

- Canon approval and promotion, editor identity/authorization, and public
  source-text distribution
- Manasek import/modeling and all ritual safety behavior
- external knowledge and YouTube ingestion
- full-text retrieval tuning, chunks, embeddings, vectors, and RAG
- Ayin/external dialogue, research packages, lecture generation,
  localization, publishing, and evaluation
- production object storage, worker topology, deployment, backup, and recovery

## H. Scope confirmation

No Phase 3 implementation was introduced. There are no Manasek tables,
importers, endpoints, ritual structures, or safety workflows. The next-phase
document is a pending plan only and must not be implemented until the repository
owner reviews and authorizes it.
