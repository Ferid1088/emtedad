# Phase 6 Completion Audit — Ayin–External Dialogue

Date: 2026-09-22

## A. Files changed

Phase 6 adds the `app.dialogue` domain (taxonomy, models, schemas, classifier,
validator, and service), the dialogue API and CLI commands, migration support,
unit/integration coverage, ADR-009, and this audit. It also updates the app
router, Alembic model registration, Phase 5 retrieval’s PostgreSQL DISTINCT
ordering bug, and project phase documentation. Existing user edits to the
working seed and specification terminology are retained and are not part of
the Phase 6 design.

## B. Migration

Alembic revision `26a7bca28432` adds the typed dialogue schema and the composite
version constraints needed for referential integrity. The migration is
reversible and leaves `content` empty. Pair-level classifier cache keys are
intentionally non-unique so the same exact judgment can be reused by multiple
retrieval proposal runs.

## C. Dialogue schema

The `knowledge` schema contains typed Ayin and external target registries,
additional evidence rows, proposal runs and candidates, immutable machine
proposals, current relations, append-only review decisions, and typed review
flags. Composite foreign keys pin source passage/segment and version identity.
The relation row stores both the exact Ayin object version and its containing
corpus version, all source evidence IDs, retrieval run, classifier/provider
configuration, and review state.

## D. Relation taxonomy

Implemented: `EMPIRICALLY_RELEVANT_TO`, `SUPPORTS_EMPIRICAL_SUBCLAIM`,
`CONCEPTUAL_PARALLEL`, `HISTORICAL_PARALLEL`, `ILLUSTRATES`, `COMPATIBLE_WITH`,
`TENSION_WITH`, `CHALLENGES`, `COUNTEREXAMPLE_TO`,
`ALTERNATIVE_EXPLANATION`, `NOT_EQUIVALENT_TO`, and `UNRESOLVED_RELATION`.
There is no generic `SUPPORTS_AYIN` relation.

Scopes are independent and explicit: `CONCEPTUAL`, `EMPIRICAL`, `DESCRIPTIVE`,
`ETHICAL`, `METAPHYSICAL`, `HISTORICAL`, and `ILLUSTRATIVE`.

## E. Evidence-role taxonomy

The classifier records `EMPIRICAL_EVIDENCE`, `EMPIRICAL_COUNTEREVIDENCE`,
`PHILOSOPHICAL_ARGUMENT`, `CONCEPTUAL_ANALOGY`, `HISTORICAL_CONTEXT`,
`EXAMPLE`, `ANECDOTE`, `COMMENTARY`, `REFERENCE_ONLY`,
`ALTERNATIVE_EXPLANATION`, or `UNKNOWN`. Evidence role is deliberately
separate from relation type.

## F. Testability model

Supported Ayin statement classes are `CONCEPTUAL`, `DESCRIPTIVE_TESTABLE`,
`DESCRIPTIVE_NONTESTABLE`, `ETHICAL`, `OPTIONAL_METAPHYSICAL`, and
`OPEN_QUESTION`. Only `DESCRIPTIVE_TESTABLE` can receive direct empirical
support. Empirical relevance to optional metaphysics is review-flagged and is
never verification.

## G. Proposal workflow

For a targeted Ayin concept, principle, distinction, or open question, the
service resolves the latest exact Ayin version, builds retrieval text from the
stored definition/context and distinctions, retrieves only external candidates,
classifies testability and evidence role, proposes zero or more typed relations,
pins all citations, validates epistemic boundaries, and persists every machine
result as `PROPOSED`. Human review is an explicit separate operation.

## H. Proposal-run and cache design

Runs record retrieval configuration and run, candidate/input hashes,
provider/model, prompt and classifier versions, outcomes, and cache behavior.
Whole-run cache keys are deterministic. Pair-level classifier keys include the
exact Ayin object version and input hash, external source version and content
hash, provider/model, and prompt/classifier versions. Changing model or prompt
creates a new proposal run.

## I. Pilot Ayin targets

The live pilot used actual Phase 5 retrieval results for `pattern`, `conditions`,
`majal`, `awareness`, principle `recognition_not_change`, and open question
`definition_of_unit`. Each target retrieved three external candidates; the
last three conservative targets produced zero relations where the corpus did
not justify a dialogue claim.

## J. Proposed relation count

14 proposed relations from 18 classified external candidates across six
successful proposal runs. All 14 remain `PROPOSED`; none was automatically
approved, rejected, or used to modify Ayin.

## K. Counts by relation type

| Relation type | Count |
|---|---:|
| `CONCEPTUAL_PARALLEL` | 5 |
| `ILLUSTRATES` | 1 |
| `COMPATIBLE_WITH` | 1 |
| `NOT_EQUIVALENT_TO` | 7 |

No empirical-support, tension, challenge, alternative, counterexample, or
unresolved relation was fabricated when the pilot corpus did not justify one.

## L. Counts by scope

| Scope | Count |
|---|---:|
| `CONCEPTUAL` | 13 |
| `ILLUSTRATIVE` | 1 |

## M. Negative and challenge relations

`NOT_EQUIVALENT_TO` is a first-class pilot result (7 relations), including the
Pattern/identity-theory fixture and Majal/option-count and causal-mechanism
distinctions. No corpus-backed `TENSION_WITH`, `CHALLENGES`,
`COUNTEREXAMPLE_TO`, or `ALTERNATIVE_EXPLANATION` relation was asserted.

## N. Unresolved relations

Zero `UNRESOLVED_RELATION` proposals were generated because the selected pilot
items either had a bounded parallel/illustration or no defensible relation.
The taxonomy and validator retain unresolved relations for future targeted
research.

## O. Review queue

All 14 relations are in the review queue. There are 16 unresolved typed review
flags, including relation ambiguity, discourse mismatch, potential false
equivalence, unsupported scientific framing, and alternative-explanation
presence. The Majal anecdotal example is intentionally still proposed for
human scrutiny rather than treated as evidence.

## P. Validator results

The structural Ayin, Manasek, external-knowledge, retrieval, and dialogue
validators all returned valid with zero validation errors. The dialogue
validator’s fixtures reject scientific-proof framing, metaphysical empirical
support, ethical proof framing, conceptual identity collapse, resolved-open-
question framing, missing provenance, impossible scopes, and approval with
critical errors.

## Q. Manual QA

Inspected exact Ayin version/passage IDs, external source version/segment/chunk
IDs, evidence role, scope, explanation, confidence, provider/model, prompt
version, and retrieval run for Pattern, Conditions, Majal, and the
non-equivalence relations. The Pattern conceptual-parallel plus
non-equivalence pairing is preserved. The illustrative Conditions relation is
bounded to illustration. No relation claims that external material defines or
proves Ayin.

## R. Dependency and version handling

Relations pin exact Ayin object versions and external source versions. Read
services compare those pins with later versions and expose stale flags for
future review; the original relation is not rewritten. Composite foreign keys
prevent a passage or segment from being paired with the wrong version.

## S. Tests

The final full suite passed: **116 tests**. Coverage includes taxonomy and
scope combinations, testability traps, provenance, negative relations,
proposal/review separation, human override history, cache-key behavior,
counterevidence deduplication/empty results, API/CLI boundaries, retrieval
regression, and migration schema assertions.

## T. Ruff and mypy

`ruff format --check .`, `ruff check .`, and strict mypy passed. Mypy reported
no issues in 90 application source files.

## U. Migration verification

Clean upgrade, repeated upgrade, downgrade to base, re-upgrade, and Alembic
drift checks passed against disposable PostgreSQL databases. The live
development database is at `26a7bca28432`; `alembic check` reports no new
operations.

## V. Ayin definition/principle confirmation

No Ayin definition, concept version, principle, distinction, or open-question
meaning was modified by Phase 6. Dialogue approval changes only dialogue
relation state and review history.

## W. Ayin authority confirmation

The live database contains one `AYIN_WORKING` version and zero `AYIN_CANON`
versions. Ayin remains Working.

## X. Manasek authority confirmation

The live database contains one `MANASEK_WORKING` version and zero
`MANASEK_CANON` versions. Manasek remains Working and is not used as proof of
Ayin.

## Y. Phase 7 confirmation

No Phase 7 tables, ResearchPackage/Ayin Spine workflow, lecture endpoint,
translation workflow, or publishing workflow was added. The next phase is
documented as pending owner review only.

## Commands and live pilot evidence

The live pilot used the existing external corpus and Phase 5 retrieval runs.
Repeating the Pattern command returned the original run with `cache_hit: true`.
Counterevidence search used three deterministic query variants and returned
five actual external chunks; no synthetic counterargument was created.
