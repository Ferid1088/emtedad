# Pending Phase: Phase 6 — Ayin–External Dialogue

## Execution status

Phase 5 is complete as of 2026-09-19. Phase 6 is prepared for repository-owner
review but is not active. Do not implement Phase 6 until the owner explicitly
approves this plan.

Completion evidence for Phase 5: `docs/audits/PHASE_5_COMPLETION.md`.

## Goal

Model an explicitly reviewed dialogue between Ayin and external knowledge while
preserving authority, epistemic status, counterevidence, and uncertainty.

## Proposed scope

- typed Ayin-to-external proposed relations and review workflow;
- evidence-role classification, conflicts, alternatives, and counterevidence;
- explicit uncertainty and provenance for every proposed interpretation;
- validators preventing external sources from redefining Ayin;
- versioned classifications, API/CLI boundaries, migrations, and evaluation.

## Out of scope

- ResearchPlan, ResearchPackage, and Ayin Spine (Phase 7);
- lecture generation, localization, publishing, music, or TTS;
- automatic Canon promotion, automatic claim verification, or generated Canon.

## Required invariants

- Ayin Working/Canon, Manasek Working/Canon, external primary/derived, and
  generated content remain distinct.
- External material may enter dialogue with Ayin but cannot redefine it.
- Manasek is experiential and cannot be used as evidence proving Ayin.
- Every relation preserves typed source provenance, uncertainty, and review
  state; no generic owner IDs are permitted.

## Acceptance gate

Phase 6 requires explicit owner approval, an accepted ADR, reversible and
drift-free migrations, serious classification/review tests, domain validators,
Ruff, strict mypy, and the full suite. Phase 7 must not begin as part of Phase
6.
