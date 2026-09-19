# Data Model Blueprint

This is a conceptual blueprint, not a substitute for reviewed SQLAlchemy models
and Alembic migrations. Phase 1 establishes schema, naming, transaction, and
type conventions. Each later phase owns its domain tables and executable
constraints.

## Cross-cutting rules

- Every authoritative relationship uses a foreign key. Important cross-domain
  relationships use typed association tables; unconstrained
  `owner_type`/`owner_id` pairs are not authoritative links.
- Primary-key strategy, timestamp type, and identifier serialization must be
  selected once in the Phase 1 foundation ADR and applied consistently.
- Timestamps are timezone-aware. State and role values are typed and protected
  by database constraints or PostgreSQL enums where migration safety justifies
  them.
- Database constraints protect invariants independently of Pydantic or service
  validation. Cascade behavior is explicit on every foreign key.
- Approved versions and frozen snapshots are immutable. Correction creates a
  new version or an explicit superseding record; history is not overwritten.
- Original bytes and raw source text are immutable. Normalized text, chunks,
  embeddings, summaries, and translations are separately versioned derivatives.
- JSONB is reserved for provider/configuration metadata that is genuinely
  variable. Fields used for identity, authority, joins, state, filtering, or
  constraints remain typed columns.
- Corpus zone and epistemic/discourse role remain queryable throughout all
  derived artifacts.

## Schema ownership

| Schema | Owns | Initial phase |
|---|---|---:|
| `core` | Ayin documents/versions/passages, ontology, terminology, editorial state | 2 |
| `ritual` | Manasek documents/versions, ritual structures, safety, localizations | 3 |
| `knowledge` | External sources, segments, entities, claims, evidence, reference resolution | 4 |
| `retrieval` | Chunks, search documents, model configurations, embeddings, runs, evaluations | 5 |
| `content` | Spines, plans/packages, masters, citations, localizations, publishing, dependencies | 7-10 |
| `ops` | Immutable asset identity, jobs/runs, audit events, cache metadata, operational review infrastructure | 1 and extended by owning phases |

Phase 1 creates namespaces and foundation-only tables justified by its accepted
plan. It does not create placeholder tables for later domains.

## Shared operational infrastructure

### Immutable assets

Use one `ops.object_assets` identity for immutable bytes:

- checksum and checksum algorithm;
- byte size and verified media type;
- storage backend/key;
- original filename as untrusted display metadata;
- acquisition/provenance metadata;
- creation and verification timestamps.

The checksum is unique within its algorithm. Storage keys are unique and cannot
contain path traversal. Domain ownership is represented by typed association
tables such as a Canon-version source asset or external-source media asset,
each with real foreign keys. This replaces the specification's illustrative
generic media owner pair where relational integrity would otherwise be lost.

### Jobs and attempts

- `ops.jobs`: stable job identity, job type, idempotency key, current typed
  state, input hash/configuration identity, and timestamps;
- `ops.job_runs`: attempt number, worker identity, start/end, result identity,
  explicit error classification, and redacted diagnostic metadata.

The job-type/idempotency-key pair is unique. Domain stage state remains in its
own schema when it is part of the business artifact rather than only execution
telemetry.

### Audit and review

- `ops.audit_events` is append-oriented and records authenticated actor,
  action, reason, transaction/correlation identity, and a descriptive target
  locator. It is operational evidence, not a substitute for domain foreign
  keys.
- Review state and assignment may share an operational base record, but each
  important review target uses a typed domain association table. Canon,
  terminology, ritual, relation, citation, localization, and source-impact
  reviews must not point through an unconstrained generic owner ID.

### Model and cache identity

Provider/model identity may be shared in `ops` if multiple domains use it;
retrieval-specific dimensions, distance metric, and language capability remain
in `retrieval`. Phase 5 must settle the exact split without duplicating model
identity. Cache records key immutable input hashes together with task, prompt,
provider/model, and configuration versions.

## Ayin Canon

- Canon documents and immutable versions;
- reproducible extraction runs separated from source/editorial versions, with
  toolchain, normalization, segmentation, configuration, and output hashes;
- extracted passages with PDF index, printed label where present, heading path,
  sequence, raw text, normalized search text, and exact source
  asset/version/run;
- concepts and concept versions;
- distinctions and their sides/relationships;
- principles;
- open questions and status history;
- discourse types;
- multilingual terminology, aliases, forbidden equivalents, and review state.

Critical constraints:

- approved versions cannot be mutated;
- extraction tooling changes create runs, not source/editorial versions;
- a source version has at most one explicitly selected preferred extraction,
  while all prior runs and passage sets remain retained;
- a document has at most one effective approved version for a validity instant;
- canonical objects pin their source version and, where asserted from text,
  their source passage;
- preferred terms are unique within language, scope, and effective interval;
- superseding creates history rather than destructive replacement;
- generated/external content cannot be assigned a Canon zone through an
  ordinary content workflow.

The source PDF's editorial status and initial semantic version are unresolved
review items; the importer must not assume them.

## Manasek

- Manasek documents and immutable versions;
- ritual families and ritual versions;
- exactly five gate definitions per approved architecture version;
- seven individual stage definitions;
- five ordered gate pieces and one distinct Return per individual stage;
- separate collective structures;
- ritual elements, timed instructions, and media intents;
- Ayin concept links;
- safety rules, validation results, exclusions, and review records;
- localized ritual text that preserves safety requirements.

Critical constraints:

- Return has its own type and cannot be represented as a gate;
- an approved individual architecture contains 35 gate pieces and seven
  Returns, for 42 pieces total;
- individual and collective structures cannot share an architecture type or be
  silently transformed into one another;
- approved ritual versions are immutable;
- failed or unresolved safety validation blocks approval/publication;
- consent, optionality, stop, and leave rules cannot be weakened by
  localization.

Aggregate counts require database-enforced designs appropriate to PostgreSQL,
such as constrained slots plus deferred validation. Service-only counting is
insufficient.

Phase 3 implements this design in the `ritual` schema. Source versions and
extraction runs are separate; passages pin both. Stable family, gate, ritual,
and safety-rule identities have source-backed versions. `architecture_versions`
distinguish `INDIVIDUAL` and `COLLECTIVE`; relational sequence items encode the
seven-by-six individual cycle, while `returns` adds a checked Return-only
extension. Cues, music specifications, localizations, Ayin concept links,
safety bindings/results, and review flags all retain typed provenance.

Deferred PostgreSQL constraint triggers validate approved architecture
completeness and ritual/localization publishability. Approved source,
architecture, ritual, localization, gate, family, and safety versions are
immutable. Current imported records remain Working/draft or review. See
ADR-006 for the implemented boundary.

## External knowledge

- creators, organizations, channels, and source identities;
- source items and immutable source versions;
- typed source-asset/media association tables;
- transcripts and immutable timestamped segments;
- normalized/extraction windows derived from raw segments;
- people, works, references, identifiers, and resolution candidates;
- claims and claim versions;
- evidence relations, criticism, alternatives, and confidence metadata;
- source-quality and epistemic metadata.

Phase 4 implements this domain with separate `sources`, immutable
`source_versions`, exact `source_segments`, configurable `extraction_windows`,
typed window-to-segment membership, configuration-pinned `extraction_runs`,
and independently retryable `window_results`. People, works, organizations,
concepts, labels, strong identifiers, mentions, candidates, attributed claims,
evidence links, media links, quality records, and review flags use typed foreign
keys. See ADR-007.

Critical constraints:

- raw content, timestamps, page references, and acquisition provenance are
  preserved;
- source ingestion is idempotent by source identity/version and content hash;
- derived text points back to ordered raw segments;
- canonical external identities are deduplicated without deleting mention or
  candidate provenance;
- uncertain resolution remains reviewable and cannot manufacture DOI, ISBN,
  journal, year, publisher, or identity;
- an attributed statement is not automatically verified evidence.

## Retrieval

- retrieval chunks and parent/child relationships;
- normalized lexical-search documents and named language configurations;
- embedding model configurations and embeddings;
- retrieval runs and lane-specific results;
- fusion, reranking, and context-expansion results;
- evaluation queries, relevance judgments, and metrics.

Every result preserves corpus zone, epistemic role, immutable source version,
source location, query/filter configuration, and model/configuration identity.
Raw cross-corpus vector score never encodes authority.

Embedding storage accommodates versioned model records without silently
accepting the wrong vector dimension. Phase 5 uses pgvector with a database
trigger that checks each vector against its registered model dimensions. The
initial 131-chunk corpus uses exact cosine search; no HNSW or IVFFlat index is
created before multilingual scale/recall benchmarks justify one.

## Research and lectures

- lecture projects, topics, and types;
- Ayin Spines and validation results;
- ResearchPlans;
- immutable ResearchPackage versions with typed evidence membership;
- Semantic Master versions;
- sections and statement/claim identities;
- statement-to-Canon, statement-to-external-claim, and citation edges as typed
  relations;
- fidelity, epistemic, citation, terminology, and localization QA reports;
- Persian, English, and Arabic localizations;
- publication packages, channels, states, and versions;
- typed dependency and staleness records.

Critical constraints:

- a lecture cannot enter research without a valid, Canon-grounded Ayin Spine;
- ResearchPackage versions are immutable snapshots;
- the writer cannot add evidence outside its package without creating a new
  package version;
- every localization points to one Semantic Master version;
- concept IDs, claim IDs, citations, uncertainty, and epistemic status survive
  localization;
- localized enrichment is separately sourced and reviewable;
- publication never promotes an output to Canon;
- dependency changes mark review state without rewriting published history.

## State and approval history

Current state may be stored on an aggregate for efficient filtering, but every
approval, supersession, publication, failure, and review transition that affects
reproducibility also has a durable history/audit record. Transitions are
performed by services with explicit authorization and transaction boundaries.
Critical states use shared typed definitions rather than free-form strings.

## Index policy

Start with primary keys, foreign-key indexes where justified by access paths,
unique constraints, and B-tree/partial indexes for relational filters. Add:

- GIN only for measured full-text or JSONB access;
- GiST for an operator class or exclusion constraint that requires it;
- `pg_trgm` indexes for measured fuzzy resolution needs;
- HNSW or IVFFlat only after multilingual retrieval benchmarks justify the
  algorithm and parameters.

Every non-obvious index must name the query it serves and carry benchmark
evidence in its phase report or an ADR. Indexes cannot compensate for missing
authority filters or provenance columns.
