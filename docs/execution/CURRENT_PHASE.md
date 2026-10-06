# Pending Phase: Master cost-quality content pipeline — Persian owner-approved master → native DE/EN/AR, awaiting owner review

Status (2026-10-06, certification round 2 — uncommitted on top of `9428e25`):

- Section-aware patch repair replaced whole-script regeneration:
  deterministic section splitting (paragraph groups, stable `section_id`s,
  SHA-256 section hashes), `PatchSetOutput` contract, stale-hash and
  malformed-hash rejection, findings routed to owning sections, one
  bounded full rewrite only when the model declares the architecture
  broken (`app/content_engine/patching.py`,
  `app/localization/native_pipeline.py`).
- Monotonic best-candidate retention: every repair and every premium
  edit is a *candidate*; a hard ordering (blockers → warnings →
  fidelity → duration → encoding → finding count) promotes strictly
  better candidates, restores the incumbent on regression, archives the
  loser, reopens exactly the addressed findings, and persists a
  `candidate_decision` provenance record. Same rule now protects the
  Persian revision path (`review._retain_best_candidate`) — a worse
  revision can no longer silently overwrite a better approved-adjacent
  draft. Verified live: topic-1 AR's premium edit regressed and the
  pre-premium best was restored and certified.
- Deterministic duration: per-section word budgets from
  `NarrativePlanSection`s reach the writer, the length-repair planner,
  and every patch payload — deletions can no longer silently collapse
  the spoken-duration band; bounded duration-only repair operates
  through patch ops and re-plans against patched text.
- Source-aware repair payloads: `_supported_material()` injects thesis +
  causal constraints + counterarguments + story facts + unresolved
  ambiguities (plus claim ledger when present) into every section patch,
  global patch, and length-repair call — repair models now see what the
  source supports instead of patching fidelity findings blind.
- Sol certified on the Responses protocol over two live loops (identical
  inputs, both protocols: schema 100 %, zero failures, semantically
  equivalent verdicts, ~41 % prompt-token reduction on critic payloads,
  ~95 % on narrow claim checks) — `model_role_reasoning_protocol`
  switched to `responses` with one-shot chat fallback recorded in
  telemetry (`requested_protocol`/`actual_protocol`/`fallback_reason`).
- Patch economics verified live: section patch calls ~4–6.6k prompt
  tokens vs ~12–15.9k for whole-script review/correction (≈60 % input,
  ≈89 % output reduction).
- Live multilingual certification (evidence in
  `docs/audits/APIMASTER_CERTIFICATION.md`):
  - Topic 1: DE/EN/AR all `READY_FOR_VOICE` (25.2 / 25.2 / 25.6 min);
    AR premium regression restored the pre-Astra best.
  - Topic 2 (package `7550261f`, source draft `1ceed5e5`):
    EN `READY_FOR_VOICE` (25.2 min, 3528 words); DE `READY_FOR_VOICE`
    (25.6 min, 3325 words — premium edit regressed, pre-premium best
    restored and certified on a fresh run after two honest budget
    exhaustions); AR honestly `BLOCKED` across two runs — run 1
    converged pre-premium then failed the final fidelity gate after a
    rejected premium regression, run 2 exhausted the loop budget with 2
    residual fidelity blockers. This topic's Arabic surface needs owner
    review or a revised Persian master, not weaker gates.
- Cost truth hardened: Studio aggregates provider-reported cost only —
  NULL costs render as "nicht vom Provider gemeldet", never `$0.0000`;
  calls-with-cost vs total-calls shown (topic-2: 108/108 calls without
  provider cost; market estimate tracked separately).
- Regression: 416 unit + 118 integration tests pass; ruff, format, and
  strict mypy clean. Remaining warnings are pooled-connection cleanup
  and httpx deprecations, not failures.
- Stop state: NOT committed; owner review checkpoint.

Status (2026-10-05, committed as `9428e25`):

- APIMaster is the canonical external LLM gateway: role-based
  `resolve_llm_provider` (`AgentRole` → `ModelRole` → configured
  marketplace model ID: `gpt-6.1-sol`, `gemini-3.8-flash`,
  `gpt-6-astra`; `qwen3.8-flash` holds `HIGH_VOLUME_REASONING` which no
  live role maps to — it failed live A/B certification, see
  `docs/audits/APIMASTER_CERTIFICATION.md`) with owner DB overrides;
  the factory fails closed — disabled routing, unmapped roles, or
  missing role declarations raise `RoutingConfigurationError` unless
  `allow_devin_runtime_fallback` is explicitly set.
- APIMaster provider (`app/knowledge/llm/apimaster.py`): strict
  JSON-schema output (`json_object` mode for `gemini-3.8-flash`, which
  ignores `json_schema` — verified live), Pydantic validation, one
  bounded repair, typed errors, bounded retries, provider-reported
  telemetry only; `ops.llm_call_events` records real tokens/costs.
- No batch API: live `POST /v1/batches` → 404. All premium work runs
  synchronously; `ProviderBatchJob`, the poller, and batch pipeline
  stages were removed.
- Persian owner-approval is now a hard gate on every localization entry
  point; stale Persian sources invalidate packages and runs.
- Shared `LocalizationSemanticPackage` (reasoning model) is the single
  semantic contract for all target languages; deterministic validation
  against the master forbids invented claims and epistemic drift.
- Native pipeline per language: coverage → reconstruction → narrative edit
  → native/audience/fidelity critics + deterministic duration finding
  inside the review loop → bounded targeted repair (plus exactly one
  dedicated duration-only pass when length is the sole remaining
  blocker) → premium final editor → final fidelity + duration +
  scoped protected-terminology gates → `READY_FOR_VOICE`/`BLOCKED`;
  localized texts are `ScriptDraft`s with `lineage="localized"`.
- Studio shows per-language pipeline truth and actual provider costs;
  web research retrieves through Tavily (default), custom, or keyless
  Wikipedia — APIMaster is refused as a retrieval backend because it
  cannot return verifiable URLs — OpenRouter is fully retired from
  runtime, kept only as historical provenance.
- Stop state: committed `9428e25`; owner review checkpoint.

Historical (OpenRouter era, 2026-10-04):

- Multi-model routing, provider telemetry, and the localization gate
  architecture were first delivered over OpenRouter, including a batch
  execution path. Evidence: `docs/audits/COST_QUALITY_CONTENT_PIPELINE.md`.
- Evidence: 386 unit + 122 integration tests, mypy/ruff clean, migration
  upgrade/downgrade verified, live canary `docs/audits/COST_QUALITY_CONTENT_PIPELINE.md`.
- Stop state: NOT committed; owner review checkpoint.

# Earlier state: Phase 6.2 — approval semantics + cycles + quote provenance + real translation, awaiting owner review

Status (2026-10-06, Phase 7 pre-commit integrity audit — uncommitted):

- Owner authority: `waive_finding`/`approve_draft`/`start_review_cycle`
  now require explicit actor identity (waivers also justification);
  `recommend_waiver` is a separate non-resolving agent path.
- Psychology v8 is REVISED at an owner checkpoint — the eight findings
  are OPEN with recorded agent recommendations; earlier agent-executed
  waivers were reverted rather than fabricated as owner consent.
- Revision budget counts persisted revision drafts per cycle
  (`ScriptDraft.revision_cycle`), never review runs. Psych: c1=1, c2=3
  (exhausted). History: c1=2, c2=2 — one revision remains.
- Localization: `adjust_duration` is anchored to the exported approved
  Semantic Master and requires exact claim-set equality; the semantic
  validator now blocks U+FFFD/Cf corruption (ZWNJ exempt). Live fixes:
  AR corruption + superlative + invented quantifier, EN ungrounded
  detail, DE de-attributed statistic.
- Full regression: ruff/format/mypy strict clean; 342 unit + 118
  integration passed; migration chain clean end-to-end.
- Audit record: `docs/audits/FULL_PROCESS_OPTIMIZATION.md` →
  FINAL_PRECOMMIT_AUDIT. Do not commit without explicit owner approval.

Status (2026-10-05, uncommitted on top of the Phase 6.1 tree):

- Final approval gate: `approve_draft` now hard-requires the configured
  25–30 min band deterministically (language WPM, shared word counter) —
  critic silence can no longer approve an under/over-length draft.
- Review cycles: `ReviewCycle` + `ReviewRun.cycle_number` persist the
  owner-authorized cycle; `start_review_cycle` grants a fresh bounded
  budget only after exhaustion — history never renumbered.
- Quote provenance: direct quotes verify against raw source excerpts,
  not generated Evidence claims; marked translations exempt, unmarked
  renderings still flag.
- Revision encoding gate: corrupted revision output now fails honestly
  (verified live on two real corrupted outputs).
- Live certification: psych v8 APPROVED (27.2 min, cycle 2, 3/3 rounds,
  8 justified waivers). History honestly BLOCKED at owner checkpoint —
  v11 has 1 blocker + 23.8 min; cycle-3 authorization not granted.
- Real localization from the approved master: DE 27.0 min (3 loops),
  EN 25.3 min (1 loop), AR 25.0 min (2 loops), FA verified as master
  language — independent statuses verified in DB and UI.
- Tests: 341 unit + integration suites green; ruff/mypy strict clean.
- Stop state: NOT committed; owner review checkpoint.

Status (2026-10-04, uncommitted on top of the Phase 5 tree):

- Root cause of the short-first-draft defect: the budget chain existed
  end-to-end (brief → narrative `target_seconds` → master
  `duration_seconds` → per-section writer `target_words`), but narrative
  totals were trusted uncalibrated (live: 720–1650 s for 27.5-min
  briefs) and nothing validated the draft before it consumed review
  rounds. A second defect surfaced in Loop 2: two word counters
  (ZWNJ-splitting regex vs whitespace) let a 21.8-min draft pass as
  in-band — unified on the whitespace spoken-word count.
- Narrative budget calibration: `_calibrate_target_seconds` rescales
  model-proposed per-beat seconds to the brief target when the sum
  drifts >10 %; raw and calibrated totals are hashed/persisted.
- Generation contract: `writing/generation.py::validate_generation`
  checks encoding, duration band (0.85–1.15 × target·wpm, owner-tunable
  via `first_draft_{min,max}_duration_ratio`), paragraph floor vs planned
  beats, and Persian quality blockers (incl. new `REPEATED_SENTENCES`
  filler check). Bounded correction
  (`generation_max_correction_attempts`, default 2) uses
  `script_generation_correction` — never creates a ReviewRun, never
  consumes `max_revision_rounds`.
- Truthful failure: persistent generation failure persists
  `generation_validation.status=FAILED`; `ProductionService` gates
  `run_review`/`revise`/`approve` and shows SCRIPT as REVIEW_REQUIRED;
  the workspace explains attempts, failed checks, and that revision
  rounds were not consumed.
- Live results: psych-evol v5 2992 w ≈ 27.2 min PASSED attempt 1 (prior
  first drafts ~70 % of target); history v6 bounded-correction exhausted
  on un-repairable U+FFFD → honest FAILED; history v7 one correction →
  2581 w ≈ 23.5 min PASSED.
- Provider capacity live-verified: background capped at 2 remote
  sessions while owner work acquired slots; `provider_capacity_wait`
  instrumentation logs ≥1 s slot waits; per-process pool + foreign
  account sessions remain documented limits.
- Tests: 337 unit, targeted integration green; ruff/mypy strict clean.
- Stop state: NOT committed; owner review checkpoint.

# Earlier state: Phase 5 — book-reference correction + real quality loops, awaiting owner review

Status (2026-10-04, uncommitted on top of the Phase 4 tree):

- `BOOK_REFERENCE_PERSIAN` semantics corrected: the rule judges the
  book's SOURCE language from metadata (`original_language`), never the
  rendered title — a Persian-translated title of an English book is
  presentation and is allowed; a Persian book under an English title is
  still rejected; missing language is omitted, never assumed.
- Quote policy corrected: no more blanket ban. `verified_quote` is
  populated by the selector only from verbatim evidence wording and
  re-verified deterministically by the gate; the writer may use
  PARAPHRASE / DIRECT_QUOTE (exact reproduction; translations marked as
  translation, never in quotes) / CRITICAL_ATTRIBUTION.
- Deterministic `BOOK_POLICY` layer (`book_reference_findings`): quoted
  spans near attribution anchors or «کتاب» mentions must be verified
  wording — reproduces the live «آدم‌های خالص» catch; quoted titles
  («کتاب «عنوان»») are citations, exempt.
- Encoding-corruption root cause fixed at the provider boundary: remote
  session output carries U+FFFD; the live session now gets one bounded
  in-session repair turn (stale-output suppression) before the
  fresh-session fallback; `ENCODING_CORRUPTION` blocker remains the
  certification backstop.
- Reproducibility: allow-list still frozen in
  `draft.provenance_json["book_references"]` before the writer call;
  `reference_usage()` + `book_refs_table` show available vs used
  references in SCRIPT and REVIEW stages without re-running selection.
- Real loops: same-draft re-review (PERSIAN false positive gone, real
  findings retained), regenerated psych-evol v4 (verified-quote
  translations, natural varied attribution), history-channel v4 (Haidt,
  one purposeful citation, zero book findings).
- Tests: 315 unit (17 book-reference), targeted integration green;
  ruff/mypy strict clean.
- Stop state: NOT committed; owner review checkpoint.

# Earlier state: Phase 4 — provider capacity + real semantic certification, awaiting owner review

Status (2026-10-04, uncommitted on top of the Phase 21 / Parts A–B tree):

- Provider starvation fixed at root: leaked remote Devin sessions orphaned
  by killed processes held the 5-slot quota. `app/knowledge/llm/capacity.py`
  enforces a total cap plus a background cap by work class
  (`INTERACTIVE_OWNER` > `OWNER_REQUESTED` > `BACKGROUND_NEW` >
  `BACKGROUND_RETRY`); the provider sweeps stale tagged `blocked`/`expired`
  sessions and backs off on quota. New finding: foreign untagged sessions
  on the same account also consume the cap — they cannot be swept;
  `provider_max_concurrency` should reflect effective quota.
- Scheduler: persisted owner pause (`background_processing_paused`) gates
  background classes only; quota/rate-limit failures never burn
  `attempt_count`; owner "retry all failed" action bypasses the cap.
- Real semantic evidence where provider capacity permitted: 81 real topic
  candidates (all five channels ≥ 10), two real scripts in different
  channels, a live V1→V3 review/revision chain (36→30→32 findings, blocker
  resolved, no stale-finding leak), master immutability test, and a real
  book-PDF run that correctly stopped at STRUCTURE_REVIEW_REQUIRED (merge
  prompt defect found and fixed, `source_structure_merge_v2`).
- Real defects found and fixed: transcript NameError, LogRecord `extra`
  collisions masking failures, duplicate re-mining via
  `_published_signatures` scope, vague script duration instruction
  (explicit per-section word targets now), revision prompt without word
  budget, provider U+FFFD corruption caught deterministically
  (`ENCODING_CORRUPTION`), merge dropping parent nodes.
- Localization: `adjust_duration` actively corrects spoken length as a new
  immutable version (claim-set preserved, quality gate re-run, owner button
  on the translations page); shared `speech_wpm()` helper.
- Book/author references (final-prompt §18–26): `build_script` runs a
  `book_reference_selection` step over the frozen EvidenceMatrix claims;
  `app/content_engine/writing/books.py` applies the deterministic gate
  (non-Persian only, dedupe, cap 4), the surviving allow-list is frozen in
  `draft.provenance_json["book_references"]`, injected into the writer
  payload, shown in the draft UI, and checked by the channel-specific
  critic (`BOOK_REFERENCE_UNVERIFIED|PERSIAN|INVENTED_QUOTE|OVERCLAIM`).
  Selection failure degrades to no references — scripts never *need* one.
  Prompts bumped: `script_writer_v3`, `critic_v2`.
- Honest limits: OpenRouter web research `BLOCKED: NO_API_KEY`; token/cost
  `BLOCKED: PROVIDER_CONTRACT`; first-write scripts still land ~50–60 % of
  the 25–30 min target (revision recovers: +64 %/+72 %, one in-band).
- Tests: 304 unit, 108+ integration (3 pre-existing environmental failures
  unchanged, verified identical on HEAD). Evidence:
  `docs/audits/FULL_PROCESS_OPTIMIZATION.md` + `PROCESS_OPTIMIZATION_LOOP.md`
  Phase 4 appendices.
- Stop state: NOT committed; owner review checkpoint.

# Earlier state: Multichannel program — Phase 21 complete

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
