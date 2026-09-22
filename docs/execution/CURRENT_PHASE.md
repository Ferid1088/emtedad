# Pending Phase: Phase 9 — Four Languages

## Execution status

Phase 7 and Phase 8 are complete as of 2026-09-23 and committed after
verification. Phase 9 is the next phase and is not implemented here.

Completion evidence:

- Phase 5: `docs/audits/PHASE_5_COMPLETION.md`
- Phase 6: `docs/audits/PHASE_6_COMPLETION.md`
- Phase 7: `docs/audits/PHASE_7_COMPLETION.md`
- Phase 8: `docs/audits/PHASE_8_COMPLETION.md`

## Completed Phase 7 scope

- Ayin Spine snapshots;
- targeted ResearchPlan and lane-aware retrieval orchestration;
- immutable, provenance-complete ResearchPackage snapshots;
- explicit review and version dependency behavior.

Completion evidence: `docs/audits/PHASE_7_COMPLETION.md`.

## Completed Phase 8 scope

- frozen ResearchPackage-pinned lecture projects and Semantic Master versions;
- typed section, claim, dependency, evidence, citation, and ritual-link graph;
- deterministic Ayin fidelity, epistemic, citation, dialogue, ritual, and
  package-traceability validators;
- immutable READY masters and standalone Phase 9 handoff exports.

Completion evidence: `docs/audits/PHASE_8_COMPLETION.md`.

## Next-phase goal

Implement language realization from standalone SemanticLectureMasterExport
objects only after owner review. Do not add localization in this phase.

## Phase 8 and Phase 9 boundary

- Persian, German, English, or Arabic final scripts, publishing, music, or
  TTS;
- automatic Canon promotion or generated Canon.

## Required invariants

- Ayin Working/Canon, Manasek Working/Canon, external primary/derived, and
  generated content remain distinct.
- External material may enter dialogue with Ayin but cannot redefine it.
- Manasek is experiential and cannot be used as evidence proving Ayin.
- Every relation preserves typed source provenance, uncertainty, and review
  state; no generic owner IDs are permitted.

## Phase 6 acceptance result

Phase 6 delivered an accepted ADR, reversible and drift-free migration,
classification/review tests, domain validators, Ruff, strict mypy, the full
116-test suite, a live retrieval pilot, manual QA, and the completion audit.
Phase 7 delivered the versioned Ayin Spine, targeted ResearchPlan, lane-aware
retrieval orchestration, immutable ResearchPackage snapshot, API/CLI surfaces,
ADR, migration, validators, and tests. No Ayin or Manasek content was changed.
