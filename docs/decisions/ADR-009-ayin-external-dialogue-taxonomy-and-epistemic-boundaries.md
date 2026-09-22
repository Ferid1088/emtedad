# ADR-009: Ayin–External Dialogue Taxonomy and Epistemic Boundaries

- Status: Accepted
- Date: 2026-09-20

## Context

External research can illuminate, challenge, contextualize, or parallel Ayin,
but it has different authority and cannot redefine an Ayin concept, principle,
distinction, or open question. A generic `SUPPORTS_AYIN` relation would erase
the difference between empirical evidence, conceptual analogy, historical
context, illustration, compatibility, criticism, and non-equivalence. It would
also invite scientific-proof framing for conceptual, ethical, or optional
metaphysical statements.

Dialogue judgments must remain reproducible after either side changes. Machine
classifications need exact Ayin and external evidence, retrieval and model
provenance, conservative defaults, and a review history that does not overwrite
the original proposal.

## Decision

### Typed, version-pinned targets

Dialogue data lives in `knowledge` but does not modify `core`, `ritual`, or
external claim verification. A constrained Ayin target registry has distinct
foreign keys for concept, principle, distinction, and open-question versions.
An external target registry has distinct foreign keys for claims, works,
retrieval chunks, external concepts, and people. Kind/target checks and
composite foreign keys require the stated kind, exact source version, and exact
passage or segment to agree. There are no generic `owner_type`/`owner_id`
columns.

Each target retains additional typed evidence rows. The Ayin object version and
the containing Working/Canon corpus version are both preserved. Relations do
not silently follow a later Ayin or external source revision; read services
compare the pinned version with later versions and mark affected relations
stale for review.

### Relation and scope taxonomies

The only dialogue relation types are:

- `EMPIRICALLY_RELEVANT_TO`
- `SUPPORTS_EMPIRICAL_SUBCLAIM`
- `CONCEPTUAL_PARALLEL`
- `HISTORICAL_PARALLEL`
- `ILLUSTRATES`
- `COMPATIBLE_WITH`
- `TENSION_WITH`
- `CHALLENGES`
- `COUNTEREXAMPLE_TO`
- `ALTERNATIVE_EXPLANATION`
- `NOT_EQUIVALENT_TO`
- `UNRESOLVED_RELATION`

`SUPPORTS_AYIN` does not exist. Scope is an independent required value:
`CONCEPTUAL`, `EMPIRICAL`, `DESCRIPTIVE`, `ETHICAL`, `METAPHYSICAL`,
`HISTORICAL`, or `ILLUSTRATIVE`. Deterministic validation rejects impossible
type/scope pairs. Multiple justified relation types may connect the same pair;
for example, a conceptual parallel can coexist with non-equivalence.

### Evidence role and Ayin testability

The classifier separately records whether an external item is empirical
evidence, empirical counterevidence, a philosophical argument, conceptual
analogy, historical context, example, anecdote, commentary, reference only,
alternative explanation, or unknown.

The Ayin statement is independently classified as `CONCEPTUAL`,
`DESCRIPTIVE_TESTABLE`, `DESCRIPTIVE_NONTESTABLE`, `ETHICAL`,
`OPTIONAL_METAPHYSICAL`, or `OPEN_QUESTION`. Only
`DESCRIPTIVE_TESTABLE` is eligible for `SUPPORTS_EMPIRICAL_SUBCLAIM`.
Empirical material may be relevant to an optional metaphysical interpretation,
but that relation is review-flagged and never framed as verification.

### Proposal, validation, and review

Targeted retrieval supplies actual external candidates for one exact Ayin
object. The `EvidenceRoleClassifier` uses the existing `LLMProvider` structured
output boundary. It can return zero relations. Every machine result is stored
as an immutable proposal, linked to a proposal run and candidate; its mutable
reviewed classification is a separate relation row. Review decisions are
append-only and preserve previous and new type, scope, explanation, reviewer,
notes, and time.

Machine relations default to `PROPOSED`; they are never auto-approved. Explicit
human review may start review, approve, reject, or supersede and may change the
classification. Approval means only that the dialogue classification was
reviewed. It does not alter Ayin or external claim verification.

The deterministic `DialogueEpistemicValidator` detects scientific-proof
framing, empirical support for non-testable statements, metaphysical overreach,
ethical proof framing, conceptual similarity collapsed into identity, open
questions presented as resolved, missing versions/evidence/run provenance,
impossible type/scope combinations, and approval with critical errors.

### Runs, caching, and counterevidence

Proposal runs pin the retrieval run/configuration, candidate set, provider,
model, prompt/classifier versions, input hashes, outcomes, and cache behavior.
Whole-run caching is deterministic. Pair-level classifier output is keyed by
the exact Ayin object version and input hash, external source version and
content hash, provider/model, and prompt/classifier versions. A prompt or model
change creates a new judgment rather than overwriting history.

Discovery is query-driven, never all-pairs. Counterevidence search uses explicit
contradiction, competing-explanation, null-result, boundary-case, and criticism
query variants over the existing external retrieval lane. It returns only
retrieved corpus chunks; an empty result is valid and no counterargument is
fabricated.

## Consequences

- Dialogue remains epistemically explicit and authority-preserving.
- Negative, unresolved, and non-equivalence relations are first-class and can
  be reviewed as seriously as positive matches.
- More tables and validation are required than for a generic polymorphic edge,
  but referential integrity and historical reproducibility are retained.
- External claims remain `UNVERIFIED` or `ATTRIBUTED_ONLY` unless a separate
  evidence-matching workflow explicitly changes them.
- Phase 7 may consume reviewed dialogue data later, but Phase 6 creates no Ayin
  Spine, ResearchPlan, ResearchPackage, or lecture artifact.

## Alternatives considered

- A generic `SUPPORTS_AYIN` edge: rejected as epistemically ambiguous.
- Unconstrained polymorphic owner/target IDs: rejected because PostgreSQL could
  not enforce target existence or version identity.
- Updating the machine proposal during review: rejected because it destroys
  audit history.
- Comparing every Ayin object with every external chunk: rejected as costly,
  noisy, and intellectually weak.
- Automatically upgrading similar external claims to `SUPPORTED`: rejected
  because resemblance is not evidence matching.

## Supersedes / Superseded by

This ADR extends ADR-002, ADR-007, and ADR-008. It supersedes no accepted ADR.
