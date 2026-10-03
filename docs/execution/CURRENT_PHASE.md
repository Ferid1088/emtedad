# Pending Phase: Multichannel program — Phase 21 complete, awaiting owner review

(For the multichannel program defined in
`docs/EMTEDAD_CODING_AGENT_MASTER_IMPLEMENTATION_PROMPT.md`. Phases 0–21 are
complete; evidence in `docs/audits/MULTICHANNEL_PHASE_0_BASELINE.md`,
`docs/audits/MULTICHANNEL_PHASE_1_EDITORIAL_CHANNELS.md`,
`docs/audits/MULTICHANNEL_PHASES_4_7.md`,
`docs/audits/MULTICHANNEL_PHASES_8_20.md`,
`docs/audits/MULTICHANNEL_GENERIC_MASTER_PATH.md`,
`docs/audits/MULTICHANNEL_PHASE_21_LEGACY_RETIREMENT.md`.)

Phase 21 completed:

- The active 100-lesson production path is retired: `LessonCanonRepository`,
  `lesson_catalog`, `lesson_research`, `create_lesson_project`, lesson
  routes/navigation/CLI, and the file-backed canon are gone.
- Generic Persian capability lives in `app/content_engine/writing/`
  (quality, text helpers, published memory, diversity, native reviewer/
  optimizer, voice contracts) and is wired into `ScriptService` for `fa`
  drafts — no lesson dependency.
- `knowledge/structure` is the single Vortragsstruktur owner:
  `app/knowledge/processing.py` (synchronous pipeline) +
  `app/knowledge/structure/scheduler.py` (queue/retry/backoff ported from
  the retired `speech_structure` scheduler); `app/speech_structure` is
  now models-only for historical rows.
- Historical lesson projects remain readable through `/workspace/{id}`
  and the text library; `lesson_id`/`lesson_canon_hash` columns are
  `LEGACY_PROVENANCE_ONLY`.
- Verified: 220 unit + 52 integration tests pass; 3 documented baseline
  failures unchanged (ix_speech index-name drift, ZWNJ ezafe
  normalization, live-Devin topic suggestions).
- Stop state: changes are NOT committed; awaiting owner approval.

Next steps after owner approval:

- Commit Phase 21.
- The implementation prompt ends at Phase 21; the next phase is an owner
  decision (hardening, deployment, new channels, or follow-on features).

Legacy phase history (Phases 0–12 of the original program) follows.

## Execution status

Phase 12 final editorial output is complete as of 2026-09-23. The owner MVP web app provides
German-first source ingestion, knowledge browsing, grounded topic suggestions,
and manual topic analysis using the existing Phase 4 and Phase 10 services.
See `docs/audits/PHASE_11_OWNER_MVP_WEB_APP.md`.

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

## Completed Phase 12 final checkpoint

- approved Persian remains the exact FA editorial source;
- direct, independently versioned FA/DE/EN/AR editorial tracks;
- explicit voice-ready text preparation with no audio or ElevenLabs calls;
- standalone text-to-voice preparation utility;
- duration-aware Persian generation and immutable provenance.

## Completed Phase 12 lesson-canon generation boundary revision

ADR-013 is implemented as of 2026-09-24:

- ordinary 100-lesson production loads a content-hashed canonical Lesson
  Content Package directly from `resources/editorial/lesson_canon`;
- the canonical lesson explanation is the Ayin core and is not regenerated as
  an AI-authored seed;
- default lesson research retrieves external evidence and counterevidence, not
  the complete Ayin book;
- Ayin-origin Semantic Master claims and evidence are filtered out of the
  Persian writer context;
- Channel Ledger, Published Script Archive, and lesson relations remain
  post-draft review inputs;
- the complete Ayin corpus remains available for provenance, inspection,
  verification, revision, citations, and explicit specialist research;
- lesson ID, package version, full package snapshot, canon hash, input roles,
  and provenance-completeness state are stored with every generated draft.

Acceptance evidence:

- `docs/audits/PHASE_12_LESSON_CANON_GENERATION_BOUNDARY.md`

Open review item: the supplied lesson JSON contains no per-lesson Ayin source
version, passage/page, concept, or distinction mapping. The package records
`MISSING_LESSON_AYIN_PROVENANCE`; no source evidence was invented.

## Completed Phase 12 owner UI adaptation

The German-first owner workspace now exposes the lesson-canon production model:

- `Lektionen` is the primary 100-lesson catalog and replaces the strategy tree
  in owner navigation;
- lesson list, search, filters, detail, relations, concepts, production status,
  and real database progress counts are available without exposing raw IDs;
- lesson projects enter the existing `EditorialProject` and Studio workflow
  with a pinned, read-only Lesson Content Package;
- Studio separates the canonical Ayin core from external research and offers no
  ordinary full-book Ayin search;
- Studio and the text library retain lesson or dynamic-topic provenance;
- published-only memory is visible through `Archiv` and the knowledge-base
  review area; drafts never appear there;
- the old strategy tree templates and actions are retired; legacy URLs redirect
  to `/lessons`, while historical project provenance remains intact.

Acceptance evidence includes owner-route integration coverage plus responsive
desktop, tablet, and mobile browser QA of the canonical lesson journey.

- `docs/audits/PHASE_12_OWNER_UI_ADAPTATION.md`

## Next-phase goal

Implement language realization and pronunciation preparation from standalone
SemanticLectureMasterExport objects, with separate semantic approval and TTS
readiness. Do not generate audio or publish in this phase.

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
