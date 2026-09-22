# Pending Phase: Phase 7 — Research Engine

## Execution status

Phase 6 is complete as of 2026-09-22 and committed after verification. Phase 7
is prepared for repository-owner review but is not active. Do not implement
Phase 7 until the owner explicitly approves its plan.

Completion evidence:

- Phase 5: `docs/audits/PHASE_5_COMPLETION.md`
- Phase 6: `docs/audits/PHASE_6_COMPLETION.md`

## Next-phase goal

Implement the versioned Research Engine that consumes reviewed dialogue data
without changing Ayin or Manasek authority.

## Phase 7 proposed scope

- Ayin Spine snapshots;
- targeted ResearchPlan and lane-aware retrieval orchestration;
- immutable, provenance-complete ResearchPackage snapshots;
- explicit review and version dependency behavior.

## Phase 7 out of scope

- lecture generation, localization, publishing, music, or TTS;
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
Phase 7 has not begun.
