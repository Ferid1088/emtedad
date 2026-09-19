# Pending Phase: Phase 4 — External Knowledge Ingestion

## Execution status

Phase 3 is complete as of 2026-09-19. Phase 4 is prepared for
repository-owner review but is not active. Do not implement Phase 4 until the
owner explicitly approves this plan. Do not begin Phase 5 retrieval.

Completion evidence for the prior phase:
`docs/audits/PHASE_3_COMPLETION.md`.

## Goal

Create provenance-preserving external-knowledge ingestion with a reusable
adapter boundary and a YouTube-first implementation. Preserve immutable source
versions, raw transcripts/timestamps, extraction provenance, typed claims,
references, resolution uncertainty, and epistemic/source-quality metadata.

External material may support, challenge, illustrate, or parallel Ayin. It
cannot redefine Ayin, become Canon, or inherit authority from agreement with
Ayin.

## Required review before activation

Before implementation, the repository owner should review:

1. the explicitly authorized initial channels/items and the rights basis for
   metadata, transcripts, captions, thumbnails, and any retained media;
2. whether Phase 4 stores metadata/transcripts only or permits bounded source
   media download for the approved fixtures;
3. API credentials, quota/rate-limit policy, and secret ownership for YouTube
   and any reference-resolution providers;
4. transcript language/translation policy and handling of absent, generated,
   or edited captions;
5. source-quality and epistemic-status taxonomies, including which values are
   machine proposals versus editorial decisions;
6. the boundary between deterministic reference parsing and uncertain external
   identity resolution;
7. privacy, takedown, retention, and audit expectations for external material.

Unresolved rights, deployment, backup, privacy, and editorial-governance items
remain explicit review items and must not be silently decided by code.

## In scope

- generic, typed ingestion-adapter interfaces;
- YouTube creator/channel/item identities and immutable item versions;
- source URLs, provider IDs, acquisition times, checksums, and request/config
  provenance;
- immutable raw captions/transcripts with original timestamps and language;
- deterministic normalized/extraction windows that retain ordered raw-segment
  provenance;
- creator, organization, person, work, and reference mention records;
- typed claims and claim versions with exact source-segment provenance;
- resolution candidates and explicit unresolved/ambiguous review state;
- source-quality, discourse/epistemic role, uncertainty, and attribution
  metadata without unsupported verification claims;
- content-addressed asset links through typed foreign keys;
- caching, rate-limit handling, retry classification, idempotency, and
  transaction rollback;
- operator CLI, structural validators, thin read-only API routes, migrations,
  fixtures, and serious unit/importer/integration/failure tests.

## Out of scope

- broad or unauthorized crawling;
- silently downloading or redistributing media without an approved rights
  decision;
- treating an attributed statement as verified evidence;
- inventing DOI, ISBN, publication year, journal, publisher, author, or work
  identities;
- Ayin-to-external dialogue relations (Phase 6);
- embeddings, vector indexes, hybrid retrieval, RRF, reranking, or search
  evaluation (Phase 5);
- research packages, Ayin Spines, lectures, localization, publishing, ritual
  playback, music, or TTS;
- generic `owner_type`/`owner_id` relationships.

## Required invariants

- Provider source identity, immutable source/item version, acquisition run, raw
  transcript segment, derived extraction window, claim, and reference
  resolution are separate identities.
- Re-ingesting unchanged provider content is idempotent. Changed provider
  content creates a retained source version rather than overwriting history.
- Every derived segment and claim traces to ordered immutable raw segments and
  their exact source version.
- Original timestamps, source language, provider caption kind, and acquisition
  provenance are retained.
- External content uses only `EXTERNAL_PRIMARY` or `EXTERNAL_DERIVED`; it cannot
  enter an Ayin or Manasek Canon/Working zone.
- Uncertain reference resolution retains all candidates and review evidence;
  it never manufactures a canonical external identity.
- Claims distinguish attribution, source assertion, evidence status,
  interpretation, criticism, and uncertainty.
- Important relationships use typed foreign keys with explicit cascade
  behavior.

## Required tests

- exact-repeat idempotency and changed-content versioning;
- adapter/configuration changes create acquisition/extraction runs rather than
  false intellectual source versions;
- raw timestamp and language preservation;
- ordered raw-to-derived segment provenance;
- transcript absence, disabled captions, generated captions, partial data,
  rate limits, retryable errors, permanent errors, and rollback;
- typed claim provenance and no automatic truth/verification promotion;
- reference extraction with resolved, ambiguous, and unresolved outcomes;
- no fabricated identifiers or bibliographic facts;
- zone separation and no Ayin/Manasek Canon mutation;
- secret-safe logs and stored diagnostics;
- CLI/API thinness, migrations, downgrade/re-upgrade, repeat upgrade, and drift;
- no Phase 5 retrieval tables, embeddings, or behavior.

## Acceptance criteria

- The repository owner explicitly approves this Phase 4 plan and the bounded
  initial source/rights scope.
- Authorized YouTube fixtures/items ingest reproducibly and idempotently with
  complete immutable provenance.
- Raw transcript/timestamp history and derived-window lineage are queryable.
- Claims and references preserve attribution, uncertainty, candidates, and
  review state without invented certainty.
- All authoritative relationships use typed foreign keys; no generic owner IDs
  are introduced.
- Formatting, linting, strict typing, clean/reversible migrations, focused
  tests, failure tests, and the full suite pass.
- Phase 4 evidence and a pending Phase 5 plan are written before Phase 4 is
  marked complete.

## Expected verification commands

```bash
uv sync --all-groups --frozen
docker compose up -d db
uv run alembic upgrade head
uv run alembic current
uv run alembic check
uv run ruff format --check .
uv run ruff check .
uv run mypy app tests
uv run pytest tests/unit -q
uv run pytest tests/importers -q
uv run pytest tests/integration -q
uv run pytest -q
```

The approved implementation must also exercise exact-repeat and changed-source
imports on a disposable database, provider failure fixtures, validator output,
zone counts, manual source-to-segment-to-claim provenance QA, Docker build, and
a downgrade/re-upgrade cycle.
