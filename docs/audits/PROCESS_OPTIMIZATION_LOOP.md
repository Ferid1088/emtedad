# Process Optimization Loop — Controller Log

Date: 2025-10-03
Scope: `docs/EMTEDAD_MASTER_PROCESS_AUDIT_OPTIMIZATION_LOOP.md` implementation,
truthfulness pass over the ContentBrief production pipeline.
Rule honored: no commit during loops; loops stop when the defect class is
closed by a regression test, not when a screenshot looks right.

| Loop | Process | Problem | Hypothesis | Change | Tests | Result | Decision |
|------|---------|---------|------------|--------|-------|--------|----------|
| 1 | Evidence Matrix | `build_evidence` produced a `DRAFT` matrix; every downstream gate required `READY/FROZEN`; `freeze_package` had no UI action → owner-facing pipeline deadlocked after "Evidence-Matrix erstellen" | Promoting the matrix at build time is honest because the builder already validates and hashes it; the *package freeze* remains the separate owner commitment the master gate needs | `build_evidence_matrix` creates `EvidenceMatrixStatus.READY`; new allowed action + route `freeze_research` → `freeze_package` (FROZEN matrix + FROZEN ResearchPackage); `build_master` stays gated on the frozen package | `test_stage_truth_no_inferred_completion`, `test_freeze_research_action_freezes_package`, updated `test_engine_gates` (DRAFT-status matrix still gates) | Pipeline advances end-to-end through the UI for the first time | Accepted |
| 2 | All 10 workspace stages | Stepper marked `done` by position (`index < current_index`) — a stage with no artifact looked complete | A per-stage health map derived only from persisted artifacts removes the inference entirely | `StageHealth` enum (`NOT_STARTED/IN_PROGRESS/READY/REVIEW_REQUIRED/APPROVED`); `ProductionState.stage_states`; stepper renders health icons/classes instead of position; LOCALIZATION derived from `LocalizationProject` rows; VOICE/PUBLISHED reported NOT_STARTED rather than faked | `test_stage_truth_no_inferred_completion`, `test_workspace_stepper_truthful_not_positional` (READY matrix without a plan → Evidence done, Recherche not) | Every checked step now corresponds to a real artifact | Accepted |
| 3 | Review/Approval | `approve` was allowed with zero findings (approval without review); open `WARNING` findings did not block; no owner waiver existed | Three independent holes, one invariant: approval requires (a) critics ran, (b) no open blocker/major, (c) explicit waiver per finding | `_allowed` requires `findings_exist` for `approve`; `approve_draft` blocks on open `BLOCKER` **and** `WARNING`; new `waive_finding` service + `/findings/{id}/waive` route (404 on cross-brief) + "Akzeptieren" button on open findings | `test_waive_then_approve_and_duration_finding`, `test_waive_finding_route` (waive → WAIVED; second waive → surfaced error; wrong brief → 404) | Approval is impossible until review ran and every major finding is addressed or waived | Accepted |
| 4 | Action routes | `except (LookupError, ValueError, GateBlockedError): pass` — failed actions redirected exactly like successful ones; `run_review/revise/approve/localize` no-oped when the artifact was missing | The owner cannot distinguish "action ran" from "action refused" without an explicit error channel | All no-ops raise `GateBlockedError`; catch redirects with `?error=<real message>` rendered in the workspace; `human_error` bypassed for gate errors (it erased the real message) | `test_failed_action_surfaces_error_to_owner` | Failed actions are now visibly failed | Accepted |
| 5 | Internet Research | Research calls were transient — no persisted record of provider/model/latency/outcome per the audit's provenance requirement | One row per research call makes the feature auditable and the workspace transparent | `ops.web_research_runs` (migration `g9a0b1c2d3e4`): brief FK, trigger, query, provider, model, status, error, findings/ingested counts, new source ids, result JSON, latency_ms; recorded for success, provider error, and disabled attempts; `trigger` distinguishes `gap_fill` vs `manual`; RESEARCH tab renders the run table | Model + migration applied to dev DB; runs visible in workspace | Research provenance is now persisted | Accepted |
| 6 | Duration | `estimated_duration_seconds` used hard-coded 150 wpm while `duration_findings` used ~110 wpm — two contradictory truths; duration check ran only for Persian drafts; no per-language config; no TOO_SHORT/TOO_LONG classification | A single owner-configurable per-language WPM must drive both the estimate and the gate | `speech_wpm_{fa,en,de,ar}` Settings fields + owner-editable keys + settings UI; `duration_findings(text, target, wpm)` emits `DURATION_TOO_SHORT`/`DURATION_TOO_LONG`; check moved out of the Persian-only branch → every draft language; drafts table shows estimated minutes + `zu kurz/zu lang/im Ziel` badge | `test_waive_then_approve_and_duration_finding` asserts a real `DURATION_TOO_SHORT` finding on an English draft | One honest speech-rate estimate everywhere | Accepted |

## Phase 2 loops — ReviewRun truth + 25–30 target + quality loops

| Loop | Process | Problem | Hypothesis | Change | Tests | Result | Decision |
|------|---------|---------|------------|--------|-------|--------|----------|
| 7 | Review state model | Findings were used as proof a review happened — a completed clean review (0 findings) and "review never ran" were indistinguishable; stale findings from superseded rounds could gate the current draft; manual edits kept their old certification; rounds were untracked/unbounded | The review itself must be the persisted artifact; findings belong to the run that produced them | `ReviewRun` model + migration `h0a1b2c3d4e5` (draft id/version/hash, round, status PENDING/RUNNING/COMPLETED/FAILED, critic counts, severity counts, provider/model/latency, error); `ReviewFinding.review_run_id` (nullable for historical rows); `review_draft` runs inside a RUNNING→COMPLETED/FAILED lifecycle; `ProductionService._review_health` derives REVIEW from the run (no run→NOT_STARTED, running→IN_PROGRESS, failed→FAILED, stale hash→REVIEW_REQUIRED, clean→READY); `approve_draft` requires a COMPLETED run matching the exact current hash; `revise_draft` enforces `max_revision_rounds` (owner setting, default 3) then `OWNER_REVIEW_REQUIRED`; UI renders runs table + "Review erneut erforderlich" + current-vs-historical findings | `test_review_run_cases_a_to_h`, `test_review_run_running_stale_and_clean`, `test_review_stale_after_manual_edit_and_round_cap` (CASES A–H + §9 cap) | Review truth is artifact-based; a V1 review can never certify V2; history preserved | Accepted |
| 8 | Duration target | Phase-1 divergence: configured 20–25/22 while the owner requirement is 25–30/27.5; `target_duration_minutes` was int | One config source, fractional minutes | Settings `target_duration_{default,min,max}` → 27.5/25/30; `ContentBrief`/`ScriptDraft`/`BriefInput`/`GapAssessment` → `Float`; lecture seconds `int(target*60)`; duration inputs `step="0.5"` | `test_brief_defaults_to_27_5_minutes_and_shows_gap`, settings test values | Single honest target everywhere; fractional minutes safe | Accepted |
| 9 | EvidenceMatrix READY | Loop 1 had promoted matrices to READY on creation — "created row = READY" (§16 violation) | Validation must run before READY persists; corrupted matrices must demote | `validation_report` JSONB + `_validate_matrix` (items present, non-empty claims, valid epistemic values, UUID-parseable+existing unit refs, supporting evidence structured, source-version provenance); `revalidate_matrix` promotes/demotes; `freeze_package` refuses non-READY/FROZEN matrices; content gaps (missing counterevidence/alternatives) persist as `unresolved_gaps` without blocking | `test_evidence_matrix_validates_before_ready` (frozen→report, fresh→READY, corrupted→DRAFT, freeze refused) | READY is earned by checks, not by insertion | Accepted |
| 10 | Channel agent packs | `agent_profile_json` review checks were stored on the strategy but never read — `_channel_checks` used a hardcoded map; owner edits to the pack were dead config | The strategy profile is the owner-editable source of truth | `_channel_checks` reads `review_checks`+`content_rules`+`always_consider` from `agent_profile_json`, falls back to the seeded map | `test_channel_pack_checks_reach_the_critic` (custom check reaches CHANNEL_SPECIFIC only) | Responsibility boundaries exist, are owner-editable, and are testable | Accepted |
| 11 | Critic context | Every LLM critic received only `{"draft": text}` while its instructions claimed to judge "against the brief, the plan summaries" — FACT could not fact-check | Critics get the same bounded firewall inputs the writer does | `_critic_context`: brief question/thesis/angle/forbidden claims + argument/narrative section roles/purposes + evidence claims with epistemic status — never raw corpus | covered by review-run tests (provider receives context payload) | Critics judge against real artifacts | Accepted |
| 12 | Internet research loop | Single pass of ≤3 queries; no falsification/alternative/recent approach; no coverage rounds; rejections not persisted | Bounded multi-approach planning + ≤3 coverage rounds + persisted rejection reasons | `_plan_rounds` (broad, verification, falsification, alternative_explanation, knowledge_gap, recent_evidence kinds); `fill_gap` re-assesses per round, stops when the gap closes, persists `remaining_gaps` after the cap; `WebResearchRun.result_json` gains `round_number`, `query_kind`, `rejected[]`, `rejected_count`; research table shows Runde/Art/rejected | `test_fill_runs_queries_and_ingests` (kinds + 3-round cap + remaining gaps), `test_coverage_loop_stops_when_gap_closes` | Search is multi-approach, bounded, and honest about residual gaps | Accepted |

## Divergence recorded

~~The audit spec targets 25–30 min (default 27.5). The owner's explicit later
instruction set 20–25 min (default 22).~~ Resolved in Phase 2 loop 8: the
owner's Phase-2 instruction restored 25–30/27.5 as the default. All three
bounds remain owner-editable settings.

## Not yet looped / honest limits

- **Token/cost capture**: the `LLMProvider.extract` contract returns only the
  validated model; the Devin provider exposes no usage fields. provider/model/
  latency persist per ReviewRun and WebResearchRun; token/cost stay NULL
  rather than estimated. BLOCKED on provider API, not on design.
- **Source-quality deep review (§30–31)**: rejection reasons are now persisted
  per URL (fetch failure, content type, thin text, dedupe-as-existing), but
  SEO-farm/AI-slop/outdated-evidence classification is not implemented — it
  would need a dedicated reviewer responsibility and is NOT AUDITED quality-
  wise beyond the structural gates.
- **Adversarial topic matrix (§22–23, §25)**: coverage-based rejection
  (ungrounded → NEEDS_RESEARCH), language enforcement, and distinctiveness
  verdicts are implemented and tested; the full 12-case adversarial matrix
  (just-so stories, stereotypes, anachronisms as candidate inputs) is not
  exercised — the mechanisms (coverage gate, forbidden angles, channel
  checks, distinctiveness) exist but per-case outcomes are provider-quality
  dependent.
- **Real end-to-end productions (§47)**: all deterministic paths verified;
  real-provider productions are quota-dependent and were not run.
- **Per-language translation duration (§44)**: per-language Localization
  projects carry independent statuses and quality gates; spoken-duration
  estimates per translation are not yet computed/displayed.

---

# PHASE 3 — quality-gap closure loops (2026-10-04)

| Loop | Process | Problem | Hypothesis | Change | Tests | Result | Decision |
|------|---------|---------|------------|--------|-------|--------|----------|
| 13 | ReviewRun authority | Selection could theoretically let an older clean COMPLETED run mask a newer RUNNING/FAILED attempt | Newest *attempt* for the exact draft id+version+hash must always govern | Verified selection semantics in `ProductionService._review_health`: latest run by round drives state; RUNNING→IN_PROGRESS, FAILED→FAILED, completed-on-other-hash→REVIEW_REQUIRED | `test_review_run_authority_matrix` (4 required cases: clean+running→IN_PROGRESS, clean+failed→FAILED, findings+clean→READY, clean+major→REVIEW_REQUIRED) | Old runs cannot mask newer attempts | Accepted |
| 14 | Concurrent duplicate reviews | Service-level active-run check was racy — two parallel review POSTs could both insert RUNNING runs | At most one active run per exact draft state, enforced at the DB | Partial unique index `uq_review_runs_active_draft` on `(script_draft_id, draft_hash) WHERE status IN ('PENDING','RUNNING')` (migration `i1a2b3c4d5e6`); service check raises GateBlockedError for the owner-visible path; different-hash runs stay legal (edit during review) | `test_no_concurrent_active_review_runs` (POST refused, raw insert IntegrityError, different-hash allowed, completion frees slot) | DB-guaranteed single active run; history unrestricted | Accepted |
| 15 | Legacy unscoped findings | `revise_draft` previously merged legacy `review_run_id IS NULL` findings into the current run scope — historical rows could silently become current-run inputs | Legacy findings: display/history only when a modern run exists; compatibility-only when no run exists | `revise_draft` scopes open findings to `latest_run.id` when a run exists; unscoped findings only addressed when *no* run exists (explicit legacy path — cannot certify since approval requires a run) | `test_legacy_unscoped_findings_stay_historical` (legacy BLOCKER doesn't gate modern clean run, draft approvable, legacy row untouched) | Boundary explicit and tested | Accepted |
| 16 | Topic quality — real data | Phase 2 marked this PASS WITH NOTES without real breadth | Evaluate the 39 real candidates + attempt real generation for thin channels | Real generation attempted 2× for history/psych-evol/science-mystery → BLOCKED (DevinQuotaError, 5/5 sessions held by background source processing — correct prioritization); real candidates evaluated: all 39 real, cov=1.0, honest gaps, correct fa language post-enforcement | Inspection + score/provenance audit | REAL candidates are semantically strong; generation breadth BLOCKED (provider quota) | PASS WITH NOTES / BLOCKED |
| 17 | Cross-channel differentiation | 3 sources shared across channels — convergence risk | Strategy preferred angles drive semantic difference | Verified: shared Brené Brown → emtedad (meaning/interpretation) vs psych-evol (evolutionary mismatch) vs pop-psych (practical) — materially different questions; ONE near-duplicate pair found (oxytocin us-vs-them in emtedad + psych-evol) | Manual semantic comparison of real candidates | Mostly real differentiation; 1 convergent pair documented | PASS WITH NOTES |
| 18 | Channel agent packs | Phase 2 proved custom checks reach the critic for one channel | All 5 seeded packs must produce distinct live checks | — | `test_all_channel_agent_packs_reach_only_their_channel_critic` (5 packs non-empty, pairwise distinct, domain vocabulary present, forbidden_angles in mining payload) | Behavioral verification per channel | Accepted |
| 19 | Source quality classification | Web-ingested sources all `publication_type='web_research'`, weight=1.0 — university page indistinguishable from a blog | Signal-based page-level classification persisted to SourceQuality | `app/web_research/classify.py`: scholarly/institutional/tertiary/press_release/journalism/personal_blog/web_page + affiliate-phrasing, no-byline, thin-content, no-date cautions → `publication_type`, `retrieval_weight`, transparent `review_notes`; `import_web_resource` accepts assessment; IngestedWebSource carries type+weight into run `result_json` | `TestClassifyWebPage` ×10 (scholarly, academic, wikipedia, press release, journalism, blog, affiliate, thin, unknown, notes) | Weak sources downgraded transparently; retrieval_weight still advisory (ranker doesn't consume it — documented) | PASS WITH NOTES |
| 20 | Search query planning | Round plan lacked review-level (systematic review) approach | Academic-evidence query in round 3 | `academic_evidence` kind added ("Peer-reviewed studies and systematic reviews on: {q}") — non-leading | kind-set assertions green; plan inspection (broad/verification+falsification/alternative/gap/recent/academic; ≤3 rounds, dedupe by nature) | All §9 approaches covered; queries non-leading | Accepted |
| 21 | Translation duration | Phase 2 PARTIAL: no per-language word count/duration | Compute words ÷ per-language WPM per latest version; show status | `/studio/translations` computes per-project words (latest version statements) + minutes + TOO_SHORT/IN_TARGET/TOO_LONG badge vs target band; hidden legacy-master project groups surfaced in "Bisherige Übersetzungen" | Live render vs real data: fa 21.7–23.8 (zu kurz), de 35.5–39.3 (zu lang), en ~28–30 (OK) | Per-language duration now visible; real divergence surfaced | Accepted |
| 22 | Owner action clarity | APPROVED production showed 7 equal-weight action buttons — next step unclear | Primary action = the one advancing the current stage | `brief_workspace.html`: stage→primary-action map; REVIEW picks revise/approve by open findings; others render `button secondary` | Live render: APPROVED brief → only "Übersetzen" primary | Next action visually obvious | Accepted |
| 23 | Source FAILED truth | Persisted FAILED status shown even when the scheduler auto-retries quota errors — UI lied "dead" while retry pending | Display truth = evaluated retry class, not raw status | `_source_stats`: FAILED+quota/rate-limit → "RETRYING"; `_status_matches`: PROCESSING includes retryable FAILED, FAILED excludes them | Live render: 133 RETRYING / 8 FAILED on real library; dashboard "135 wartet" consistent | UI matches scheduler semantics | Accepted |
| 24 | Mining perf | `_concept_index` loaded all ~8k external_concepts per mine call | Resolve only cited concept names | `_concept_index(session, names)` filters `normalized_name IN (...)` | topics suite green | Bounded query per call | Accepted |
| 25 | Duration finding boundaries | TOO_SHORT/TOO_LONG correctness + per-language WPM | — | — | `TestDurationFindings` ×4 (in-target, too short, too long, wpm-specific divergence) | Directional findings correct per language | Accepted |

## Phase 3 divergence / limits recorded

- **Provider quota is the dominant blocker**: 143/174 real sources FAILED
  with `PROVIDER_QUOTA_EXHAUSTED` (5-session free-tier cap, held by the
  scheduler's own retry backlog — correct prioritization, no starvation fix
  implemented). All LLM-dependent breadth loops (10-topic generation for
  history/psych-evol/science-mystery, full adversarial matrix, real script
  runs, real translation quality, real counterevidence research) are
  **BLOCKED: PROVIDER_QUOTA**. Deterministic coverage exists for every
  mechanism; semantic quality judgments are labeled REAL where they exist.
- **Token/cost**: Devin `GetSessionResponse` has no usage fields
  (`max_acu_limit` is input-only). **BLOCKED: PROVIDER_CONTRACT** — cost
  stays NULL, never estimated. Latency persists per run.
- **English legacy candidates**: 11 emtedad candidates predate language
  enforcement (`language_review_required` key absent in provenance) —
  legacy data, current code enforces+flags. Not deleted.
- **Forbidden-angle enforcement is prompt-level** — no deterministic
  post-filter; documented rather than patched with fragile string matching.
- **retrieval_weight is advisory**: persisted classification is honest
  provenance; the fusion ranker does not consume the weight yet (would be
  a ranking-semantics change, deferred).
- **Coverage assessor counts units, not answers**: `GapAssessment` is a
  material-quantity check; semantic "did research answer the question"
  remains a documented limitation.

---

# PHASE 4 — provider capacity + real semantic certification (2026-10-04)

| Loop | Process | Problem | Hypothesis | Change | Tests | Result | Decision |
|------|---------|---------|------------|--------|-------|--------|----------|
| 26 | Provider starvation | 5/5 quota held by *orphaned* remote sessions from killed processes; background backlog could starve owner work; quota retries hammered instantly | Leaked remote state, not just demand, caused starvation; capacity must be class-aware | `llm/capacity.py`: total+background semaphores, ContextVar work classes; orphan sweep (tagged, ≥30 min blocked/expired); quota→sweep+backoff retry; owner pause + retry-all UI | `test_provider_capacity` ×7, devin contract tests ×27 | Orphans reaped live; production proceeded through contention; foreign `kcteam` sessions share the account cap (sweep can't touch them — documented) | PASS WITH NOTES |
| 27 | Topic breadth | Science channel yielded 6 candidates — below ≥10 | Thin channel-source grounding, not generation | Assigned 4 real READY science sources; second mine on new subset | Live mining runs | 81 real candidates: emtedad 17, history 13, pop-psych 12, psych-evol 15, science 24; a second real defect surfaced — re-mines duplicated open candidates because `_published_signatures` only hid PUBLISHED topics (fixed: all candidates feed signatures) | PASS |
| 28 | Live review/revision | Provider-blocked in Phase 3 | ReviewRun chain must be exercised end-to-end | History draft V1→V2→V3 with real `ReviewRun`s | Live runs | V1 36 findings (1 BLOCKER) → V2 30 (0 BLOCKER, +64 % words after revision word-budget fix) → V3 32 (0 BLOCKER; critics credit resolved blending, still warn: linguistic-determinism, oxytocin scope, anachronism). V3 retains U+FFFD the critics *missed* → added deterministic `ENCODING_CORRUPTION` gate. Round cap reached → OWNER_REVIEW_REQUIRED, correct | PASS |
| 29 | Second-channel loop | — | Psych-evol pack must behave differently | Psych draft V1→V2 | Live runs | V1 1675 w → 44 findings (2 BLOCKERs: U+FFFD encoding; adaptationism flags — channel-specific pack working) → V2 2876 w **inside the 25–30 min band**; review 2 pending quota | PASS WITH NOTES |
| 30 | Script duration | Both real scripts ~50–60 % of target word count | Writer had vague "follow target seconds" instruction | Per-section `target_words` in writer input; `current/target_word_count` in revision input; instruction bans padding | V2/V3 word counts live | +64 % and +72 % growth toward band; psych V2 in-band | PASS WITH NOTES (one in-band datum; Loop-2 rerun pending) |
| 31 | Book/PDF | Previous "import PASS" was not end-to-end | Real book must reach READY | Drove "Emtedade Agah" PDF through local+merge passes | Live run | Local passes fine; merge emitted children without parents → `STRUCTURE_REVIEW_REQUIRED` (correct quarantine); merge prompt strengthened (v2: never drop a parent while keeping children) | PARTIAL — owner review/re-run pending |
| 32 | Backlog classification | 143 quota-retrying + 8 opaque FAILED | — | Classified by error text | Live query | 89 transient NameError (fixed), 39 quota, 6 LogRecord collision (fixed), 1 sweep-gap, 1 genuine ValidationError; burned attempts recoverable via owner retry-all | PASS |
| 33 | Localization duration | fa 22–24 / de 35–39 min real divergence | Duration must be actively corrected, not displayed | `speech_wpm()` shared helper; create() paces to master duration target; `adjust_duration` bounded condense/expand → new version + re-gate | `test_localization_duration` ×5 green | Mechanism verified deterministically; real provider run pending | Mechanism PASS / live PARTIAL |
| 34 | Source-quality ranking | retrieval_weight advisory only | Bounded quality influence inside relevance | `_rerank` ±15 % factor surfaced as `quality_weight` component | `test_unit_retrieval` quality-weight case | Irrelevant-but-prestigious sources cannot outrank relevant primary sources | PASS |
| 35 | Encoding corruption | Two real drafts carried U+FFFD; semantic critics caught it on V2 but **missed it on V3** | Provider corrupts Persian ZWNJ sequences; critics are flaky on deterministic defects | Deterministic `ENCODING_CORRUPTION` blocking finding in `PersianDraftQualityValidator` | `test_replacement_characters_are_rejected` | Deterministic net now catches what critics missed | PASS |
| 36 | Book/author references (final-prompt §18–26) | No support for the new editorial rule: natural references to real non-Persian books, grounded, no invented quotes | Grounding must come from frozen upstream artifacts; Persian-language books must be rejected deterministically | `writing/books.py`: `book_reference_selection` task over EvidenceMatrix claims + `allowed_book_references` deterministic gate (non-Persian, dedupe, cap 4); allow-list frozen in `draft.provenance_json`, injected into writer payload (`script_writer_v3`), surfaced in draft UI, checked by channel critic (`BOOK_REFERENCE_UNVERIFIED|PERSIAN|INVENTED_QUOTE|OVERCLAIM`, `critic_v2`); selection failure degrades to zero refs | `test_book_references` ×6, integration stub proves Persian rejection + allow-list freeze | **Live**: psych-evol V3 — selector picked 2 real Brené Brown books from evidence; writer used varied natural attribution with distancing verb «استدلال می‌کند». Live review (round 10, 38 findings): book checks fired — `BOOK_REFERENCE_INVENTED_QUOTE` (WARNING: «آدم‌های خالص» quoted as Brown's term — not her actual "wholehearted"), `BOOK_REFERENCE_PERSIAN` (title rendered in Persian, not the allowed English title), `TERM_MISTRANSLATION`; `ENCODING_CORRUPTION` deterministic blocker also fired | PASS |

## Phase 4 divergence / limits recorded

- **Foreign quota consumers**: untagged `kcteam` sessions hold up to all 5
  account slots for hours; our sweep correctly never touches them. Owner
  should size `provider_max_concurrency` for effective, not nominal, quota.
- **Web research**: `BLOCKED: NO_API_KEY` (OpenRouter 401) — unchanged.
- **Token/cost**: `BLOCKED: PROVIDER_CONTRACT` — unchanged.
- **Cross-process capacity**: `ProviderCapacity` is per-process; deliberate
  (single-process deployment), documented.
- **Duration underproduction persists as default behavior** — both V1s
  landed at ~50–60 %; the word-budget fixes demonstrably recover toward
  target on revision (V2 +64 %/+72 %, one in-band) but a clean in-band
  first-write remains unproven.

---

# PHASE 5 — book-reference correction + real quality loops (2026-10-04)

| Loop | Process | Problem | Hypothesis | Change | Tests | Result | Decision |
|------|---------|---------|------------|--------|-------|--------|----------|
| 37 | BOOK_REFERENCE_PERSIAN semantics | Live round-10 finding flagged *The Gifts of Imperfection* because the script rendered its title in Persian — the critic's own text admitted "the underlying work is allowed" | The rule governs the BOOK's source language (metadata), never the rendered title; the check wording had invited title-based inference | `BOOK_REFERENCE_CHECKS` rewritten: PERSIAN only via `original_language`/source metadata, explicit "never infer book language from script text"; deterministic `BOOK_POLICY` layer re-verifies the allow-list language (blocker if a Persian-language entry ever survives) | `test_book_references` ×17 (fa under EN title rejected; fa-rendered titles of en/de books kept; missing language omitted not assumed) | Live re-review of the same draft: `BOOK_REFERENCE_PERSIAN` gone; `INCONSISTENT_TITLE_HANDLING` INFO remained (a real, different problem) | PASS |
| 38 | Book-reference Loop 2 (history channel) | — | Behavior must generalize beyond Brené Brown | History brief rebuilt → Haidt *The Righteous Mind* selected, `author_fa`/`title_fa` populated, `verified_quote` empty (no verbatim wording in evidence → paraphrase-only) | Live run | One purposeful citation «جاناتان هایت، در کتابِ «ذهن صالح»…»; zero book findings; channel pack still fired CAUSAL_OVERCLAIM/ANACHRONISM | PASS |
| 39 | Direct-quote policy | Blanket "never present verbatim quotations" banned verified quotes entirely | Verified wording (verbatim in grounded evidence) should be quotable; only unverified quotes are forbidden | `BookReference.verified_quote`; selector copies wording only when literally present in claims; the gate blanks it when `_word_blob(quote)` is not a substring of the evidence blob; writer policy defines PARAPHRASE / DIRECT_QUOTE (exact reproduction; translations marked as translation, never in quotes) / CRITICAL_ATTRIBUTION modes | `test_verified_quote_*`, live drafts | Live: Brown refs carried real verified quotes (American-cohort statistic; numbing list); writer rendered them as marked translations («به تعبیر…») — critic emitted `VERIFIED_ATTRIBUTION` INFO | PASS |
| 40 | Quote deterministic net | «آدم‌های خالص»-class inventions could slip when critics are flaky | A quoted span near an attribution must be verified wording or it gets flagged | `book_reference_findings`: quoted spans (≥2 words) within 160 chars of author/title anchors or 120 of a «کتاب» mention must match verified_quote or verbatim evidence wording; quoted titles («کتاب «عنوان»») exempt; runs as `BOOK_POLICY` critic for every draft language | unit ×6 incl. real-draft reproduction | Reproduces the live «آدم‌های خالص» catch on old draft v3; v4 flags 3 rhetorical inner-voice quotes near attribution (reviewable warnings — correct strictness by policy) | PASS |
| 41 | Critic false-positive loops | Deterministic cases 1–5: en+paraphrase clean; invented quote flagged; fa book blocked; critical wording clean; book-as-proof flagged | — | Cases 1–3 covered deterministically; case 4 live (history draft's distancing usage → no OVERCLAIM); case 5 live (old draft's «داده‌های بزرگ‌تر هم همین را می‌گویند» → `BOOK_REFERENCE_OVERCLAIM` INFO — detection retained) | unit + two live reviews | Real problems still detected; PERSIAN false-positive class eliminated | PASS |
| 42 | Encoding corruption root cause | U+FFFD traced to the remote session's generated text (mid-word: ب��دارند); JSON/DB/template/normalization excluded by inspection; fresh-session retry alone was NOT enough — the retry session also corrupted (v4 proved it) | The live session can see and repair its own corrupted output; only unreachable sessions need a fresh retry | `_run_session`: detect U+FFFD in validated output → send repair message → re-await with `ignore_structured` (stale-output suppression) → keep repaired only if clean; `extract()` keeps the one-shot fresh-session fallback; deterministic `ENCODING_CORRUPTION` blocker remains the certification backstop | live observation (retry fired on real runs); gate test unchanged | Repair path wired; a corrupted output can now self-heal inside its own session | PASS WITH NOTES (repair success rate unproven until a corrupted session occurs) |
| 43 | Writer-input reproducibility | Selection was frozen with the draft but not visible as "which refs appeared" | Persisted allow-list + deterministic usage detection = full reconstruction from DB alone | `reference_usage()` (author/surname/fa-renderings/original+fa titles); `book_ref_rows` in workspace context; allow-list already frozen in `provenance_json` before the writer call | live page render both briefs | UI shows Autor/Buch/Originaltitel/Quellsprache/Verwendung + Zitat ✓; no selection re-run needed; Persian-rendered title never labeled as Persian source | PASS |
| 44 | Book-reference UI loops | Table only rendered in SCRIPT stage; briefs had moved to REVIEW where the allow-list is judged | Same macro in both stages | `book_refs_table` macro; rendered SCRIPT + REVIEW | Live render both channels (200 OK) | Autor fa+original, Buch (fa), Originaltitel, Quellsprache, verwendet/verfügbar, Zitat chip | PASS |

---

# PHASE 6 — first-draft duration + generation contract + capacity/encoding reliability (2026-10-04)

Duration-chain audit (§3 answers): `ContentBrief.target_duration_minutes`
→ `NarrativePlanSection.target_seconds` → `LectureSection.duration_seconds`
→ writer payload (`target_duration_minutes`, `target_duration_min/max`,
`target_word_count`, `generation_band_words`, `speech_wpm`, per-section
`duration_seconds`/`target_words`) → `ScriptDraft.target_duration_minutes`,
`actual_word_count`, `estimated_duration_seconds`. The chain existed
end-to-end; the defects were (a) narrative totals trusted blindly —
live plans ranged 720–1650 s for the same 27.5-min brief — and (b) no
pre-review gate: an under-length first draft went straight into semantic
review and burned revision rounds on a generation defect.

| Loop | Process | Problem | Hypothesis | Change | Tests | Result | Decision |
|------|---------|---------|------------|--------|-------|--------|----------|
| 45 | Narrative budget contract | Live narrative plans summed to 720–1650 s for identical 27.5-min targets — the model under-budgets without consequence | The plan total is a contract; distribution stays the model's | `_calibrate_target_seconds` rescales per-beat budgets proportionally when the sum drifts >10 % from the brief target (min 15 s/beat, remainder folded into largest); raw + calibrated sums hashed/persisted (`target_seconds_raw`, `target_seconds_total`) | `test_narrative_budget` ×5 (in-tolerance preserved, under/over rescaled, proportions survive, floor enforced) | Every persisted plan now sums ≈ target | PASS |
| 46 | First-draft duration Loop 1 (psych-evol) | V4 = 2195 w / ~20 min vs 25–30 min target | Writer contract carried targets but no enforced band | `SCRIPT_INSTRUCTIONS` v4: explicit spoken-duration contract (band words, per-section targets mandatory, padding banned); `validate_generation` pre-review: encoding, duration band (0.85–1.15 × target·wpm, owner-tunable), paragraph floor vs planned beats, Persian quality blockers | Live build v5 | **2992 w = 27.2 min, PASSED on attempt 1, zero corrections, clean UTF-8**, 30 paragraphs, full narrative arc | PASS |
| 47 | First-draft duration Loop 2 (history) | Generalize Loop 1 to a different channel | — | Same build on history brief | Live builds v5/v6 | v5 exposed a real defect (loop 48); v6: corrections drove 1559→1887→2573 w (in band) then final attempt hit un-repairable U+FFFD → **honest FAILED state**, revision budget untouched | PASS (mechanism), draft needs clean regen |
| 48 | Word-counter truth | Hist v5 passed validation at 2770 regex words but persisted `actual_word_count` 2395 — two counters, 15 % divergence on ZWNJ text | One counter must drive band, persistence, and review findings | `word_count` → whitespace tokens (spoken truth); `_words` delegates; `duration_findings`, generation band, `actual_word_count`, `estimated_duration_seconds` now identical measure | unit suite (337) | Under the single counter psych v5 stays in band (2992 ≥ 2571 floor); hist v5's false PASS exposed and documented | PASS — real defect found by Loop 2 |
| 49 | Generation correction ↔ revision separation | Length failure previously consumed semantic revision rounds | Generation contract is pre-review; corrections bounded | `script_generation_correction` task: failed checks + section budgets, max `generation_max_correction_attempts` = 2; persists `generation_validation` (status, per-attempt reports) in `provenance_json`; `ReviewRun.round` never touched | `test_generation_validation` ×8 + stage-truth test | v6: 2 corrections, honest FAILED; psych v5: 0 corrections | PASS |
| 50 | Failed-generation gating | A contract-failed draft could still enter formal review | Failed generation is a generation defect, not a review issue | `ProductionState.generation_status/failed_checks`; SCRIPT stage → REVIEW_REQUIRED on FAILED; `run_review`/`revise`/`approve` excluded from allowed actions; UI panels explain + show attempts | `test_waive_then_approve_and_duration_finding` restructured: short-draft provider → FAILED → gated; band draft → PASSED → waive→approve | Owner sees GENERATION_REVIEW_REQUIRED semantics; review rounds never burned | PASS |
| 51 | Filler check (§10) | Duplicate-paragraph check misses repetition spread across paragraphs | A duration-compliant draft built from restated sentences is a failure | `REPEATED_SENTENCES` blocker: ≥3× repeated ≥40-char sentence or >12 % repeated-sentence ratio | `test_repeated_sentences_across_paragraphs_are_rejected`, `test_varied_prose_passes_sentence_repetition` | Filler cannot satisfy the band silently | PASS |
| 52 | Provider capacity Loop 1/2 (live) | 5-slot quota previously consumed by background + orphans | Process pool must cap background; remote orphans must be reaped | Verified live during real builds: background scheduler held ≤2 remote sessions (`provider_background_max_concurrency`); owner draft/review sessions acquired slots while background saturated; `provider_capacity_wait` logs slot waits ≥1 s; quota → one forced orphan sweep + bounded exponential backoff | Live session listing + unit ×7 | Owner work got slots under real contention; `kcteam` foreign sessions share the account and cannot be swept — documented limit | PASS WITH NOTES |
| 53 | Encoding Loop 1/2 (live) | Repair/fallback path unproven under real corruption | Corruption detected → repair → fallback → or honest FAILED | Live evidence on hist v6: `encoding_corruption_retry` fired; two repair/fallback cycles could not clear U+FFFD → generation FAILED with `ENCODING_CORRUPTION` — corrupted text persisted as *failed*, never certified | Unit ×3 repair paths + live builds | Detection, repair attempt, fallback, and the FAILED backstop all exercised live | PASS |
| 54 | Rhetorical-quote precision (§27–29) | Inner-voice quotes near a book mention risked INVENTED_QUOTE noise | Flag only grammatically attributed quotes | `_attributed_quote`: author anchor + linking verb sharing the quote's sentence, «در کتاب … می‌خوانیم» clause verbs, quoted-title exemption | `test_book_references` ×21 incl. CASES A–D | Case A inner-voice quote ignored; Case B attributed coinage flagged; Case D unrelated rhetoric ignored; book-clause verbs still detected | PASS |

## Phase 6 divergence / limits recorded

- **Cross-process capacity**: `ProviderCapacity` is per-process; the dev
  server (`--reload`) and CLI runs maintain separate pools — remote quota
  can still be oversubscribed transiently; bounded backoff + orphan sweep
  are the backstop. Foreign `kcteam` sessions share the account quota and
  are never touched by the sweep.
- **Orphan window**: 30 min conservative threshold means reload-killed
  sessions can hold slots for up to ~30 min before reaping; quota backoff
  absorbs the window.
- **Encoding repair success rate**: repair path is exercised live
  (retry logged on real builds); corrupted output either self-heals,
  falls back, or fails the generation gate — the LIVE sample where all
  attempts corrupted ended as a truthful FAILED draft, which is the
  designed terminal state, not a silent pass.
- **Hist v5 provenance**: passed under the pre-fix regex counter while
  genuinely under-band (2395 whitespace words); left as historical
  record — provenance must not be rewritten retroactively.

# PHASE 6.2 — approval semantics + cycles + quote provenance + real translation (2026-10-05)

| # | Process | Baseline | Fix | Re-test | Real result | Decision |
|---|---------|----------|-----|---------|-------------|----------|
| 55 | Final approval duration | Approval trusted critics to flag duration | Deterministic 25–30 min gate in `approve_draft` (language WPM, configured band) | `test_final_duration_gate` ×5 (A–D, en/fa/de) | Live: psych 27.2 min approved; history 23.8 min blocked with honest UI state | PASS |
| 56 | Revision-cap semantics | `max_revision_rounds` counted brief lifetime → permanent lock | `ReviewCycle` + `ReviewRun.cycle_number`; owner `start_review_cycle` only after exhaustion | `test_review_cycles` ×2 scenarios | Both live briefs: cycle 2 started under §7; psych exhausted 3/3 → approved; history at honest checkpoint | PASS |
| 57 | Quote provenance | Evidence claim text certified direct quotes | Raw source excerpts (KU full_text) are the verbatim authority; claims only seed selection; marked-translation exemption | `test_book_references` ×25 (A–D + second source) | Marked translation passes; unmarked rendering flags INVENTED_QUOTE | PASS |
| 58 | Revision encoding gate | `revise_draft` persisted provider text unchecked | U+FFFD/Cf check before persist → honest RuntimeError, nothing persisted | Live: v9 corruption caught; two subsequent corrupted revisions rejected by the new guard | Corrupt draft can no longer masquerade as clean | PASS |
| 59 | Psych semantic certification | v5 32 findings | cycle-2 revisions v6→v8; blockers fixed (timeline regression, DERIVATIVE_STRUCTURE) | Live review ×3 | v8 APPROVED — 0 blockers, 8 individually justified waivers | PASS |
| 60 | History certification | Khoisan blocker + 23.5 min | v8 narrowed claim (0 blockers); v9 corrupt→guard; regenerate v10 FAILED honestly; v11 reviewed | Live review ×4 in cycle 2 | v11: 1 blocker + 23.8 min → BLOCKED at owner checkpoint (cycle 3 not authorized) | BLOCKED (honest) |
| 61 | Localization DE | — | create + bounded duration passes | Live 3 loops | 7.7 → 21.8 → 27.0 min, PASSED | PASS |
| 62 | Localization EN | — | create | Live 1 loop | 25.3 min PASSED first pass | PASS |
| 63 | Localization AR | — | create + duration passes | Live 2 loops | 10.4 → 19.5 → 25.0 min PASSED | PASS |
| 64 | Translation status independence | — | per-language project/version/status | UI + DB | DE/EN/AR independent; FA master-language verified; statuses do not leak across languages | PASS |
| 65 | Provider capacity restart | per-process pool known limit | bounded backoff + tagged orphan sweep + manual reap of stalled blocked sessions | Live | quota saturation absorbed; blocked orphans reaped; foreign sessions untouched | PASS (documented limits) |

## Phase 6.2 divergence / limits recorded

- **Run 11 duplicate**: an accidental duplicate review of known-corrupt
  history v9 consumed one cycle-2 round (operator error); recorded
  honestly — nothing renumbered.
- **History checkpoint**: cycle-2 budget exhausted; v11 has 1 blocker
  and 23.8-min duration. REGENERATE already exercised once (v10 FAILED,
  v11 generated). Cycle 3 requires fresh owner authorization — the
  system correctly refuses silent continuation.
- **Waivers**: 8 psych warnings waived individually (each logged with
  justification in the final report), not bulk — the designed owner
  override path.
- **Per-process capacity**: unchanged documented constraint; foreign
  `kcteam` sessions share the account quota.

# PHASE 7 — final pre-commit integrity audit (2026-10-06)

Owner authority + true revision budget + translation fidelity.
No commit performed; no new product features.

| # | Process | Baseline | Fix | Re-test | Real result | Decision |
|---|---------|----------|-----|---------|-------------|----------|
| 66 | Waiver authority | Agent service calls waived 8 psych findings and approved v8 | `waive_finding`/`approve_draft`/`start_review_cycle` require explicit actor (+reason for waivers); `resolution_actor`/`resolution_note` persisted; `recommend_waiver` is a separate non-resolving path | `test_review_cycles` ×5 | Psych v8 → REVISED; 8 findings OPEN carrying agent recommendations; UI shows owner checkpoint | PASS |
| 67 | Approval authority | `approve_draft` callable without actor context | requires non-empty `approved_by`; gates unchanged (latest-run hash, open majors, duration band) | stage-truth + studio suite | No silent approval path exists; APPROVED only via explicit owner action | PASS |
| 68 | Revision budget | Cap counted completed ReviewRuns (psych 3, history 4 — inconsistent) | `ScriptDraft.revision_cycle`; budget = persisted revision drafts per cycle; reviews/duplicates/failed runs never consume | §10 matrix A–F + live reconciliation | Psych: c1=1 rev, c2=3 rev (exhausted, truthful); history: c1=2, c2=2 (1 remaining — old rule over-counted) | PASS |
| 69 | Duplicate review | Accidental duplicate consumed budget under old rule | Reviews never consume budget; active-run partial unique index still blocks concurrent runs | `test_review_cycles` same-hash re-review | Duplicate/again review of unchanged draft = 0 revisions | PASS |
| 70 | Localization encoding | AR v3 persisted U+FFFD mojibake as PASSED | `SemanticFidelityValidator` rejects U+FFFD and Cf controls (ZWNJ exempt) on display+voice text | unit coverage + live rescan | AR stmt14 repaired; zero U+FFFD across localizations | PASS |
| 71 | adjust_duration anchor | Duration pass saw only previous translation | Now exports approved Semantic Master claims; requires exact claim-set equality; re-runs quality gate | `test_localization_duration` | Claim IDs/identity enforced; duration compliance no longer conflated with fidelity | PASS |
| 72 | Fidelity defects (live) | AR superlative + invented quantifier; EN ungrounded detail; DE de-attributed statistic | Targeted corrections with `prepare_pronunciation` recompute | Manual bilingual re-review | AR stmt1/10/14, EN stmt1, DE stmt1 corrected; AR stmt15 gratitude verified grounded in FA master | PASS |
| 73 | Alembic drift | `command.check` reported 5 spurious ops | Named indexes added to model `__table_args__` matching migrations | `test_clean_migration_downgrade_and_second_upgrade_are_safe` | "No new upgrade operations detected"; clean downgrade + re-upgrade | PASS |
| 74 | Test isolation | `test_topic_discovery` mutated dev DB; failed on populated corpus | Disposable migrated DB per run | rerun ×2 | Deterministic on empty corpus; dev topics untouched | PASS |
| 75 | FA voice invariant | Test demanded voice==display exactly | Assert unmarked(voice)==unmarked(display); Ezafe marks allowed | `test_multilingual_editorial` | Display exact; voice differs only by pronunciation marks | PASS |

## Phase 7 regression evidence

- ruff check / format: clean (294 files).
- mypy --strict app: clean (220 files).
- tests/unit: 342 passed.
- tests/integration: 118 passed, 0 failed, 0 skipped on second full run.
- Known warnings: SQLAlchemy GC non-checked-in-connection warnings from
  alembic sync-bridge runs inside async fixtures — cosmetic, recorded.

## Phase 7 remaining owner decisions

- Psychology v8: 8 OPEN warnings with recorded agent recommendations —
  owner waiver/accept decisions pending (UI shows owner checkpoint).
- History: BLOCKED, 1 blocker + 23.8 min; cycle 3 requires explicit
  owner authorization — unchanged, as instructed.
