# Phase 4 Completion — External Knowledge Ingestion

Date: 2026-09-19
Checkpoint target: `feat: implement external knowledge ingestion`

## A. Files changed

Created the `app/knowledge` domain (adapters, models, normalization, windows,
structured extraction, Codex provider, importer, resolvers, media, services,
schemas, and validator), `app/api/routes/knowledge.py`, Alembic revision
`2d874648966b`, Phase 4 tests, ADR-007, and this report. Updated application
wiring, CLI, dependencies/lock, architecture/execution documentation, and the
README.

## B. Migration

Revision `2d874648966b` creates the typed `knowledge` domain, its PostgreSQL
enums, constraints, indexes, and immutable source-version/raw-segment triggers.
The downgrade removes triggers, tables, indexes, and every Phase 4 enum.

## C. External knowledge schema

The schema separates creators/channels/sources; immutable source versions and
timestamped segments; deterministic windows and ordered segment membership;
extraction runs and independently retryable results; people, organizations,
works/authors, concepts, labels, and strong identifiers; occurrences,
resolution candidates, attributed claims, evidence, source quality,
content-addressed media links, and review state. All authoritative relations
are typed foreign keys; there is no generic owner ID.

## D. Pilot source metadata

- Platform/video: YouTube `331XLUCCybU`
- Source ID: `91f42e55-d01c-4dd8-9be4-792658753a2a`
- Title: `بحثی درباره‌ی کتاب مغز ایدئولوژیک | اثر لئور اِسمگراد | دکتر آذرخش مکری`
- URL: `https://www.youtube.com/watch?v=331XLUCCybU`
- Language/caption kind: Persian / generated
- Published/duration: 2025-09-25 / 6,836 seconds
- Source versions: 1 `EXTERNAL_PRIMARY`
- Content SHA-256: `1f0132aa223e8f405ed8e5fdf18a55e2ea14553f5bb886c988779e000d42dc67`
- Transcript SHA-256: `98a445aca49ef9d0a6fa6b2c86959b0291307297a12ff59e98759085b275ca6f`
- Acquisition/normalization: `youtube-v1` / `external-text-v1`

## E. Transcript statistics

2,151 ordered raw segments retain exact start/end timestamps and language.
Raw text is immutable; conservative Persian normalization is stored separately.

## F. Extraction windows

The default remains configurable 50/8. Live QA intentionally exercised two
configurations on the same source version:

- 500/50: 5 windows; 1 succeeded and 4 timed out, retained as a partial run.
- 200/32: 13 windows; all 13 succeeded in a separate run.

The partial run demonstrates failure isolation and review capture rather than
being erased. The successful run ID is
`adf9cd83-2e5f-4598-a06f-96b77331d419`.

## G. Cache behavior

An exact rerun of the successful 200/32 configuration reused all 13 successful
window results: 13 hits, 0 misses, 0 model calls, and no duplicate source,
version, run, mention, claim, or entity rows.

## H. People extracted

The live corpus contains 71 deduplicated candidate people after both retained
extraction runs. Mentions remain occurrence records and uncertain identities
remain reviewable.

## I. Works extracted

The live corpus contains 17 candidate works. Strong DOI/ISBN/OpenAlex/Open
Library identifiers are normalized through globally unique typed identifier
records; fuzzy ambiguity never auto-merges.

## J. External claims

The successful run produced 338 claims; the retained live corpus contains 372
claims across both runs. Every machine-extracted claim is `attributed_only`.
Citation resolution does not promote support or verification.

## K. Resolution statistics by provider

A bounded live resolution QA processed 10 mentions, retained 21 candidates,
and isolated one provider request failure without aborting the batch. Candidate
rows were Crossref 10 and Wikidata 11; OpenAlex and Open Library produced no
retained candidate for this Persian sample. All 10 remained unresolved under
the strict thresholds, which is preferable to a false identity match.

## L. Review cases

The final live review queue contains 425 records. It includes each extracted
identity occurrence, four timed-out window failures, and unresolved/ambiguous
resolution cases. Nothing uncertain was silently selected.

## M. Media assets

One YouTube thumbnail was downloaded once from provider metadata, validated as
an image, stored through content-addressed object storage, and linked to the
source. Its rights status remains `unknown`; attribution is retained. Tests
also cover SHA reuse, inaccessible PDF status, PDF magic/MIME validation, and
verified first-page-only PyMuPDF rendering.

## N. Manual QA

Timestamp samples at segments 1, 500, 1000, 1500, and 2151 matched the live
caption sequence (0.520 through 6,837.800 seconds). Representative extracted
references were pinned to exact segments/times, including Cornelius Ryan at
segment 8 (23.039s), Anthony Hopkins at segment 13 (41.039s), and Montgomery at
segment 63 (208.159s). Representative claims retained speaker attribution
language and `attributed_only` status. The structural validator returned valid
with zero issues.

## O. Tests

The suite covers URL/ID parsing, normalization, windows/overlap, structured
Codex invocation, invalid output, source/version/run idempotency, changed
content, timestamp/raw provenance, claim authority, identifier deduplication,
resolver uncertainty, provider isolation, media/PDF behavior, migrations,
API/read services, and existing Ayin/Manasek behavior.

- Unit tests: 58 passed
- Importer tests: 6 passed
- Integration tests: 18 passed
- Full Phase 1–4 suite: 82 passed

PyMuPDF 1.28 emits one interpreter-shutdown SWIG deprecation warning on Python
3.13 after its real render test; it is upstream-only and no test failed.

## P. Ruff and mypy

Ruff formatting checked 125 files and lint passed. Strict mypy passed for 93
source/test files.

## Q. Migration verification

PostgreSQL 17 and pgvector 0.8.1 were healthy. Clean upgrade, Alembic drift,
downgrade to base, re-upgrade, and repeated upgrade are exercised on disposable
databases. `alembic current` reported `2d874648966b (head)` and `alembic check`
reported no new operations. Repeated upgrade was a no-op. The Compose database
was healthy on PostgreSQL 17.8 with pgvector 0.8.1. The application image built
successfully as `emtedad-app:phase4`.

## R. Authority confirmation

The existing source state remains one `AYIN_WORKING` and one
`MANASEK_WORKING`. External material exists only as `EXTERNAL_PRIMARY`.

## S. Canon confirmation

There are zero `AYIN_CANON` and zero `MANASEK_CANON` versions. Phase 4 exposes
no approval or promotion path.

## T. Scope confirmation

No retrieval chunks, FTS retrieval, embeddings, vector indexes, RRF,
reranking, Ayin-external dialogue classification, research package, lecture,
localization, or publishing implementation was introduced. Phase 5 remains
pending owner review.

## Verification command record

```bash
uv add 'httpx>=0.28,<1' 'youtube-transcript-api>=1.2,<2' \
  'yt-dlp>=2025.9,<2027' 'rapidfuzz>=3.14,<4' 'pymupdf>=1.26,<2'
uv sync --all-groups --frozen
docker compose up -d db
docker compose ps
uv run alembic revision --autogenerate -m 'add external knowledge ingestion'
uv run alembic upgrade head
uv run alembic upgrade head
uv run alembic current
uv run alembic check
uv run ruff format --check .
uv run ruff check .
uv run mypy app tests
uv run pytest tests/unit -q
uv run pytest tests/importers -q
EMTEDAD_DATABASE_URL=postgresql+psycopg://... uv run pytest tests/integration -q
EMTEDAD_DATABASE_URL=postgresql+psycopg://... uv run pytest -q
uv run python -m app.cli knowledge ingest-youtube 331XLUCCybU \
  --window-size 500 --overlap 50
uv run python -m app.cli knowledge ingest-youtube 331XLUCCybU \
  --window-size 200 --overlap 32
uv run python -m app.cli knowledge ingest-youtube 331XLUCCybU \
  --window-size 200 --overlap 32
uv run python -m app.cli knowledge resolve-pending \
  --source-id 91f42e55-d01c-4dd8-9be4-792658753a2a --limit 10
uv run python -m app.cli knowledge validate
docker build -t emtedad-app:phase4 .
git diff --check
```

Database URLs above were supplied through environment variables and are
redacted in this audit. The integration migration test independently executed
clean upgrade, drift check, downgrade to base, re-upgrade, and repeat upgrade
against disposable databases.
