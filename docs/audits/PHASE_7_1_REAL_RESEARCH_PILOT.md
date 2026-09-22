# Phase 7.1 Real Research Pilot Validation

Date: 2026-09-23

This checkpoint exercised the Phase 7 services against the existing
development corpus: one `AYIN_WORKING` version, one `MANASEK_WORKING` version,
131 active retrieval chunks (53 Ayin, 43 Manasek, 35 external), one external
source version, and 14 Phase 6 dialogue
relations. No fixture rows were inserted and no Canon rows were created.

## Authority pre/post check

- `AYIN_WORKING`: 1; `AYIN_CANON`: 0.
- `MANASEK_WORKING`: 1; `MANASEK_CANON`: 0.
- Counts were unchanged after all pilots.

## Final pilot artifacts

| Pilot | Spine | Plan | Frozen package | Ayin Spine | External chunks | Relations | Ritual versions |
|---|---|---|---|---:|---:|---:|---:|
| A — pattern continuation | `ff91d2e8-d2f8-4211-81eb-9768ff3b4b74` | `b158aa92-bef1-40ea-aa57-c9e290bb847d` | `77d52c9d-0d42-4f5c-b910-1a46447500c3` | pattern, conditions, majal, change, causality (5 passages) | 5 | 8 | 0 |
| B — change and identity | `7afe59e1-bae1-46c8-b7cf-f27f9578adc9` | `078e4332-a5a1-4e96-9e78-e772629f0fcc` | `5d6e9ec2-0ae3-42bd-a50f-ad41c2d01f35` | change, bon, pattern, emtedad (4 passages) | 5 | 4 | 0 |
| C — between two people | `84125d74-ea7e-4062-913f-e9b8de4dd332` | `75cc35d3-67dc-4482-b437-11f692404da5` | `07c1a186-773c-47eb-941a-304c43d78cef` | between, other, bon, emtedad (4 passages) | 5 | 6 | 5 |

The concepts were selected from the current Ayin records and their exact
definitions/passages after inspecting the actual Ayin retrieval candidates.
The first automated candidate probe surfaced broad concepts such as
causality, bon, conditions, emtedad, factor, jan, pattern, and tohigah; the
final spines were narrowed using the structured Ayin definitions rather than
forcing an external match.

Each plan contained AYIN, EMPIRICAL, and COUNTEREVIDENCE questions. Pilot C
also contained an explicit MANASEK question because ritual relevance was
declared. All three packages froze successfully.

## Evidence and relation behavior

- Counterevidence was attempted for all pilots: 5 retrieved candidates per
  pilot, with 5 retained in each retrieval snapshot before package-level
  de-duplication.
- No counterargument, criticism, or alternative explanation was fabricated.
- Final relation counts were 8, 4, and 6 respectively. Every serialized
  relation had `review_status: PROPOSED`; proposed-relation leakage: **0**.
- No external claim was promoted to `SUPPORTED`.
- External evidence retained source version, source URL/title, creator,
  timestamps/pages where available, content hash, chunk ID, and evidence
  text. The final packages contained 43/49/61 external claims, 6/3/5 works,
  and 15/10/23 people respectively.
- One external source dominates the current pilot corpus. This is a corpus
  coverage limitation, not an algorithmic source-merging defect. Chunk IDs
  were unique within each package; overlapping context was not duplicated as
  separate selected chunks.

Pilot C stored five ritual versions as `RITUAL_CONTEXT`. They remain visibly
  `MANASEK_WORKING` and are not evidence for Ayin. The relational Ayin Spine
  uses `between` and `other`; no reviewable `horizontal_emtedad` proposal was
  promoted or silently treated as established Ayin.

## JSON export and writer isolation

JSON exports were produced at `/tmp/phase7_1_A_reviewed.json`,
`/tmp/phase7_1_B_reviewed.json`, and `/tmp/phase7_1_C_reviewed.json` during the
pilot. Frozen retrieval snapshots contain question kind, retrieval run,
selected chunk text, language, rank, scores, hashes, and complete provenance.
They also contain explicit dialogue relation type, scope, explanation,
selection role, and review status. Thus a consumer without database,
retrieval, or internet access can distinguish Ayin grounding, external
evidence, counterevidence, conceptual parallel, non-equivalence, proposed
relations, unresolved material, and optional Manasek context.

## Immutability test

An application-level update and a direct SQL update against frozen package
`77d52c9d-0d42-4f5c-b910-1a46447500c3` both failed with the database trigger
error `frozen ResearchPackage ... is immutable`. Both transactions rolled
back cleanly and the package remained `FROZEN`.

## Performance and cost

The first pilot included model loading and took approximately 13 seconds;
subsequent package builds took under one second with the embedding model
cached. Retrieval runs were reused by deterministic retrieval configuration;
package builds reported no whole-package cache hit because each run produced a
new retrieval snapshot. Phase 7 package construction made no LLM calls; Phase
6 relations were read from the existing corpus. No repeated model work beyond
the expected first embedding-model load was observed.

## Defects found and fixes

1. Retrieval snapshots attempted to persist UUID objects in JSONB. The pilot
   exposed this at package flush time. Snapshot identifiers are now serialized
   as JSON-safe strings, with a regression test.
2. `manasek_relevant=True` did not create a MANASEK question, so the optional
   lane could be silently skipped. Relevant plans now receive one explicit
   MANASEK question unless the operator supplied one.
3. Selected Manasek chunks were not associated with package ritual versions.
   The package builder now records their typed `RITUAL_CONTEXT` associations.
4. Retrieval snapshots did not expose selected text or relation detail to an
   offline consumer. Snapshots now include selected text/language and complete
   serialized dialogue relation metadata.

These were narrow pilot defects; no new tables or architectural subsystem was
introduced.

## QA conclusion

The Ayin Spines preserve the current Working definitions and exact passages;
the plans are narrow enough to show the intended research lanes; external
material remains separate; all dialogue edges remain proposed; counterevidence
was honestly attempted; Manasek is optional and non-evidentiary; and package
provenance is traceable. The final packages are suitable frozen inputs for a
future Phase 8 review, but no lecture workflow was started here.
