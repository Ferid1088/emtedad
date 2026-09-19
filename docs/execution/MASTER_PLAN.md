# Master Implementation Plan

## Status legend

- `pending`: not started
- `in_progress`: active implementation phase
- `blocked`: cannot proceed without a recorded decision or dependency
- `complete`: all acceptance criteria verified with evidence

Only one phase may be `in_progress` at a time.

## Program status

- Active phase: None; Phase 3 is pending repository-owner review
- Last completed checkpoint: Phase 2.1 - Ayin Provenance Stabilization
  (2026-09-19)
- Application runnable: Yes; health, PostgreSQL readiness, Ayin read API, CLI
  import, and structural validation are verified
- Open blocker: None remaining for Phase 2. Phase 3 requires explicit approval
  of its prepared plan and review dependencies. Rights, deployment, backup,
  privacy, and editorial governance remain recorded later-phase/production
  review items.

## Phase plan

| Phase | Name | Status | Primary outcome |
|---:|---|---|---|
| 0 | Repository Audit | complete | Verified bootstrap baseline, source inspection, requirements mapping, and Phase 1 plan |
| 1 | Platform Foundation | complete | Runnable FastAPI/PostgreSQL foundation |
| 2 | Ayin Canon | complete | Versioned Working/Canon corpus boundary and Working ontology |
| 2.1 | Provenance Stabilization | complete | Source versions separated from reproducible extraction runs |
| 3 | Manasek | pending | Versioned ritual model and safety validation |
| 4 | External Knowledge Ingestion | pending | Provenance-preserving adapters, YouTube first |
| 5 | Retrieval | pending | Multilingual, lane-specific hybrid retrieval |
| 6 | Ayin–External Dialogue | pending | Typed relations, classification, criticism and review |
| 7 | Research Engine | pending | Ayin Spine, ResearchPlan and frozen ResearchPackage |
| 8 | Lecture Master | pending | Cited Semantic Master and validators |
| 9 | Three Languages | pending | FA/EN/AR localization with fidelity QA |
| 10 | Content Strategy and Publishing | pending | Series, coverage and publication packages |
| 11 | Evaluation | pending | Gold sets, fidelity fixtures and benchmarks |

## Phase 0 — Repository Audit

Deliverables:

- Repository and source inventory
- Reusable/replace/refactor assessment
- Existing test and data baseline
- Requirements coverage check
- Database/data migration assessment
- Risks, contradictions, and review questions
- Executable Phase 1 plan

Verified result (2026-09-18):

- Confirmed a bootstrap-only repository with no application code, dependency
  manifest, database, migrations, tests, containers, CI, or application data.
- Inventoried all repository areas, Git state, ignored local environment, and
  source files.
- Inspected all 146 Ayin pages and 42 Manasek pages through extraction and
  all-page rendering; recorded immutable SHA-256 identities.
- Confirmed the source-backed domain invariants required at Phase 0 scope and
  recorded the unresolved Canon/Working status rather than assuming approval.
- Mapped all master-specification sections 0-70 to Phases 0-11, including
  cross-cutting ownership and previously implicit Codex CLI/canon-revision work.
- Determined there is no legacy data to migrate; later PDF ingestion is a new,
  provenance-preserving import.
- Refined the modular-monolith architecture and data-model blueprint without
  creating Phase 1 code.
- Replaced the active phase with a bounded, executable Phase 1 plan.

Completion evidence: `docs/audits/PHASE_0_REPOSITORY_AUDIT.md`

## Phase 1 — Platform Foundation

Target scope: PostgreSQL 17, pgvector, Docker Compose, SQLAlchemy 2, Alembic,
schemas/namespaces, configuration, logging, storage abstraction, health checks,
and core tests.

Verified result (2026-09-18):

- Locked a CPython 3.13 `uv` environment and recorded foundation choices in
  ADR-004.
- Added the FastAPI factory, typed configuration, secret-safe structured logs,
  request correlation, explicit errors, and thin health routes.
- Added async SQLAlchemy 2/psycopg infrastructure with application-owned
  transactions.
- Started and verified PostgreSQL 17.8 with pgvector 0.8.1 through Docker
  Compose.
- Applied Alembic revision `20260918_0001`, creating the six empty schemas and
  no future-domain tables or vector indexes.
- Verified clean upgrade, downgrade, re-upgrade, repeated upgrade, current head,
  and no Alembic drift on disposable databases.
- Added and tested content-addressed immutable local storage with atomic
  publication, idempotency, corruption detection, and path/symlink containment.
- Built and ran the application image; source PDFs, tests, secrets, and local
  storage are excluded from it.
- Verified live/ready HTTP 200 behavior and live HTTP 200/ready HTTP 503 during
  a real database outage without logging connection details.
- Passed Ruff, strict mypy, 25 unit tests, 3 integration tests, and all 28 tests
  with zero warnings.
- Confirmed no Phase 2 implementation or generic owner relation was added.

Completion evidence: `docs/audits/PHASE_1_COMPLETION.md`

## Phase 2 — Ayin Canon

Target scope: canon documents, versions, passages, concepts and their versions,
distinctions, principles, open questions, discourse types, terminology,
importers, immutability, and version-pinning tests.

Verified result (2026-09-18):

- Added the typed, versioned Ayin document, passage, ontology, concept-relation,
  terminology, review, and immutable source-asset model through Alembic revision
  `20260918_0002`.
- Imported the exact 146-page source as `AYIN_WORKING`/`draft` with verified
  SHA-256, 1,019 host-extracted passages, source-pinned Working ontology and
  terminology, and 56 explicit extraction review items.
- Kept raw and normalized text separate, retained exact source bytes outside
  PostgreSQL, and used typed foreign keys throughout without generic owner IDs.
- Enforced Canon approval metadata and approved-version immutability at the
  database layer while exposing no approval command or endpoint.
- Verified transactional rollback, idempotent repeat import, parser provenance,
  read API/CLI behavior, structural validation, migration
  downgrade/re-upgrade and drift checks, Docker image construction, Ruff,
  strict mypy, and all 46 tests.
- Confirmed zero `AYIN_CANON` versions and no Phase 3 implementation.

Completion evidence: `docs/audits/PHASE_2_COMPLETION.md`.

## Phase 2.1 — Ayin Provenance Stabilization

Verified result (2026-09-19):

- Separated intellectual document, source/editorial version, extraction run,
  and extracted passage-set identities in ADR-005 and Alembic revision
  `20260918_0003`.
- Keyed Working source identity by document, exact SHA-256, corpus zone, and
  explicit source-version metadata rather than extraction tooling.
- Added immutable extraction-run provenance for importer, extractor,
  normalization, segmentation, configuration, source asset, output hash, page
  count, and passage count.
- Added an integrity-safe, one-row-per-source-version preferred-extraction
  table with explicit selector and reason. Imports do not auto-select a run.
- Added extraction-run-pinned review metadata with specific reason, status,
  reviewer notes, and review time while retaining all 56 flagged passages per
  real extraction run.
- Verified the exact PDF with host Poppler 26.08.0 and container Poppler
  25.03.0 as one `AYIN_WORKING` source version, two extraction runs, and
  independent 1,019/1,018-passage sets. Structured concept identities remained
  20 concepts and 20 concept versions.
- Passed clean migrations, legacy Phase 2 data backfill, guarded duplicate
  handling, repeat-import idempotency, preference switching/history, Ruff,
  strict mypy, and all 49 tests.
- Confirmed zero `AYIN_CANON` versions and no Phase 3 implementation.

Completion evidence: `docs/audits/PHASE_2_1_STABILIZATION.md`.

## Phase 3 — Manasek

Target scope: ritual families, five gates, seven stages, Return, separate
collective architecture, versions, concept links, importers, safety policies,
and structural validators.

Pending plan: `docs/execution/CURRENT_PHASE.md`. It is not authorized for
implementation until repository-owner review.

## Phase 4 — External Knowledge Ingestion

Target scope: generic adapters, YouTube-first ingestion, immutable transcripts,
timestamps, extraction, claims, references, resolution, media, caching, and
idempotency.

## Phase 5 — Retrieval

Target scope: retrieval chunks, multilingual normalization, full-text search,
pgvector, embedding registry, separate retrieval lanes, RRF, reranking, parent
expansion, filters, and evaluation fixtures.

## Phase 6 — Ayin–External Dialogue

Target scope: relation taxonomy, epistemic evidence classification, proposed
relation review, conflicts, counterevidence, and uncertainty.

## Phase 7 — Research Engine

Target scope: Ayin Spine, ResearchPlan, lane-aware retrieval orchestration, and
immutable/versioned ResearchPackage snapshots.

## Phase 8 — Lecture Master

Target scope: lecture types, argument grammar, Semantic Master, statement-level
claim/citation graph, Ayin fidelity, epistemic, citation, and counterargument
validation.

## Phase 9 — Three Languages

Target scope: Persian, English, and Arabic localization; terminology QA;
cross-language fidelity; localized enrichment; shared concept, claim, and
citation identities; publication states.

## Phase 10 — Content Strategy and Publishing

Target scope: topic graph, series, coverage analysis, publishing channels,
publication packages, stale-content detection, and review workflow.

## Phase 11 — Evaluation

Target scope: multilingual retrieval gold set, lecture fidelity fixtures,
ritual safety tests, end-to-end acceptance suite, benchmark command, and report.

## Mandatory end-of-phase gate

Every phase must:

1. satisfy its written acceptance criteria;
2. pass relevant and full test suites;
3. document migrations and commands;
4. keep the application runnable;
5. expose ambiguity through review queues;
6. update this plan with evidence rather than assertion.
