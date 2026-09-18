# Next Phase: Phase 2 - Ayin Canon (Pending User Review)

## Execution status

Phase 1 is complete. This Phase 2 plan is prepared for review but is not active.
Do not implement it until the repository owner explicitly approves the plan and
resolves or accepts the listed Phase 2 review dependencies.

## Goal

Create a provenance-preserving, versioned Ayin data model and importer that can
store Working and approved Canon states without conflating them. Import
`Ayin_Emtedad_Baznevisi_Shodeh.pdf` only as `AYIN_WORKING`, preserve its exact
bytes and page-aware text, expose ambiguity through typed review records, and
establish the ontology and terminology structures required by later phases.

No operation may silently promote Working material to `AYIN_CANON`. A future
approval must create or transition to a specifically approved, immutable
version while retaining every historical Working and superseded version.

## Binding source-status decisions

- `Ayin_Emtedad_Baznevisi_Shodeh.pdf` is `AYIN_WORKING`.
- `Manasek_V1.pdf` is `MANASEK_WORKING` and is not imported in Phase 2.
- Neither source has canonical approval.
- Working versions may have no editorial semantic version; database constraints
  must require approval metadata and a semantic version before an approved
  Canon state can exist.
- Rights, approval authority, and editorial governance remain review items.
  They block public distribution and real Canon approval, not local Working
  import and schema development.

## Required inputs

Before implementation, read:

1. `AGENTS.md`
2. this document after user approval
3. `docs/audits/PHASE_1_COMPLETION.md`
4. `docs/specification/MASTER_IMPLEMENTATION.md`, especially sections 2-8,
   43-45, 57-59, 61-64, 67-A, 68, and 69
5. all architecture documents and accepted ADRs
6. the complete Ayin PDF, with page-aware visual inspection for importer
   validation
7. existing Phase 1 code, migration, and tests

## Review dependencies before activation

The repository owner should review these choices before Phase 2 starts:

1. Confirm that a Working import may use the source SHA-256 as its immutable
   technical identity while leaving editorial `semantic_version` null.
2. Confirm that location identity stores PDF page index, printed page label when
   present, heading path, and passage sequence rather than choosing only one.
3. Decide whether Phase 2 should import only passages plus an editorial seed
   manifest, or whether editors will supply a separate reviewed ontology
   manifest for concepts, distinctions, principles, open questions, and terms.
   The implementation must not infer these as approved facts from LLM output.
4. Confirm that Canon approval remains disabled until editor identities,
   authorization, and approval authority are specified.

If item 3 is not resolved, Phase 2 may implement and validate the schema and
Working passage import but cannot claim the structured ontology acceptance
criteria complete.

## In scope

- `ops.object_assets` for immutable object metadata, backed by the Phase 1
  storage protocol;
- typed `core` association from Ayin document versions to source assets;
- corpus-zone, editorial-status, discourse-type, and review-state types without
  magic strings;
- Ayin documents and immutable document versions;
- page-aware canonical/working passages with raw and normalized text kept
  separately;
- concepts and versioned definitions;
- versioned principles, distinctions, concept relations, and open questions;
- Persian/English/Arabic-ready terminology entities and versioned term forms,
  including forbidden equivalents and review status;
- typed, Ayin-specific review records and target relations with real foreign
  keys;
- database enforcement for immutable approved versions, valid status metadata,
  source/version pinning, and typed cascade behavior;
- an idempotent Ayin Working import service and explicit CLI command;
- read services and thin API routes for versions, passages, concepts,
  distinctions, principles, open questions, and terminology;
- migration, unit, integration, importer, immutability, and failure-path tests;
- README instructions limited to commands that are implemented and verified.

## Out of scope

- importing or modeling Manasek;
- promoting the supplied Ayin source to Canon;
- a public Canon approval endpoint before authorization/governance exists;
- inventing semantic versions, approvers, translations, definitions,
  distinctions, or source wording;
- AI/LLM extraction or hidden model calls;
- external knowledge, YouTube, claims, reference resolution, or media
  enrichment;
- retrieval chunks, full-text search tuning, embeddings, vector indexes, or
  RAG;
- Ayin-external relations, research plans/packages, lectures, localization,
  publishing, or staleness propagation beyond recording version dependencies;
- Manasek or ritual safety behavior;
- generic `owner_type`/`owner_id` relationships.

## Proposed file boundaries

| Path | Responsibility |
|---|---|
| `app/core/ayin/domain.py` | Typed states and pure Ayin version policies |
| `app/core/ayin/models.py` | `core` SQLAlchemy models for documents, versions, passages, ontology, and typed review targets |
| `app/core/ayin/schemas.py` | Pydantic command/query and API boundary schemas |
| `app/core/ayin/repository.py` | Ayin persistence queries; no commits |
| `app/core/ayin/service.py` | Transactional version, query, and approval-guard behavior |
| `app/core/ayin/importer.py` | Page-aware, idempotent Working import orchestration |
| `app/core/terminology/models.py` | Terms and term-form versions |
| `app/core/terminology/repository.py` | Terminology persistence and lookup |
| `app/core/terminology/service.py` | Preferred/forbidden form policy and review behavior |
| `app/ops/assets/models.py` | Immutable object metadata only |
| `app/ops/assets/repository.py` | Asset identity/checksum persistence |
| `app/api/routes/ayin.py` | Thin Ayin read/import transport routes if HTTP import is approved |
| `app/cli.py` | Explicit command entry point; no business logic |
| `alembic/versions/*_ayin_working_canon.py` | Phase 2 schema and constraints |
| `tests/unit/core/` | Domain/status/normalization/terminology policy tests |
| `tests/integration/core/` | Constraints, repositories, transactions, and API tests |
| `tests/importers/` | Exact PDF identity, page order, idempotency, and ambiguity tests |
| `tests/fixtures/ayin/` | Small synthetic or explicitly reviewed fixtures; no fabricated Canon |

Names may be refined before implementation if one coherent module removes
duplication, but route, service, repository, domain policy, and storage
boundaries must remain explicit.

## Data and constraint requirements

### Assets and source versions

- asset SHA-256 and storage key are unique;
- exact source hash remains
  `676c210e0ef6be5f0fe5228190f63d9e38f39dccc7a9ea6b0b815d487124566c`;
- a typed Ayin-version/source-asset relation uses real foreign keys;
- one importer version plus source hash is idempotent;
- raw source bytes are never overwritten or stored as PostgreSQL BLOBs.

### Documents and versions

- source zone is explicit and constrained;
- the supplied source enters only `AYIN_WORKING`;
- approved status requires non-null semantic version, approver identity,
  approval timestamp, and effective date according to the reviewed governance
  design;
- approved rows are immutable at the database layer;
- supersession creates a new version and retains the prior one;
- no ordinary content or import operation can assign `AYIN_CANON`.

### Passages

- each passage pins one document version and source asset;
- page index, printed label, heading path, sequence, raw text, normalized text,
  language, and content hash are distinct fields;
- raw text is not altered by normalization;
- passage sequence is unique within a version;
- duplicate content does not erase distinct source locations;
- ambiguous extraction creates a typed review item rather than guessed text.

### Ontology and terminology

- concept identity is stable while definitions are versioned;
- principles, distinctions, relations, and open questions pin source passages
  and document versions where the source supports them;
- every structured assertion carries a discourse type;
- important terms are not auto-translated or auto-approved;
- preferred-form uniqueness is constrained by language, scope, version, and
  effective interval;
- forbidden equivalents remain queryable and versioned;
- every important relation uses typed foreign keys.

## Import behavior

1. Verify the exact PDF SHA-256 before parsing.
2. Store/reuse the immutable source asset through `ObjectStore`.
3. Create or reuse one Ayin document identity.
4. Create or reuse one `AYIN_WORKING` document version keyed by source hash and
   importer version.
5. Extract pages without overwriting raw text; store printed labels separately
   when they can be established.
6. Apply deterministic, versioned search normalization only to the normalized
   field.
7. Validate page count, passage order, hashes, required metadata, and
   bidirectional-text edge cases.
8. Load only reviewed structured ontology/terminology seed data. Machine or
   heuristic candidates remain Working review proposals.
9. Commit the operation transactionally; retries reuse the same immutable
   identities.
10. Emit a report with created/reused counts, ambiguities, and review items.

## Required tests

- corpus-zone separation and no silent Canon promotion;
- approval metadata/check constraints;
- approved-version database immutability;
- version pinning and supersession history;
- source asset checksum/storage identity;
- exact 146-page source validation and stable page order;
- raw versus normalized text separation;
- repeated import returns the same version/passages without duplicates;
- changed importer version produces an explicit new derived import identity;
- transaction rollback leaves no partial document/version/passages;
- concept-version and source-passage retrieval;
- distinction integrity and discourse-type persistence;
- open-question state history;
- preferred-term uniqueness and forbidden-equivalent lookup;
- ambiguity creates a typed review target with a real foreign key;
- API/CLI routes remain thin and never commit or approve directly;
- migration upgrade, downgrade, re-upgrade, and Alembic drift checks.

## Risks and controls

| Risk | Control |
|---|---|
| Working text accidentally treated as Canon | Zone/status constraints, disabled approval path, API labels, and negative tests |
| RTL extraction changes canonical wording | Preserve exact bytes/raw output, page identity, extraction version, content hashes, and review items |
| Ontology inferred without editorial authority | Accept only reviewed seed input; candidates remain Working and unapproved |
| Approved history can be edited | Database immutability enforcement plus service and integration tests |
| Generic relations weaken integrity | Typed source, review, ontology, and terminology foreign-key tables |
| Duplicate imports | Source hash + importer version idempotency and unique constraints |
| PDF parser/library drift | Lock parser version and store importer/configuration version |
| Rights uncertainty | Limit to local Working import; no public source-text endpoint or redistribution claim |
| Schema overreach into Manasek/retrieval | Diff review and explicit absence checks for later-phase tables/dependencies |

## Acceptance criteria

- The plan has been explicitly approved for execution.
- The supplied Ayin PDF is stored/imported only as `AYIN_WORKING`.
- No `AYIN_CANON` version exists unless a separately authorized approval
  fixture/workflow satisfies every governance and metadata constraint.
- Exact source bytes and recorded SHA-256 are preserved outside PostgreSQL.
- Import is transactional and idempotent.
- Page/passage order, raw text, normalized text, locations, and extraction
  version are reproducible and reviewable.
- Structured ontology and terminology contain only reviewed source-backed
  material or clearly labeled Working candidates.
- Approved-version immutability and historical retention are enforced by the
  database and tested.
- All authoritative relations use foreign keys; there are no unconstrained
  generic owner IDs.
- Routes and CLI delegate to services; repositories do not commit.
- Migration upgrade/downgrade/re-upgrade and drift checks pass on a disposable
  database.
- Formatting, linting, strict typing, focused tests, and the full suite pass.
- No Phase 3 or later behavior is introduced.
- Phase 2 evidence, master-plan status, and the pending Phase 3 plan are written
  before Phase 2 is marked complete.

## Verification commands

The approved implementation must retain the Phase 1 checks and add focused
Phase 2 commands, expected to include:

```bash
uv sync --all-groups --frozen
uv run ruff format --check .
uv run ruff check .
uv run mypy app tests
docker compose up -d db
uv run alembic upgrade head
uv run alembic current
uv run alembic check
uv run pytest tests/unit/core -q
uv run pytest tests/integration/core -q
uv run pytest tests/importers -q
uv run pytest -q
```

Run the reviewed Ayin Working import command twice against a disposable
database, compare identities and counts, verify the source hash and 146-page
contract, verify zero unauthorized Canon versions, and perform a documented
migration downgrade/re-upgrade cycle.

## Exact next task after approval

Implement only this reviewed Phase 2 plan. Do not implement Manasek or any
later-phase feature, and do not create a Canon approval path until editorial
identity and authorization requirements are explicitly resolved.
