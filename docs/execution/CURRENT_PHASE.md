# Pending Phase: Phase 3 — Manasek

## Execution status

Phase 2 is complete as of 2026-09-18. Phase 3 is prepared for repository-owner
review but is not active. Do not implement Phase 3 until the owner explicitly
approves this plan. Do not begin Phase 4.

Completion evidence for the prior phase:
`docs/audits/PHASE_2_COMPLETION.md`.

## Goal

Create a provenance-preserving, versioned Manasek model and importer that keeps
the supplied source in `MANASEK_WORKING`, represents its individual and
collective ritual architectures without conflation, and enforces ritual safety
as machine-testable policy.

Manasek remains the experiential/practical layer of Ayin. It is not evidence
that proves Ayin. No operation may silently promote Working material to
`MANASEK_CANON`.

## Binding source-status decisions

- `Manasek_V1.pdf` is `MANASEK_WORKING` unless a later explicit editorial
  approval promotes a specific version.
- Its recorded source identity is 42 pages with SHA-256
  `f5f07580d10b165b07513fe802ca86d8969cbe24a9d110d208b424c58c73f1af`.
- Import and structured Working proposals do not constitute Canon approval.
- Canon approval must create/version an approved state while retaining source,
  Working, superseded, and historical versions.
- Rights and editorial-governance questions remain review items. They do not
  block local Working import unless technically required by this phase.

## Required review before activation

Before implementation, the repository owner should review:

1. whether the existing Phase 2 document/version/passage tables should be
   generalized through typed shared abstractions or mirrored in the `ritual`
   schema without weakening the Ayin boundaries;
2. the reviewed seed-manifest ownership and source anchors for five gates,
   seven stages, seven Returns, collective structures, and safety rules;
3. which safety findings are hard blockers versus typed editorial review
   findings, while preserving the non-negotiable stop/leave/consent rules;
4. whether approval remains disabled until editor identities, authorization,
   and approval authority are specified;
5. the exact localization scope for Phase 3, particularly how safety language
   must remain invariant across Persian, English, and Arabic.

Unresolved points must remain explicit review items; they must not be filled by
LLM inference or invented ritual wording.

## In scope

- immutable Manasek documents and versions in the `ritual` schema;
- typed source-asset and source-passage provenance;
- ritual families and immutable/versioned ritual definitions;
- exactly five ordered gate definitions as symbolic attentional perspectives;
- exactly seven ordered individual stages;
- five gate pieces per individual stage, producing 35 gate pieces;
- one separately typed Return per stage, producing seven Returns and 42 total
  individual pieces;
- collective ritual architecture stored separately from the individual
  architecture;
- typed ritual elements, instructions, timing, and media intent only where the
  source supports them;
- typed Ayin concept links that pin the relevant Ayin concept version;
- structured safety rules, exclusions, validation results, and review records;
- machine enforcement of optionality, consent, right to stop, right to leave,
  non-coercion, and non-interpretation of participant experience;
- localized ritual text only to the extent required and source-supported for
  preserving safety policy;
- idempotent `MANASEK_WORKING` import, explicit CLI commands, read services,
  structural/safety validators, and thin read-only API routes;
- migrations and unit, importer, integration, failure-path, immutability, and
  safety tests.

## Out of scope

- promoting the supplied source to `MANASEK_CANON`;
- treating gates as Bon components or metaphysical elements;
- treating Return as a sixth gate;
- compressing the individual architecture into a collective ritual;
- treating ritual experience or intensity as proof of Ayin;
- generating new rituals or filling source ambiguity with model output;
- external knowledge ingestion, YouTube, claims, or reference resolution;
- retrieval, chunks, embeddings, vector indexes, or RAG;
- research packages, lecture generation, localization beyond ritual-safety
  preservation, publishing, or evaluation-phase infrastructure;
- generic `owner_type`/`owner_id` relationships.

## Required invariants and constraints

- An approved individual architecture must contain exactly seven stages, five
  gate slots per stage, and one Return per stage. The database design must
  enforce aggregate completeness using constrained slots plus deferred
  validation or another documented PostgreSQL mechanism; service-only counting
  is insufficient.
- Return has its own type and cannot reference or occupy a gate slot.
- Individual and collective structures use distinct architecture types and
  cannot be silently converted into one another.
- Gates remain symbolic attentional perspectives and are never components of
  Bon or five metaphysical elements.
- Approved ritual versions are immutable and historically retained.
- Failed or unresolved blocking safety validation prevents approval and any
  later publication eligibility.
- Consent, optionality, stop, leave, silence, and non-interpretation protections
  cannot be weakened by a ritual version or localization.
- Every important domain relationship uses typed foreign keys and explicit
  cascade behavior.

## Required tests

- Working/Canon zone separation and no silent Canon promotion;
- exact source hash, 42-page validation, raw provenance, and idempotent import;
- changed importer/extractor identity retains a new historical version;
- transaction rollback leaves no partial ritual graph;
- approved-version metadata and database immutability;
- exactly five gates and stable ordering;
- seven stages times five gate pieces equals 35;
- exactly seven separately typed Returns and 42 individual pieces total;
- Return cannot be inserted as a sixth gate;
- collective and individual architectures remain structurally separate;
- gates cannot be classified as Bon components/metaphysical elements;
- ritual/Ayin concept links pin real versioned foreign keys;
- stop, leave, consent, optionality, and silence protections are enforced;
- forbidden coercive patterns are rejected or produce the specified blocking
  safety result;
- localization cannot remove required safety protections;
- routes and CLI remain thin and cannot approve directly;
- migration upgrade, downgrade, re-upgrade, repeat upgrade, and drift checks;
- no Phase 4 or later tables or behavior.

## Acceptance criteria

- The repository owner explicitly approves this Phase 3 plan for execution.
- The supplied source is imported only as `MANASEK_WORKING`; no unauthorized
  `MANASEK_CANON` version exists.
- Exact bytes, checksum, page/passage location, raw/normalized text, and parser
  provenance are preserved and reviewable.
- The five-gate, seven-stage, seven-Return, 42-piece individual architecture is
  represented and database-validated without making Return a gate.
- Collective architecture remains distinct.
- Machine-enforced safety validation cannot be bypassed by import, approval,
  localization, or later publication eligibility.
- Ambiguity is preserved through typed review records.
- All authoritative relationships use foreign keys; no generic owner IDs are
  introduced.
- Formatting, linting, strict typing, migrations, focused tests, and the full
  suite pass from a clean disposable database.
- Phase 3 evidence and a pending Phase 4 plan are written before Phase 3 is
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

The approved implementation must also run the Manasek Working import twice on
a disposable database, compare identities and counts, execute the ritual
structural and safety validators, prove zero unauthorized Canon versions, and
document a downgrade/re-upgrade cycle.
