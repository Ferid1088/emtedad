# Phase 8.1 — Semantic Master Content Repair

## Outcome

Phase 9.1 correctly stopped before localization because the first READY
masters carried UUID-oriented machine instructions in `claim_intent` and
section scaffolding. Those identifiers were not usable semantic content.
The repair keeps identifiers as stable references while adding grounded,
language-neutral semantic payloads derived only from each frozen
ResearchPackage.

## Changes

- Added nullable historical-compatible claim fields: `semantic_proposition`,
  `plain_meaning`, `required_concepts`, `required_qualifiers`,
  `prohibited_overstatements`, `source_support_summary`, and
  `source_evidence`.
- Export now includes dialogue relations and selected package evidence text,
  language, content hash, and provenance.
- Architecture now carries actual source-backed Ayin propositions, exact
  source text, external evidence text, relation explanations, review status,
  and terminology definitions. No new retrieval or research was performed.
- Added `SemanticMasterStandaloneValidator` and
  `LocalizationReadinessValidator`. They reject UUID-only claims/sections,
  missing evidence text, missing relation explanations, and missing term
  definitions.
- Added regression tests for the UUID-only defect and a self-contained
  grounded claim.

## Historical and repaired masters

The immutable first versions remain preserved as historical READY records;
they were not rewritten because database immutability protects frozen
history. Their known limitation is documented as
`INSUFFICIENT_SEMANTIC_PAYLOAD_FOR_LOCALIZATION`. New version 3 records were
architected from the same frozen packages and validated independently:

| Pilot | ResearchPackage | Repaired master | Claims | Evidence | Relations | Terms |
|---|---|---|---:|---:|---:|---:|
| Pattern continuation | `77d52c9d-0d42-4f5c-b910-1a46447500c3` | `aeab164c-8609-4c22-8582-147912492847` | 28 | 28 | 8 | 5 |
| Change and identity | `5d6e9ec2-0ae3-42bd-a50f-ad41c2d01f35` | `f6ecf88f-ddf6-447f-b018-a9ce15db88eb` | 22 | 22 | 4 | 4 |
| Between two people | `07c1a186-773c-47eb-941a-304c43d78cef` | `9d1e9dd6-0070-437a-b5fe-b5b226539501` | 29 | 29 | 6 | 4 |

All three repaired masters are `READY`, pinned to their original frozen
package hash and Ayin Working authority. Pilot C retains optional Manasek
Working context; it is not evidence for an Ayin proposition.

## Standalone export QA

The standalone export contains the human question, semantic section
purposes and transitions, claim propositions and plain meanings, exact
source excerpts where available, package provenance, epistemic metadata,
dialogue explanations and review status, counterevidence text, and
terminology definitions. A validator can inspect this JSON without a
database, retrieval service, or internet access. No UUID-only required field
remains in the repaired masters.

Representative payloads now state the source-backed proposition itself (for
example, the Ayin definition and distinction text) and explicitly constrain
the localizer not to turn external evidence or a PROPOSED relation into
proof, identity, or approval.

## Verification

- Standalone and localization-readiness validators: pass for all three
  repaired exports.
- Existing Ayin fidelity, epistemic, citation, dialogue-status, and ritual
  boundary validators remain enabled and pass.
- No localized `display_text` or `voice_text` was generated.
- No retrieval, web search, ElevenLabs, audio, or new research was used.
- Ayin remains `AYIN_WORKING`; Manasek remains `MANASEK_WORKING` where
  present; no Canon records were created or changed.
