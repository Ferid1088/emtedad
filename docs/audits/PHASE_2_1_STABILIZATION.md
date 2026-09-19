# Phase 2.1 Stabilization — Source and Extraction Provenance

Date: 2026-09-19

Status: complete; Phase 3 remains pending repository-owner review.

## A. Schema and model changes

- `core.canon_documents` remains the intellectual document identity.
- `core.canon_versions` now represents a source/editorial version. Its Working
  identity is independent of extractor tooling and includes document, exact
  source SHA-256, corpus zone, and explicit semantic/source version metadata.
- New `core.extraction_runs` rows represent reproducible transformations of one
  source version and exact source asset. Each records importer, extractor,
  normalization, segmentation, canonical configuration/hash, output hash, page
  count, passage count, and creation time.
- `core.canon_passages` now belongs to one extraction run. Sequence uniqueness
  is per run, while document-version and source-asset pins remain intact.
- New `core.preferred_extraction_runs` stores at most one explicitly selected
  run per source version. It records selector, reason, and timestamp; run rows
  and passage sets are never deleted when preference changes.
- `core.ayin_review_items` now pins an extraction run and records a specific
  reason, status, nullable reviewer notes, and nullable review time.
- `core.ayin_passage_reviews` uses composite foreign keys to ensure its passage
  and review item belong to the same extraction run.
- Stable editorial identities and their version rows are loaded once per source
  version. A parser rerun does not duplicate concepts or concept versions.

ADR-005 records the compatibility and reproducibility decision.

## B. Migration

Alembic head is `20260918_0003`:

- creates and constrains extraction and preference tables;
- backfills one extraction run for each existing Phase 2 version with passages;
- computes a deterministic passage-set output hash;
- attaches existing passages and review records to the backfilled run;
- maps the existing extraction ambiguity reviews to the specific
  `character_corruption` reason;
- moves importer/extractor/page counts out of `canon_versions` after backfill;
- changes passage sequence uniqueness from source-version scope to
  extraction-run scope;
- introduces the corrected source-identity unique index;
- supports downgrade only where each source version still has exactly one run.
  A multi-run downgrade is refused because the Phase 2 schema cannot represent
  it without data loss.

The migration upgrade, downgrade, and re-upgrade path was tested with populated
Phase 2 data, including passage-review metadata.

## C. Existing duplicate Working versions

An automatic merge of two pre-existing same-identity source versions is not
safe because both may own structured editorial rows and evidence links. The
migration detects that state before changing schema and aborts transactionally
with an instruction to recreate the pre-production import.

The current source was therefore verified from the original PDF on a fresh
database. Both Poppler outputs were retained under one source version as two
extraction runs. No passage set was discarded or overwritten.

The local development database contained only the disposable Phase 2 Working
import (one document/version, zero Canon rows) and had schema drift from an
earlier applied form of revision 0002. It was recreated from the unchanged
source PDF and committed migrations rather than applying an unsafe partial
repair. The resulting development state contains both extraction runs and the
explicitly selected preferred run described below.

## D. Extraction-run design

Extraction identity includes:

- source version and immutable source asset;
- importer version;
- extractor name and version;
- normalization version;
- segmentation version;
- canonical configuration hash.

The stored output hash covers ordered sequence, page, printed page label,
heading path, paragraph index, raw content hash, and normalized passage text.
Repeating the same identity reuses its run only when page count, passage count,
and output hash agree; contradictory output fails rather than silently
replacing data.

Observed verification state:

| Identity | Host run | Container run |
|---|---:|---:|
| Source SHA-256 | `676c210e0ef6be5f0fe5228190f63d9e38f39dccc7a9ea6b0b815d487124566c` | same |
| Poppler | 26.08.0 | 25.03.0 |
| Pages | 146 | 146 |
| Passages | 1,019 | 1,018 |
| Output SHA-256 | `b91d1bced7eaafef3854069d9e2576153ca4eb4279bb4927af8a4d916ba5af83` | `1d4c1dfceb4cf08b45ca7598ab7419059c88d31095db23dae2d79ee549105e78` |
| Review items | 56 | 56 |

Combined state: one document, one `AYIN_WORKING` source version, one source
asset, two extraction runs, and 2,037 independently run-pinned passages.

## E. Preferred-extraction mechanism

Imports never select a preferred run. The CLI requires an explicit run UUID,
selector identity, and documented reason. A primary key on source-version ID
enforces at most one preference; a composite foreign key prevents selecting a
run from another version.

After deterministic hashes, structural validation, and the prior page-aware
manual QA were reviewed, the Poppler 26.08.0 run was selected with a reason that
explicitly states selection was not based on passage count alone. Integration
tests switch preference between two runs and prove both historical run and
passage sets remain.

## F. Review queue

All 56 previously flagged passages remain open and unmodified for each real
extraction output. No AI rewriting or silent correction was performed.

Supported review reasons are:

- `suspicious_extraction`
- `heading_uncertainty`
- `broken_paragraph`
- `character_corruption`
- `page_layout_ambiguity`
- `possible_missing_content`
- `seed_provenance`

The current embedded-font detector classifies the 56 observed items as
`character_corruption`. Every item is traceable to its source version,
extraction run, passage, and page and includes `reviewer_notes` and
`reviewed_at` fields for later editorial work.

## G. Commands and results

Principal verification commands:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy app tests
uv run pytest tests/unit -q
uv run pytest tests/importers -q
EMTEDAD_DATABASE_URL=postgresql+psycopg://... uv run pytest tests/integration -q
EMTEDAD_DATABASE_URL=postgresql+psycopg://... uv run pytest -q

uv run alembic upgrade head
uv run alembic upgrade head
uv run alembic current
uv run alembic check

uv run python -m app.cli ayin import \
  docs/source_material/Ayin_Emtedad_Baznevisi_Shodeh.pdf
uv run python -m app.cli ayin validate

docker build -t emtedad-platform:phase2.1 .
docker run --rm ... emtedad-platform:phase2.1 \
  uv run --no-sync python -m app.cli ayin import /source/ayin.pdf

uv run python -m app.cli ayin prefer-extraction RUN_UUID \
  --selected-by phase-2-1-qa \
  --reason "Preferred after deterministic hash validation and prior page-aware manual QA; not selected by passage count alone."
```

Results:

- Ruff format: 78 files checked
- Ruff lint: passed
- strict mypy: 52 source files, no issues
- unit tests: 34 passed
- importer tests: 5 passed
- integration tests: 10 passed
- full suite: 49 passed
- clean Alembic upgrade/repeat-upgrade/current/drift checks: passed
- populated Phase 2 migration/backfill/downgrade/re-upgrade: passed
- unsafe duplicate-source merge guard: passed and preserved the old rows
- host import repeated: one run, second import idempotently reused it
- container import repeated: second run, second container import reused it
- structural validator over both real passage sets: valid, zero issues
- `AYIN_CANON` versions: zero

One initial integration command was invoked without its required
`EMTEDAD_DATABASE_URL`; fixture setup rejected it before application assertions
ran. The environment was supplied and both the focused integration suite and
full suite then passed as reported above.

## H. Authority confirmation

The source remains `AYIN_WORKING` with `draft` status. Selecting a preferred
extraction run is an operational/editorial evidence choice and does not promote
the source or any structured object to Canon.

## I. Scope confirmation

No Phase 3 or Manasek implementation was started. No ritual tables, models,
importers, routes, safety workflows, or source imports were added. Phase 3
remains a pending plan requiring explicit repository-owner approval.
