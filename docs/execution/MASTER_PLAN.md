# Master Implementation Plan

## Status legend

- `pending`: not started
- `in_progress`: active implementation phase
- `blocked`: cannot proceed without a recorded decision or dependency
- `complete`: all acceptance criteria verified with evidence

Only one phase may be `in_progress` at a time.

## Program status

- Active phase: Multichannel Phase 21 — complete (pending owner review)
- Last completed checkpoint: Phase 21 - legacy 100-lesson retirement and
  speech_structure consolidation onto knowledge/structure (2026-10-03)
- Last completed checkpoint: Phase 12 - approved Persian multilingual production
  (2026-09-23)
- Latest architectural checkpoint: Phase 12 - lesson-canon generation boundary
  (ADR-013; full-book Ayin RAG removed from ordinary script generation)
  (2026-09-24)
- Latest owner-UI checkpoint: canonical lesson catalog, lesson-aware Studio and
  text provenance, separated external research, and published-only channel
  memory; legacy topic-tree UI retired (2026-09-24)
- Application runnable: Yes; health, PostgreSQL readiness, Ayin, Manasek,
  external-knowledge, and retrieval APIs/CLIs and validators are verified
- Open blocker: None remaining for Phase 8. Phase 9 requires explicit approval
  of its prepared plan. Rights, deployment, backup, privacy, and editorial
  governance remain recorded later-phase/production review items.

## Phase plan

| Phase | Name | Status | Primary outcome |
|---:|---|---|---|
| 0 | Repository Audit | complete | Verified bootstrap baseline, source inspection, requirements mapping, and Phase 1 plan |
| 1 | Platform Foundation | complete | Runnable FastAPI/PostgreSQL foundation |
| 2 | Ayin Canon | complete | Versioned Working/Canon corpus boundary and Working ontology |
| 2.1 | Provenance Stabilization | complete | Source versions separated from reproducible extraction runs |
| 3 | Manasek | complete | Versioned ritual model and safety validation |
| 4 | External Knowledge Ingestion | complete | Provenance-preserving adapters, YouTube first |
| 5 | Retrieval | complete | Multilingual, lane-specific hybrid retrieval |
| 6 | Ayin–External Dialogue | complete | Typed relations, classification, criticism and review |
| 7 | Research Engine | complete | Ayin Spine, ResearchPlan and frozen ResearchPackage |
| 8 | Lecture Master | complete | Cited Semantic Master and validators |
| 9 | Four Languages | complete | FA/DE/EN/AR localization, pronunciation QA, and voice boundary |
| 10 | Content Strategy and Publishing | complete | Series, coverage and publication packages |
| 11 | Evaluation | complete | Owner source/topic discovery and validation checkpoints |
| 12 | Emtedad Editorial Pipeline | complete | Lesson canon, research workspace, Persian approval, multilingual text output |
| 21 | Legacy 100-Lesson Retirement | complete | Resource-first production only: lesson canon frozen, generic writing package extracted, knowledge/structure consolidated as canonical Vortragsstruktur |

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

Verified result (2026-09-19):

- Added a dedicated, typed `ritual` schema with Manasek document/source version,
  extraction-run, run-pinned passage, architecture, ritual, cue, music,
  localization, Ayin-link, safety, and review records through Alembic revision
  `20260919_0004`.
- Imported the exact 42-page PDF as one `MANASEK_WORKING` / `draft` source
  version. Host Poppler 26.08.0 and container Poppler 25.03.0 produced two
  independently retained 42-passage extraction runs without duplicating stable
  ritual identities.
- Represented five ordered gates, seven stages, 35 gate pieces, seven
  separately typed Returns, the 42-piece individual sequence, and one separate
  collective architecture. Database constraints make Return-as-gate and
  Working-as-approved invalid.
- Stored 224 timed cues, 43 source-preserving music specifications, Persian
  draft localizations, 62 resolved typed Ayin links, and one reviewable
  `horizontal_emtedad` proposal without inventing a Canon concept.
- Added 33 versioned safety rules and deterministic structural/safety
  validation. All imported rituals retain the complete safety binding set and
  remain non-publishable drafts.
- Verified clean/repeat/reversible migrations, drift, exact/idempotent imports,
  transaction rollback, API/CLI reads, page-aware manual QA, Docker image,
  Ruff, strict mypy, and the full Phase 1–3 suite.
- Confirmed zero `MANASEK_CANON` and `AYIN_CANON` versions and no Phase 4
  implementation.

Completion evidence: `docs/audits/PHASE_3_COMPLETION.md`.

## Phase 4 — External Knowledge Ingestion

Verified result (2026-09-19):

- Added generic adapters and a real YouTube implementation with immutable
  source versions, exact timestamped raw segments, separate normalization,
  deterministic overlapping windows, and independent cached extraction jobs.
- Added typed external identities, labels, strong identifiers, mentions,
  attributed claims, evidence links, resolver candidates, quality metadata,
  content-addressed media links, and review state in `knowledge`.
- Integrated replaceable structured LLM extraction through non-interactive
  Codex CLI and Crossref, OpenAlex, Open Library, and Wikidata resolvers.
- Verified reversible/drift-free migrations, failure isolation, exact-repeat
  cache reuse, live YouTube acquisition/extraction, and no Phase 5 behavior.

Completion evidence: `docs/audits/PHASE_4_COMPLETION.md`.

## Phase 5 — Retrieval

Target scope: retrieval chunks, multilingual normalization, full-text search,
pgvector, embedding registry, separate retrieval lanes, RRF, reranking, parent
expansion, filters, and evaluation fixtures.

Verified result (2026-09-19):

- Built immutable/versioned chunks over Ayin Working, Manasek Working
  structured ritual content, and external primary segments with typed source
  membership and complete provenance.
- Added multilingual normalization, PostgreSQL FTS, pinned multilingual E5
  embeddings, exact cosine search, entity-aware retrieval, deterministic RRF,
  deterministic reranking, and source-local context expansion.
- Preserved lane authority through explicit per-lane fusion and deterministic
  lane interleaving; similarity never promotes Canon or implies evidence.
- Passed Persian, English, and Arabic retrieval evaluation, steady-state
  latency, reversible migrations, structural validation, and full checks.

Completion evidence: `docs/audits/PHASE_5_COMPLETION.md`.

## Phase 6 — Ayin–External Dialogue

Target scope: relation taxonomy, epistemic evidence classification, proposed
relation review, conflicts, counterevidence, and uncertainty.

Verified result (2026-09-22):

- Added typed, version-pinned Ayin/external dialogue targets and evidence,
  immutable machine proposals, append-only human review decisions, review flags,
  and deterministic proposal-run/pair-level cache provenance through Alembic
  revision `26a7bca28432`.
- Added the explicit relation/scope taxonomy with first-class negative,
  non-equivalence, and unresolved relations. No generic `SUPPORTS_AYIN` edge
  exists.
- Added structured `EvidenceRoleClassifier`, Ayin testability classification,
  deterministic `DialogueEpistemicValidator`, targeted Phase 5 retrieval,
  counterevidence search, API/CLI review surfaces, and dependency staleness
  reporting.
- Ran a six-target live pilot over the current external corpus: 18 candidates,
  14 conservative proposed relations, all still `PROPOSED`; zero external
  claims were upgraded and no Ayin/Manasek record was modified.
- Structural validators all passed. Clean/repeat/reversible migrations,
  Alembic drift, Ruff, strict mypy, Docker build, and the full 116-test suite
  passed. No lecture workflow was added.

Completion evidence: `docs/audits/PHASE_6_COMPLETION.md`.

## Phase 7 — Research Engine

Target scope: Ayin Spine, ResearchPlan, lane-aware retrieval orchestration, and
immutable/versioned ResearchPackage snapshots.

Verified complete 2026-09-23. See `docs/audits/PHASE_7_COMPLETION.md`.

## Phase 8 — Lecture Master

Target scope: lecture types, argument grammar, Semantic Master, statement-level
claim/citation graph, Ayin fidelity, epistemic, citation, and counterargument
validation.

Verified complete 2026-09-23. See `docs/audits/PHASE_8_COMPLETION.md`.

## Phase 9 — Four Languages

Target scope: Persian, German, English, and Arabic localization; terminology QA;
cross-language fidelity; localized enrichment; shared concept, claim, and
citation identities; publication states.

## Phase 10 — Content Strategy and Publishing

Target scope: topic graph, series, coverage analysis, publishing channels,
publication packages, stale-content detection, and review workflow.

Verified complete 2026-09-23. See `docs/audits/PHASE_10_COMPLETION.md`.

## Phase 11 — Owner MVP Web App

Target scope: owner source ingestion, knowledge-base browsing, grounded topic
discovery, and advisory topic persistence. No research or lecture generation.

Verified complete 2026-09-23. See `docs/audits/PHASE_11_OWNER_MVP_WEB_APP.md`.

## Phase 11 — Evaluation

Target scope: multilingual retrieval gold set, lecture fidelity fixtures,
ritual safety tests, end-to-end acceptance suite, benchmark command, and report.

## Multichannel program (EMTEDAD_CODING_AGENT_MASTER_IMPLEMENTATION_PROMPT)

A second, separate program began in parallel after Phase 12: migration to a
resource-first multi-channel studio. Its phases are numbered 0–19 in that
prompt. Status here refers to those phases.

| Phase | Name | Status | Primary outcome |
|---:|---|---|---|
| 0 | Baseline + ADR | complete | Baseline gates, ADR-014, audit `MULTICHANNEL_PHASE_0_BASELINE.md` |
| 1 | EditorialChannel domain | complete | Five seeded channels, versioned strategies, source assignment |
| 2 | Studio UI shell | complete | Studio workspace, resource library, channel pages |
| 3 | YouTube import | complete | Existing ingest verified, processing state on import |
| 4 | Source structure | complete | `source_structure_nodes`, two-pass agent, validator, states |
| 5 | Knowledge Units | complete | Atomic units, deterministic full_text, validator |
| 6 | Concept mapping | complete | Unit–concept links, concept relationships |
| 7 | Retrieval V2 | complete | FTS+dense+concept hybrid over units, structural expansion |
| 8 | Dynamic Topic Engine | complete | Resource-derived TopicCandidate mining, strategy-weighted scoring, gap rule |
| 9 | ContentBrief | complete | Gated brief contract (§9.2), channel+strategy pinned |
| 10 | Distinctiveness | complete | ScriptSignature + ACCEPT/REPLAN/REVIEW_REQUIRED planner |
| 11 | Generic Research | complete | Brief-origin plan/package, EvidenceMatrix, frozen snapshot |
| 12 | Argument Architect | complete | Versioned ArgumentPlan, gated on EvidenceMatrix |
| 13 | Narrative Architect | complete | Versioned NarrativePlan, gated on ArgumentPlan |
| 14 | Generic Script | complete | ScriptDraft gated on NarrativePlan; no canon dependency |
| 15 | Review Pipeline | complete | Five critics, typed findings, revision, approve gate |
| 16 | Channel review packs | complete | Per-channel checks in CHANNEL_REVIEW_CHECKS |
| 17 | Production workspace | complete | `/studio/production/{brief_id}`, backend-driven actions |
| 18–19 | Library/detail UI | complete | `/library` + resource detail tabs (earlier phases) |
| 20 | Publication targets | complete | `PublicationTarget` model; no auto-publish |
| 20a | Generic Semantic Master | complete | `CONTENT_BRIEF`-origin `LectureMasterVersion` via `GenericMasterService`; script gated on READY master; no lesson/canon dependency |
| 21 | Retire 100-lesson path | pending | Prerequisite met; needs owner deletion decision |
| P4 | Provider capacity + semantic certification | owner review | Class-aware provider capacity + orphan sweep + quota backoff; 81 real candidates; live review→revision chains in 2 channels; merge/voice/duration defects found and fixed; `NO_API_KEY` web research documented |
| P5 | Cost-quality multi-model pipeline | owner review | APIMaster role routing + telemetry (single external gateway; no batch API — premium runs synchronously); Persian approval gate on all localization; shared semantic package; native DE/EN/AR pipeline with bounded loops and fidelity gates; historical OpenRouter canary in `docs/audits/COST_QUALITY_CONTENT_PIPELINE.md` |
| P5c | APIMaster final quality certification | owner review | Fail-closed provider routing (`allow_devin_runtime_fallback` opt-in); all role-less callers given explicit AgentRoles; URL-grounded research via Tavily/custom/Wikipedia (APIMaster refused as retrieval); live A/B rejected qwen for all four prep roles (50% schema, 2–3× slower, weaker judged quality) → remapped to Sol; Astra Persian writer certified (best rev native 8.5 / evidence 9.0 / 25.3 min; revs 2+ regress → best-of-N); scoped protected-terminology + in-loop deterministic duration + bounded duration-only repairs; historical approved master flagged evidence 4.0 / ~7 min under today's critics — owner re-review item. Evidence: `docs/audits/APIMASTER_CERTIFICATION.md` |

Evidence: `docs/audits/MULTICHANNEL_PHASE_0_BASELINE.md`,
`docs/audits/MULTICHANNEL_PHASE_1_EDITORIAL_CHANNELS.md`,
`docs/audits/MULTICHANNEL_PHASES_4_7.md`,
`docs/audits/MULTICHANNEL_PHASES_8_20.md`,
`docs/audits/MULTICHANNEL_GENERIC_MASTER_PATH.md`.

## Mandatory end-of-phase gate

Every phase must:

1. satisfy its written acceptance criteria;
2. pass relevant and full test suites;
3. document migrations and commands;
4. keep the application runnable;
5. expose ambiguity through review queues;
6. update this plan with evidence rather than assertion.
