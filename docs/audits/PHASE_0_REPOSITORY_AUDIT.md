# Phase 0 Repository Audit

- Audit date: 2026-09-18
- Phase: 0 - Repository Audit
- Repository state observed: Git initialized on `main`, no commits, all bootstrap
  files untracked
- Scope: repository baseline, source-material inspection, specification coverage,
  architecture refinement, migration assessment, and Phase 1 planning

## 1. Executive summary

### Observed facts

This is a documentation-and-source bootstrap, not an existing application. It
contains governance documents, a 2,863-line implementation specification, three
accepted ADRs, two source PDFs, execution prompts, and a minimal editor setting.
It contains no application package, dependency manifest or lockfile, database
schema, migration, test, container configuration, CI configuration, operational
script, or persisted application data.

The two supplied PDFs are readable, have embedded fonts, contain extractable
text, have no encryption, forms, JavaScript, or embedded attachments, and match
the central structural claims in the specification at the level required for
Phase 0. The Ayin source is 146 pages; the Manasek source is 42 pages. The
Manasek source directly states the five-gate, seven-stage, seven-Return,
42-piece individual structure, a separate collective structure, and explicit
consent and exit safeguards.

There is no legacy application or database to migrate. The safe implementation
path is a greenfield, phase-owned modular monolith. The only local executable
environment is an ignored `.venv` for an unrelated `sample-python-scripscrap`
project. It is evidence about the workstation, not a reusable project
dependency baseline.

### Recommendations

Phase 1 should create only the platform foundation: a pinned Python project,
FastAPI shell, PostgreSQL 17/pgvector Compose service, SQLAlchemy/Alembic
infrastructure, PostgreSQL namespaces, typed configuration, structured logging,
an immutable-object storage interface, health checks, and focused tests. It
must not create Ayin, Manasek, ingestion, retrieval, or lecture domain tables.

Before Phase 2 imports source material, editorial review must resolve whether
the Ayin PDF labeled as a working version is approved as the initial
`AYIN_CANON` version or must enter `AYIN_WORKING`. Source ownership, license,
approved version identifiers, and authorized editors also remain unresolved.

## 2. Repository inventory

### Version-control and filesystem state

| Area | Observed fact | Disposition |
|---|---|---|
| Git | Repository is on `main`, has no commits, and reports the bootstrap files as untracked. | Preserve; user decides when to create the first commit. |
| Root metadata | `.gitignore`, `.python-version`, `.vscode/settings.json`, `AGENTS.md`, `README.md`, and `START_CODEX.md` exist. | Reuse governance; expand tooling in Phase 1. |
| Documentation | Architecture, audit, decision, execution, source-material, and specification directories exist. | Reuse and version. |
| Prompts | Current-phase implementation and completed-phase review prompts exist. | Reuse. |
| Application | No `app/`, `src/`, or equivalent package exists. | Create in Phase 1. |
| Dependencies | No `pyproject.toml`, lockfile, requirements file, or package metadata exists. | Create and pin in Phase 1. |
| Database | No SQLAlchemy models, SQL, Alembic tree, or database dump exists. | Greenfield foundation in Phase 1. |
| Tests | No tests or test configuration exist. | Create foundation tests in Phase 1. |
| Containers | No Compose file, Dockerfile, or environment example exists. | Create database Compose configuration and app development contract in Phase 1. |
| Automation | No scripts, task runner, pre-commit configuration, or CI exists. | Add only the minimum verification surface justified by Phase 1. |
| Local artifacts | Two unignored `.DS_Store` files exist. `tmp/` is not ignored. | Do not treat as project inputs; add appropriate ignore rules in Phase 1. |
| Local virtual environment | Ignored `.venv` uses CPython 3.13 and is named `sample-python-scripscrap`; it contains PyMuPDF, RapidFuzz, Requests, and `youtube-transcript-api`, among other transitive packages. | Replace for project work; never infer production dependencies from it. |

Excluding `.git`, `.venv`, and Phase 0 temporary inspection output, the
repository has 22 files: 16 Markdown files, two PDFs, two `.DS_Store` files,
one JSON editor setting, one `.gitignore`, and one `.python-version`.

### Source-material inventory

| Source | Observed metadata | SHA-256 | Phase 0 validation |
|---|---|---|---|
| `Ayin_Emtedad_Baznevisi_Shodeh.pdf` | 146 pages; PDF 1.7; A5-like page size; Persian; tagged; no encryption, forms, JavaScript, or attachments | `676c210e0ef6be5f0fe5228190f63d9e38f39dccc7a9ea6b0b815d487124566c` | Cover, contents, all-page visual contact sheets, extractability, and domain-invariant passages inspected. |
| `Manasek_V1.pdf` | 42 pages; PDF 1.7; US Letter; Persian with embedded English music-generation prompts; tagged; no encryption, forms, JavaScript, or attachments | `f5f07580d10b165b07513fe802ca86d8969cbe24a9d110d208b424c58c73f1af` | All-page visual contact sheets, extractability, ritual structure, collective separation, and safety language inspected. |

The extracted text contains bidirectional-ordering and character artifacts, so
raw extracted text cannot be treated as editorially exact without page-aware
import validation. Phase 2 and Phase 3 must preserve the original PDF bytes and
raw extraction alongside any normalized search representation.

## 3. Existing architecture and dependency baseline

### Observed facts

- `DOMAIN_RULES.md` accurately summarizes the non-negotiable source zones,
  Ayin/Manasek separation, lecture invariants, multilingual contract, and
  ambiguity rule.
- ADR-001 fixes PostgreSQL 17, pgvector, PostgreSQL full-text search,
  SQLAlchemy 2, and Alembic.
- ADR-002 fixes separate knowledge domains and retrieval lanes.
- ADR-003 fixes one Semantic Master with aligned Persian, English, and Arabic
  realizations.
- The architecture documents describe the intended domains but previously did
  not fix module dependency direction, schema ownership, Phase 1 boundaries,
  or the handling of generic owner links.
- `.python-version` contains `3.13`, which satisfies the stated Python 3.11+
  minimum. The supported-version policy and production base image are not yet
  recorded.
- No dependency versions are project-owned. Packages installed in `.venv` are
  neither declared nor reproducible and must not be reused implicitly.

### Refined baseline

The evidence supports a modular monolith with one deployable FastAPI process
and phase-owned modules. PostgreSQL schemas are authority boundaries, not
microservices. Dependency direction is from API and workflows into services,
repositories, and domain objects; domain logic must not depend on FastAPI.
Cross-domain reads use explicit services/repositories, and cross-domain writes
remain transactional where they share PostgreSQL.

LangGraph is not a Phase 1 dependency. It becomes eligible in Phase 7 only if a
checkpointed research workflow demonstrates that ordinary service orchestration
is insufficient.

## 4. Reuse, refactor, replace, or remove assessment

| Item | Classification | Rationale / action |
|---|---|---|
| `AGENTS.md` | Reuse | Clear repository-level scope, domain, database, verification, and phase gates. |
| `README.md` | Refactor incrementally | Accurate bootstrap description; Phase 1 must replace bootstrap-only setup with runnable setup while preserving mission and authority order. |
| `START_CODEX.md` | Reuse as historical bootstrap | Correctly initiated Phase 0; it should not be treated as the active plan after this audit. |
| `MASTER_IMPLEMENTATION.md` | Reuse as implementation specification | Broad and internally useful; Phase mapping and contradictions are recorded below rather than rewriting the specification. |
| `DOMAIN_RULES.md` | Reuse | Matches source and specification at the audited level. |
| `SYSTEM_ARCHITECTURE.md` | Refactor | Add modular-monolith boundaries, dependencies, schema ownership, trust boundaries, and phase sequencing. |
| `DATA_MODEL.md` | Refactor | Resolve generic-owner conflict, make version/provenance patterns explicit, and assign schema ownership. |
| ADR-001 through ADR-003 | Reuse | Accepted and consistent with the target architecture. |
| `MASTER_PLAN.md` | Refactor | Mark Phase 0 complete with evidence and Phase 1 active. |
| `CURRENT_PHASE.md` | Replace | Phase 0 is complete; document must become the executable Phase 1 plan. |
| Prompt files | Reuse | They reinforce scope and completion gates. |
| Source PDFs | Reuse as immutable inputs | Preserve exact bytes and hashes; editorial zone/status remains a review decision. |
| `.python-version` | Reuse provisionally | Python 3.13 meets the minimum; Phase 1 must test and document supported runtime versions. |
| `.vscode/settings.json` | Reuse | Harmless editor metadata; not an application configuration source. |
| `.venv` | Replace | Unrelated, unpinned, ignored environment; recreate from the Phase 1 lockfile. |
| `.DS_Store` files | Remove from project surface | Local Finder metadata; ignore and delete separately when authorized. |

## 5. Requirements-to-phase coverage findings

The following matrix maps every numbered specification section. “Cross-cutting”
means the owning phase implements its portion and later phases extend it; it is
not permission to implement future-domain behavior early.

| Spec section | Owning phase(s) | Coverage finding |
|---|---:|---|
| 0. V2 corrections | 0-11 | Cross-cutting acceptance constraints; retained in domain rules and phase gates. |
| 1. Project mission | 0-11 | Cross-cutting; architecture and README. |
| 2. Source-of-truth hierarchy | 1, 2-10 | Phase 1 namespace/constants contract; domain persistence in owning phases. |
| 3. Canonical Ayin principles | 2, 8, 11 | Structured Canon in Phase 2; generation enforcement Phase 8; fixtures Phase 11. |
| 4. PostgreSQL domain separation | 1 | Explicit Phase 1 namespace creation. |
| 5. Canon document versioning | 2 | Covered. |
| 6. Ayin ontology | 2 | Covered. |
| 7. Four discourse types | 2, 8, 9, 11 | Persistence then generation/localization enforcement and evaluation. |
| 8. Terminology registry | 2, 9 | Registry then localization QA. |
| 9. Manasek layer | 3 | Covered. |
| 10. Five gates | 3 | Covered. |
| 11. Seven-stage individual architecture | 3 | Covered. |
| 12. Horizontal Emtedad | 2, 3 | Canon concept and ritual relation. |
| 13. Machine-enforced ritual safety | 3, 9, 11 | Core validator, localized enforcement, safety evaluation. |
| 14. External ingestion | 4 | Covered. |
| 15. Reference resolution | 4 | Covered. |
| 16. External claims/evidence | 4, 6 | Extraction in Phase 4; classified dialogue relations in Phase 6. |
| 17. Ayin-external dialogue | 6 | Covered. |
| 18. Source quality metadata | 4, 6 | Capture in Phase 4; policy use in Phase 6. |
| 19. Media assets | 1, 4 | Storage contract in Phase 1; knowledge media/provenance in Phase 4. |
| 20. Retrieval chunks | 5 | Covered. |
| 21. Multilingual normalization | 5 | Covered. |
| 22. Embedding registry | 5 | Covered; shared `model_registry` naming must be reconciled then. |
| 23. Multi-lane retrieval | 5 | Covered. |
| 24. Hybrid retrieval algorithm | 5 | Covered. |
| 25. Ayin Spine | 7 | Covered. |
| 26. Lecture types | 8 | Covered. |
| 27. Content strategy | 10 | Covered; explicitly separate from ritual stages. |
| 28. Research planner | 7 | Covered. |
| 29. Research Package V2 | 7 | Covered. |
| 30. Epistemic evidence classifier | 6, 7 | Taxonomy/classifier in Phase 6; package use in Phase 7. |
| 31. Semantic Master | 8 | Covered. |
| 32. Lecture argument grammar | 8 | Covered. |
| 33. Statement-level citation graph | 8 | Covered. |
| 34. Three-language strategy | 9 | Covered. |
| 35. Core evidence/local enrichment | 9 | Covered. |
| 36. Terminology QA | 9 | Covered. |
| 37. Localization fidelity QA | 9 | Covered. |
| 38. Ritual links in lectures | 8, 9 | Master relation in Phase 8; localization preservation Phase 9. |
| 39. Separate ritual-generation workflow | Deferred, 3/9 | Conditional future workflow; Phase 3 owns safety-ready draft state, Phase 9 may localize approved ritual text. No autonomous ritual generation is currently authorized. |
| 40. Lecture workflow | 7-9 | Split by research, master, and localization ownership; LangGraph decision deferred to Phase 7. |
| 41. Ayin fidelity validator | 8 | Covered. |
| 42. Counterargument requirement | 7, 8 | Package requirement then lecture validation. |
| 43. Human review/governance | 1-10 | Phase 1 establishes audit/review conventions only; domain approval workflows remain phase-owned. |
| 44. Canon revision workflow | 2, 10 | Version/revision mechanics in Phase 2; downstream impact analysis in Phase 10. |
| 45. Staleness/impact analysis | 10 | Covered, with dependency edges created by owning phases. |
| 46. Series/publishing | 10 | Covered. |
| 47. RAG answering vs lecture generation | 5, 7, 8 | Retrieval interfaces and separate Ayin/lecture workflows. General chat product behavior remains an explicit future decision. |
| 48. Research reproducibility | 5, 7 | Retrieval-run capture then immutable package snapshot. |
| 49. Cache/cost optimization | 1, 4-9 | Phase 1 idempotency/cache contracts; domain caches only when their inputs exist. |
| 50. PostgreSQL/pgvector | 1, 5 | Platform/extension in Phase 1; vector usage in Phase 5. |
| 51. Multilingual RAG evaluation | 11 | Covered. |
| 52. Content quality metrics | 8, 9, 11 | Validator dimensions in Phases 8/9; benchmark reports Phase 11. |
| 53. Initial YouTube ingestion | 4 | Covered. |
| 54. External extraction | 4 | Covered. |
| 55. Codex CLI provider | 4 | Previously implicit; now explicitly assigned to Phase 4 behind an LLM provider interface. |
| 56. Storage efficiency | 1, 4, 5 | Storage contract then ingestion/retrieval efficiency. |
| 57. Idempotency | 1, 4-10 | Conventions in Phase 1; behavior in each job-producing phase. |
| 58. Pipeline state | 1, 2, 4, 7-10 | Typed state conventions first, domain state machines when implemented. |
| 59. API | 1-10 | Health in Phase 1; domain endpoints only in owning phases. |
| 60. Project structure | 1 | Adapted to a modular monolith; no empty future-module scaffolding. |
| 61. Testing | 1-11 | Tests land with owning behavior; full evaluation in Phase 11. |
| 62. Database constraints | 1-10 | Naming/convention foundation then phase-owned relational constraints. |
| 63. Review queues | 2-10 | Domain-specific typed targets; no unconstrained generic owner relation. |
| 64. README requirements | 1-10 | Incremental; only verified commands documented in each phase. |
| 65. Long-term architecture | 0, 1 | Captured in architecture and enforced incrementally. |
| 66. Implementation phases | 0-11 | All 12 phases retained. |
| 67. End-to-end acceptance | 11 | Final acceptance suite, with earlier behaviors proven in their phases. |
| 68. Generation rules | 7-9, 11 | Enforced in workflow/validators and evaluated. |
| 69. Coding style | 1-11 | Cross-cutting implementation standard. |
| 70. Start now | 0 | Satisfied by this audit and executable Phase 1 plan; no Phase 1 code created. |

### Coverage gaps corrected by this audit

- The Codex CLI provider is assigned explicitly to Phase 4.
- Canon revision mechanics are assigned to Phase 2, while downstream staleness
  remains Phase 10.
- Human review, cache, idempotency, API, README, and testing requirements are
  recognized as phase-owned cross-cutting work rather than one late feature.
- Ritual generation remains conditional and unauthorized; safety and data
  structures do not imply automatic generation.
- General conversational RAG is named but lacks a product/API contract. It is
  recorded for review rather than silently included in Phase 5.

## 6. Data and migration assessment

### Observed facts

- There is no application database, dump, migration history, structured Canon,
  transcript collection, embedding index, or generated-content dataset.
- The only project data are the two PDFs and documentation.
- The ignored virtual environment is executable tooling, not migratable data.

### Assessment

No legacy data migration is required or possible. Phase 1 starts a new Alembic
history. Phase 2 and Phase 3 will perform provenance-preserving imports, not
legacy migrations. Each import must register exact source bytes, SHA-256,
source metadata, extraction version, and page/location identity before creating
normalized or structured derivatives.

The PDFs can be imported safely only after the following controls exist:

1. immutable raw-object storage and checksum verification;
2. explicit corpus-zone and editorial-status decisions;
3. page-aware extraction that retains raw and normalized forms;
4. idempotency based on source hash and importer version;
5. validation of passage count/order and review items for extraction ambiguity;
6. a rollback strategy that removes a failed import transaction without
   deleting the immutable source asset.

## 7. Security, privacy, licensing, and operational risks

| Risk | Evidence / impact | Required treatment |
|---|---|---|
| Source rights and license unknown | PDFs have no repository license or documented rights statement. | Record owner, permitted uses, redistribution policy, and attribution before exposing source text or media. |
| External-source terms and copyright | Planned YouTube, PDF, book, paper, and webpage ingestion may be restricted. | Store lawful-access provenance; do not bypass controls; define retention and quotation policies before Phase 4 production use. |
| Untrusted files and URLs | Future uploads and remote fetches can carry malicious content, oversized payloads, SSRF targets, or deceptive MIME types. | Enforce size/type limits, safe URL policy, quarantine/scanning decision, path containment, timeouts, and streaming. |
| Secrets leakage | Database URLs, provider credentials, and subprocess environments may leak through logs. | Environment-based secrets, redaction, `.env` exclusion, least privilege, and no secrets in command lines/logs. |
| Codex CLI subprocess | Phase 4 requires an external executable with filesystem and network implications. | Use argument arrays, allowlisted working directories, timeouts, output schemas, redaction, and no `shell=True`. |
| Review authorization undefined | Canon/ritual approval cannot be safely enforced without editor identities and roles. | Decide authentication/authorization boundary before write APIs for Canon or Manasek. |
| Audit-event integrity | Approval and revision history must be trustworthy. | Append-oriented audit records, authenticated actor identity, transaction coupling, and retention policy. |
| Ritual participant data | Future feedback or session data could be sensitive health/spiritual information. | Do not collect by default; define purpose, consent, minimization, retention, access, and deletion policy before any feature. |
| Backup/recovery absent | PostgreSQL and object storage will hold irreplaceable version/provenance data. | Add documented backup, restore, and integrity verification before production deployment. |
| Dependency/supply chain | No lockfile or automated dependency checks exist. | Pin dependencies, review licenses, generate repeatable environments, and add update/scanning policy. |
| Observability privacy | Structured logs can accidentally capture source text or user prompts. | Log identifiers and hashes by default; classify and redact content-bearing fields. |
| Local artifacts | `.DS_Store` is unignored; `tmp/` is not governed. | Ignore OS and local QA outputs and keep generated artifacts outside source control. |

## 8. Contradictions and missing decisions

### Confirmed specification tensions

1. **Working source versus Canon status.** The Ayin PDF cover identifies it as a
   working version for dialogue, critique, and development. The bootstrap and
   master specification call the supplied sources authoritative for the version
   to be ingested. This supports using the bytes as authoritative input, but it
   does not establish `AYIN_CANON` approval. Editorial status must be explicit.
2. **Generic owner links versus relational integrity.** The specification's
   sample `knowledge.media_assets(owner_type, owner_id)` and generic review
   targets conflict with the repository rule against unconstrained generic
   owner IDs. The architecture now requires one immutable asset record plus
   typed, foreign-keyed domain association tables.
3. **LangGraph mandate versus restraint.** The specification calls the lecture
   workflow LangGraph-compatible; repository rules allow LangGraph only where
   stateful orchestration is justified. Compatibility is required; adopting the
   library is a Phase 7 ADR decision based on checkpointing needs.
4. **`model_registry` naming and ownership.** The data-model blueprint places a
   shared model registry in infrastructure, while the specification names
   `retrieval.embedding_models`. Phase 5 must define whether a shared provider
   registry owns model identity with retrieval-specific configurations, without
   creating duplicate sources of truth.

### Missing decisions

- Initial Ayin and Manasek corpus zones, approval statuses, semantic version
  identifiers, effective dates, and approving editor(s).
- Source ownership, license, redistribution, quotation, and derivative-work
  permissions.
- Authentication mechanism, actor identity, editorial roles, and approval
  quorum/separation-of-duties policy.
- Deployment target, object-storage backend for production, backup targets,
  retention, recovery objectives, and network/security boundary.
- Supported Python version range versus one production version, and the
  production container base image.
- Sync versus async SQLAlchemy session strategy and worker/job execution
  mechanism. Phase 1 must record the foundation choice without adding a queue
  product prematurely.
- Exact canonical passage location semantics for pages with front matter,
  diagrams, repeated headers, bidirectional text, or embedded English prompts.
- Whether source page numbers mean PDF page index, printed page label, or both.
- Public/general RAG product scope and response contract.
- Privacy policy for future users, editorial comments, ritual feedback, and
  generated prompts.
- Accessibility, supported locales beyond `fa`, `en`, and `ar`, and locale
  variants within those languages.

## 9. Review queue

| ID | Priority | Owner needed | Review question | Blocks |
|---|---|---|---|---|
| P0-RQ-001 | Critical | Editorial authority | Source zones resolved on 2026-09-18 as `AYIN_WORKING` and `MANASEK_WORKING`; semantic versions, effective dates, and later approvers remain open. | Phase 2/3 approval and import publication |
| P0-RQ-002 | Critical | Rights owner / legal | Who owns each source, and what storage, extraction, quotation, translation, derivative, and publication rights are granted? | Public or production use |
| P0-RQ-003 | High | Product/editorial governance | Who may draft, review, approve, supersede, and deprecate Canon, terms, and rituals? | Canon/ritual write APIs |
| P0-RQ-004 | High | Platform owner | What is the first deployment target and production object-storage backend? | Production hardening, not local Phase 1 |
| P0-RQ-005 | High | Platform owner | What backup retention, restore objectives, and audit retention are required? | Production readiness |
| P0-RQ-006 | Medium | Editorial/import owner | Should page identity store PDF index, printed page label, named section location, or all three? | Phase 2 importer design |
| P0-RQ-007 | Medium | Product owner | Is general chat RAG in product scope, or are only search/research/lecture APIs required initially? | General RAG endpoint design |
| P0-RQ-008 | Medium | Security/privacy owner | Will user profiles, ritual participation, feedback, or sensitive free text be stored? | Privacy model and retention |
| P0-RQ-009 | Medium | Localization editors | Which locale variants and review authorities apply to Persian, English, and Arabic? | Phase 9 publishing policy |
| P0-RQ-010 | Low | Repository owner | Should the bootstrap files and Phase 0 result be committed as the initial checkpoint? | Version-history hygiene only |

Unknowns remain review items. None has been converted into invented canonical,
translation, ritual, licensing, or product facts.

### Post-audit source-status decision

On 2026-09-18, the repository owner resolved the status portion of P0-RQ-001:

- `Ayin_Emtedad_Baznevisi_Shodeh.pdf` is `AYIN_WORKING`;
- `Manasek_V1.pdf` is `MANASEK_WORKING`;
- neither source may be silently promoted to a canonical zone;
- later Canon approval must create a versioned approved state while retaining
  historical versions.

Semantic version identifiers, effective dates, approvers, rights, and the
approval workflow remain open. Those items do not block the Phase 1 technical
foundation.

## 10. Recommended Phase 1 boundaries

### Include

- reproducible Python project metadata and lockfile;
- FastAPI application factory and thin system routes;
- typed environment configuration with secret-safe representation;
- structured logging and request correlation;
- PostgreSQL 17 + pgvector local Compose service;
- SQLAlchemy 2 engine/session lifecycle and metadata conventions;
- Alembic with transactional creation of `core`, `knowledge`, `ritual`,
  `retrieval`, `content`, and `ops` namespaces plus required extensions;
- immutable-object storage protocol and safe local implementation;
- liveness and dependency-aware readiness checks;
- explicit exception boundary and testable service/repository layering;
- unit and PostgreSQL integration tests;
- updated runnable README and a foundation ADR for unresolved technical choices.

### Exclude

- all Ayin, terminology, Manasek, external-knowledge, retrieval, research,
  lecture, localization, publishing, and evaluation domain tables or behavior;
- importing either PDF;
- embedding or LLM dependencies;
- LangGraph;
- YouTube or bibliographic adapters;
- authentication/authorization implementation before governance requirements
  are known;
- a distributed job queue, cloud deployment, or premature microservices.

The executable deliverables, file boundaries, dependencies, risks, acceptance
criteria, and commands are now in `docs/execution/CURRENT_PHASE.md`.

## 11. Verification commands and results

| Command / check | Result |
|---|---|
| `git status --short --branch` | Passed inspection: `main`, no commits, bootstrap files untracked. |
| `find` inventory excluding `.git`, `.venv`, and temporary QA output | Passed: all repository areas and 22 project-surface files accounted for. |
| Presence checks for app, tests, manifests, migrations, containers, and scripts | Passed: all confirmed absent. |
| `.venv/pyvenv.cfg` and installed-distribution inventory | Passed: confirmed unrelated CPython 3.13 `sample-python-scripscrap` environment. |
| `pdfinfo` on both source PDFs | Passed: readable metadata and page counts; no encryption, forms, or JavaScript. |
| `shasum -a 256 docs/source_material/*.pdf` | Passed: hashes recorded in this audit. |
| `pdffonts` and `pdfdetach -list` | Passed: embedded fonts; zero embedded files in each PDF. |
| `pdftotext -layout` on both PDFs | Passed with expected RTL extraction artifacts; 21,019 and 15,027 extracted words respectively. |
| Low-resolution render of every PDF page plus contact-sheet visual review | Passed: every page rendered; no blank-run, clipping, or gross corruption detected. |
| Manual comparison of source structure against `DOMAIN_RULES.md` and specification | Passed at Phase 0 scope; core Ayin framing, Manasek counts/separation, and safety rules align. |
| Full reading of `MASTER_IMPLEMENTATION.md` and section-to-phase mapping | Passed: all sections 0-70 mapped above. |
| Application formatting, lint, typing, migration, and tests | Not applicable: no application/tooling exists in Phase 0. |

Phase 0 temporary PDF renders and extracted text were created under `tmp/pdfs/`
for read-only verification. They are not deliverables and must not be committed.
