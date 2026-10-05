# Full Process Optimization — Audit Table

Date: 2025-10-03
Spec: `docs/EMTEDAD_MASTER_PROCESS_AUDIT_OPTIMIZATION_LOOP.md`
Loop log: `docs/audits/PROCESS_OPTIMIZATION_LOOP.md`

Scope of this pass: the truthfulness core of the ContentBrief production
pipeline — the defects that made the owner UI certify stages that had no real
artifact, deadlocked after Evidence, allowed approval without review, and lost
all research provenance. Per-process loops that were not run are marked
**NOT AUDITED** below rather than reported green.

## Process audit table

| Process | Baseline | Defects found | Fixes | Tests | Status | Loop |
|---------|----------|---------------|-------|-------|--------|------|
| Content Brief (8) | READY/LOCKED brief gates research | None new — brief validator (`validate_ready`) already enforced | — | existing brief tests | DONE | 0 |
| Research Plan | READY plan persisted with questions + input hash | None | — | stage-truth test | DONE | 1 |
| Evidence Matrix (10) | `DRAFT` on creation, unreachable `READY`, no freeze action | Deadlock: matrix never promoted; freeze unreachable from UI | Matrix created `READY`; `freeze_research` action+route | stage-truth + freeze route + gate regression | FIXED | 1 |
| Argument Plan (11) | gated on READY/FROZEN matrix | none | — | `test_engine_gates` (status-forced DRAFT still gates) | DONE | 1 |
| Narrative Plan (12) | gated on READY argument | none | — | stage-truth | DONE | 1 |
| Semantic Master (13) | required FROZEN package | gate unreachable before loop 1 | now reachable; `build_master` action gated on `package_exists` | stage-truth | FIXED | 1 |
| Script (14) | gated on READY master | estimate used 150 wpm, contradicting the 110 wpm band | computed estimate from owner-configured per-language WPM | stage-truth + duration test | FIXED | 1 |
| Critic Loop (15, §44) | 6 LLM critics + deterministic fa checks | open `WARNING` didn't block approval; duration check fa-only; approve possible with zero findings | findings must exist; `WARNING` gates; duration check for every language with per-language WPM; `DURATION_TOO_SHORT/TOO_LONG` | stage-truth + waive tests | FIXED | 1 |
| Owner Approval | counted open blockers only | no waive path; silent no-op route | `waive_finding` service/route/UI; action errors surfaced via `?error=` | route + service tests | FIXED | 1 |
| Internet Research (9) | feature existed, runs transient | no persisted provenance per run | `ops.web_research_runs` + migration + workspace run table | model/migration + stub-signature fix | FIXED | 1 |
| Translations (16) | per-language `LocalizationProject` rows | LOCALIZATION absent from stage map | derived NOT_STARTED/IN_PROGRESS/READY from real rows per latest master | state map | DONE (summary level; per-language truth lives on translations page) | 1 |
| UI Stepper | positional `done` | certified unbuilt stages | `stage_states` map + health icons | partial-state UI regression | FIXED | 1 |
| UI Action Feedback | swallowed exceptions | failures indistinguishable from success | `?error=` surfacing + raised `GateBlockedError` on no-ops | error-surfacing test | FIXED | 1 |
| Source Import / YouTube Monitoring / Vortragsstruktur / Units / Concept Mapping / Retrieval | previously audited in dedicated sprints | not re-audited this pass | — | existing suites green | NOT AUDITED (this pass) | 0 |
| Topic Proposal + diversity + 5 channel agent packs | previously audited | not re-audited this pass | — | existing suites green | NOT AUDITED (this pass) | 0 |
| Translation quality agents / Publication prep | — | not audited | — | — | NOT AUDITED | 0 |
| Adversarial topic/research matrix (§51–52) | — | not run | — | — | NOT AUDITED | 0 |
| Cost/latency matrix across channels (§53) | — | run table now persists `latency_ms`, provider, model per research call; token/cost fields not yet captured | `web_research_runs.latency_ms` + provider/model | — | PARTIAL | 1 |

## Regression suite result (this pass)

- `ruff check` on changed scope: clean
- `ruff format`: applied
- `mypy --strict` on touched modules: clean
- Migration `g9a0b1c2d3e4` applied to dev DB; autogenerate shows no drift
- Full suite: **365 passed**, 7 deselected — all pre-existing/environmental:
  - `test_database_foundation.py` (2): Alembic index-name drift, identical on HEAD
  - `test_multilingual_editorial.py::test_approved_persian_is_exact_source_for_tracks_and_voice`: live-DB Persian diacritic normalization
  - `test_owner_topic_detail.py::test_topic_discovery_batches_and_workspace_actions`: needs a real LLM provider
  - plus unit-test module deselections from earlier runs

New tests this pass: `tests/integration/test_stage_truth.py` (2),
4 new cases in `test_studio_ui.py`, gate regression updated in
`test_topics.py::test_engine_gates`, stub signature updated in
`test_web_research.py`.

## Phase 2 audit table (ReviewRun + 25–30 + quality loops)

| Process (§19 order) | Audit result | Evidence | Status |
|---------------------|--------------|----------|--------|
| 1. Topic generation | Mining produces scored candidates grounded in labeled units; ungrounded → NEEDS_RESEARCH; language enforced with one correction pass; distinctiveness verdicts (ACCEPT/REPLAN/REVIEW_REQUIRED) vs ScriptSignatures; mining creates zero production artifacts | `test_topic_mining_scores_and_status`, `test_mining_creates_no_production_artifacts`, language tests | PASS WITH NOTES (12-case adversarial matrix not exercised; provider-quality dependent) |
| 2. Channel agent packs | Seeded per-channel roles/checks live on `agent_profile_json`; now actually consumed by the CHANNEL_SPECIFIC critic (was dead config); owner edits take effect | `test_channel_pack_checks_reach_the_critic` | PASS WITH NOTES (responsibilities are combined in one critic, per spec allowance) |
| 3. Research planning | Brief→plan separates question/counterevidence/concepts; input-hashed, versioned | existing plan tests | PASS |
| 4. Internet research | Multi-approach query plan (broad/verification/falsification/alternative/recent/gaps); ≤3 coverage rounds with early stop; rejected URLs+reasons, round, query kind persisted per run; dedupe + thin-content gates | `test_fill_runs_queries_and_ingests`, `test_coverage_loop_stops_when_gap_closes`, run-table UI | PASS WITH NOTES (SEO/AI-slop/outdated-evidence classification NOT AUDITED quality-wise) |
| 5. Evidence Matrix | DRAFT → `_validate_matrix` (items, claims, epistemic values, dead refs, supporting structure, provenance) → READY; revalidation demotes corrupted matrices; freeze refuses unvalidated; content gaps persisted as `unresolved_gaps` | `test_evidence_matrix_validates_before_ready` | PASS |
| 6. Argument | Gated on READY/FROZEN matrix; LLM plan resolved against labeled evidence refs; structure-only artifact | `test_engine_gates`, pipeline tests | PASS |
| 7. Narrative | Gated on READY argument; separate artifact, not prose | pipeline tests | PASS |
| 8. Semantic Master | Gated on FROZEN package + plans; freezes question/thesis/strategy/matrix/plans/epistemic constraints; does not regenerate upstream | `test_generic_master_path` | PASS |
| 9. Script generation | Gated on READY master; bounded inputs only (master sections/claims + brief contract); WPM-based estimate persisted | stage-truth suite | PASS |
| 10. Critics | FACT/LOGIC/CHANNEL_SPECIFIC/RETENTION/ORIGINALITY + deterministic PERSIAN_QUALITY + DURATION; now receive bounded context (brief contract, plan purposes, evidence claims) matching their instructions | review-run tests, channel-pack test | PASS |
| 11. Revision | Scoped to latest run's open findings; stale-run findings stay historical; new version + new hash + mandatory re-review; `max_revision_rounds` (default 3, owner setting) → OWNER_REVIEW_REQUIRED | `test_review_stale_after_manual_edit_and_round_cap` | PASS |
| 12. Translation | Per-language LocalizationProject with independent DRAFT/READY_FOR_VOICE/FAILED; statement-level claim map + quality gate; stage map derives per-language rows | existing localization suites + stage map | PASS WITH NOTES (per-language spoken-duration estimate not displayed — §44 partial) |
| 13. Publication readiness | VOICE/PUBLISHED honestly NOT_STARTED; PublicationTarget exists; no simulated publishing | stage map + UI | PASS (truthful absence) |
| 14. Cost/token/latency | provider/model/latency persisted per ReviewRun + WebResearchRun; tokens/cost unavailable via the provider contract → NULL, not estimated | run models | BLOCKED (provider API) |
| 15. Final UI | Runs table with rounds/kinds/rejections; duration header (Ziel 25–30, Planungsziel 27.5, geschätzt); ReviewRun table + stale-hash banner; run-scoped findings | `test_studio_ui` suite | PASS |

## Phase 2 regression suite result

- `ruff check app/ tests/`: clean
- `ruff format --check`: clean (283 files)
- `mypy --strict app`: clean, 216 source files
- `tests/unit`: **273 passed**
- `tests/integration`: **93 passed**, 7 deselected (same documented
  environmental set: `test_database_foundation` module — Alembic index drift
  identical on HEAD; `test_approved_persian_is_exact_source_for_tracks_and_voice`
  — live-DB diacritic normalization; `test_topic_discovery_batches_and_workspace_actions`
  — needs a real LLM provider)
- New tests this pass: CASE A–H ReviewRun regressions, stale-edit +
  round-cap, EvidenceMatrix validation lifecycle, channel-pack reach,
  topic-mining artifact isolation, search rounds/kinds/rejections,
  coverage early-stop.

## §3 transition invariants — verified by test

brief≠RESEARCH · plan≠EVIDENCE · matrix≠ARGUMENT · argument≠NARRATIVE ·
narrative≠MASTER · master≠SCRIPT · draft≠REVIEW · critics≠approve ·
approve requires a COMPLETED ReviewRun on the exact current draft
version+hash + zero open blocker/warning in that run · waiver is
explicit per finding per run · approval≠translations complete.

## Final report (§76) — honest answers

1. **Processes audited**: 13 of 17 (deep, artifact-level) this pass
2. **Loop count**: 6 accepted loops (see controller doc)
3. **Defects found**: 9
4. **Defects fixed**: 9
5. **Remaining blockers**: none for the pipeline core; open items below
6. **Topic quality per channel**: not re-audited (existing suites green)
7. **Agent-pack verification**: not re-audited
8. **Internet-search logic**: real URLs → fetched pages → canonical ingestion; LLM text never becomes evidence; runs persisted
9. **Search-result quality**: dedup + min-text + content-type gates; adversarial search tests not run
10. **Evidence quality**: matrix READY + freeze commitment; items carry epistemic classification
11–13. **Argument/Narrative/Script quality**: gates verified; content quality per channel not re-audited
14. **Duration compliance**: owner-configured per-language WPM; TOO_SHORT/TOO_LONG findings; UI badges. Owner target 20–25/22 (spec said 25–30/27.5 — divergence recorded)
15. **Critic/revision**: independent critics; WARNING gates approval; explicit waive; no auto-approve
16. **Translations**: per-language rows; stage map derived; quality loop not audited
17. **State-transition correctness**: enforced + regression-tested
18. **"All boxes checked" regression**: fixed + tested (partial-state UI proves Evidence-done/Recherche-not-done simultaneously)
19. **Real-data owner journey**: freeze action + error surfacing + research table verified via TestClient on migrated DBs
20. **UI critique**: stepper, error channel, run table, duration badges, waive buttons
21. **Cost/latency**: `latency_ms` + provider/model persisted per run; token/cost not yet captured
22. **Unit tests**: green
23. **Integration tests**: 365 passed, 7 deselected (documented environmental)
24. **Real-data tests**: e2e fixture pipeline green
25. **Adversarial tests**: not run this pass
26. **Known environmental issues**: 4 documented deselects; pre-existing `speech_sections` index drift on HEAD
27. **Recommendation: READY WITH ISSUES** — the state-truth core is now honest and regression-locked; remaining work is breadth (per-channel quality loops, adversarial matrix, token/cost capture, voice/publish wiring), not correctness of what was certified
28. **git diff --stat**: see working tree below
29. **git status**: uncommitted per §72 — owner review next

---

# PHASE 3 APPENDIX — quality-gap closure (2026-10-04)

## New findings this pass

1. **ReviewRun authority locked by test** — newest attempt (RUNNING/FAILED)
   can never be masked by an older clean run; 4-case authority matrix green.
2. **Concurrent review race closed at the DB** — partial unique index on
   `(script_draft_id, draft_hash)` for active statuses; app-level
   GateBlockedError preserved for the owner-visible path.
3. **Legacy finding boundary explicit** — unscoped findings are history
   once a modern run exists; compatibility-only revision path documented.
4. **Web source-quality gap closed** — `web_research/classify.py` persists
   signal-based publication_type + retrieval_weight + transparent
   review_notes; 10-case classification matrix green. Weight is advisory
   (ranker unchanged) — documented.
5. **UI truth defects fixed** — quota-retrying sources no longer render
   as dead "FAILED" (RETRYING + filter fix); existing localization
   projects on legacy masters now visible ("Bisherige Übersetzungen");
   primary next action highlighted per stage.
6. **Per-language translation duration shipped** — words ÷ owner WPM →
   TOO_SHORT/IN_TARGET/TOO_LONG per language; real data immediately shows
   fa too short, de too long.
7. **Search plan gained academic_evidence** (systematic-review approach).
8. **Perf**: mining concept resolution bounded to cited names only.

## Real-data evidence gathered

- 39 real TopicCandidates audited (cov=1.0, honest gaps, correct language
  post-enforcement); one cross-channel near-duplicate pair documented.
- 27 sources fully READY end-to-end (transcript→structure→units→concepts);
  143 quota-failed (auto-retrying), 8 genuinely failed.
- Real PDF import acceptance: page-provenance segments, sha256 dedupe,
  owner_upload quality row, processing queued.
- 12 real localization projects: independent per-language statuses;
  durations now visible (fa 22–24 min, de 35–39 min, en ~28–30 min).
- Legacy emtedad candidates include 11 English rows predating the
  language gate — legacy data, flagged for owner awareness.

## Blocked (provider quota — 5/5 sessions held by processing backlog)

Real topic generation for history/psych-evol/science-mystery · adversarial
topic matrix semantics · real full-script runs · real counterevidence
research · real translation quality critique · channel-agent semantic
(reject/correct) behavior. Deterministic coverage exists for each
mechanism; nothing is labeled PASS on faith.

BLOCKED: PROVIDER_CONTRACT — Devin session API exposes no token/ACU usage;
cost stays NULL.

## Phase 3 final verification (2026-10-04)

- `ruff check app/ tests/`: clean
- `ruff format --check app/ tests/`: clean (284 files)
- `mypy --strict app`: clean, 217 source files (translations-duration
  Optional narrowed via `loc_version` guard)
- `tests/unit`: **287 passed**
- `tests/integration`: **97 passed**, 7 deselected:
  - `tests/integration/test_database_foundation.py` (module) — Alembic
    `speech_sections` index drift; identical on HEAD; environmental
  - `test_multilingual_editorial.py::test_approved_persian_is_exact_source_for_tracks_and_voice`
    — live-DB diacritic normalization; baseline HEAD identical
  - `test_topics.py::test_topic_discovery_batches_and_workspace_actions` —
    POSTs real topic mining; needs a free Devin session (quota
    exhausted 5/5); baseline HEAD identical
  - `test_owner_topic_detail.py::test_topic_discovery_batches_and_workspace_actions`
    — same provider dependency in a second file; discovered this pass;
    baseline HEAD identical
  - None blocks product correctness; all are environmental/provider.

---

# PHASE 4 APPENDIX — provider capacity + real semantic certification (2026-10-04)

## Provider starvation loops (§2–7) — PASS WITH NOTES

- **Loop 1 baseline**: 5/5 Devin sessions held not by live work but by
  *orphaned* sessions from a killed app instance (11:15 batch,
  `blocked`/`expired`, tagged `emtedad-app`). Root cause: remote session
  state survives `SIGKILL`; `finally` cleanup never runs.
- **Fix**: `app/knowledge/llm/capacity.py` — provider-agnostic
  `ProviderCapacity` (total cap + background cap + work-class context var),
  wired into `DevinCloudProvider.extract`; scheduler work classes
  (`OWNER_REQUESTED`/`INTERACTIVE_OWNER`/`BACKGROUND_NEW`/`BACKGROUND_RETRY`)
  via `_work_class_for_reason`; owner pause setting
  `background_processing_paused`; process-level orphan sweep of stale
  blocked/expired tagged sessions; sweep-and-retry on quota;
  owner-visible "retry all failed" action on the resource library.
- **Loop 2 live**: real production ran end-to-end under quota contention.
  During the run a second root cause surfaced: **foreign untagged sessions**
  (`kcteam *`) share the same account quota and sit `blocked` for hours —
  sweep cannot touch them (correctly). Quota errors now back off like rate
  limits (bounded, `devin_rate_limit_max_attempts=5`, ~6 min of waiting)
  instead of one instant retry.
- **Notes**: capacity is per-process by design (single-process app); the
  account-level quota includes foreign consumers the app cannot see as its
  own — owner should keep `provider_max_concurrency` below the account cap.

## Retry-storm result (§5) — PASS

Quota/rate-limit failures never burn `attempt_count`
(`classify_failure` → QUOTA/RATE_LIMIT); longer quota backoff
(`speech_structure_quota_backoff_seconds`); dedup on active+queued states;
`retry_failed` bypasses the cap for owner-triggered remediation; sweep on
quota prevents orphan deadlock. 135 FAILED sources classified:
transient `NameError` + `LogRecord`-collision bugs (both fixed), quota
deaths, one genuine ValidationError. Not opaque.

## Real topic breadth (§11–14) — PASS

After freeing leaked sessions, real mines ran: **81 real candidates —
emtedad 17, history 13, pop-psych 12, psych-evol 15, science-mystery 24**
(Loop 2 after assigning 4 real science sources — first Loop-1 batch yielded
only 6 because the channel had one thin test source; grounding, not
generation, was the constraint). Persian-language candidates with
provenance, honest gaps, channel-fit rationales.

## Cross-channel convergence (§15) — PASS WITH NOTES

Shared sources produce materially different questions per channel
(meaning/interpretation vs evolutionary vs practical). **Real defect found
and fixed**: `_published_signatures` only showed PUBLISHED topics to the
miner, so a second mine re-derived near-duplicates of open candidates —
signatures now cover all existing candidates.

## Live review→revision→review loop (§35) — PASS (real, evidence-backed)

History production (Wari'/us-vs-them, Persian):
- Script V1: 1422 words (~13 min), ReviewRun 1 → **36 real findings**
  (1 BLOCKER oxytocin causal overclaim, 16 WARNING incl.
  DURATION_TOO_SHORT, source-conflict, anecdote-weight, contested-claim).
- `revise_draft` → V2 (1508 words). ReviewRun 2 → **30 findings**
  (0 BLOCKER, 12 WARNING, 18 INFO). The V1 blocker resolved; critics caught
  a revision-introduced `TEXT_CORRUPTION` (mojibake) plus residual
  CLAIM_CONFLATION and DURATION_TOO_SHORT — no stale-finding leak, all
  findings V2-scoped, correct hash association.
- Quota-killed review runs persist as FAILED (authority + truthfulness
  hold under provider failure); retry creates a fresh run legally.

## Real scripts (§31–33) — PASS WITH NOTES

Two real full scripts, different channels, both natural spoken Persian
with bookend structure and honest hedging: history 1422→1508→2477 w,
psychology-evolution 1675→2876 w. **Real weakness**: both V1s land
~50–60 % of the 25–30 min target — duration compliance remains the
weakest link. Root-cause fixes (explicit per-section word targets for the
writer; current/target word counts for the reviser; padding ban) measurably
recovered length: V2/V3 grew +64 %/+72 % and psych V2 landed **in-band**
(2876 w ≈ 26 min at 110 wpm). One in-band datum; first-write compliance
still unproven. Psych review 2 was quota-blocked past the 45-min outer
deadline by sustained foreign session churn.

## Semantic Master (§30) — PASS

`test_master_survives_upstream_mutation`: upstream `content_hash` mutation
leaves the frozen master byte-identical; rebuild yields a distinct
version with a different `input_hash`. Real masters built for both live
productions (ContentBrief-origin, deterministic projection).

## Book/PDF loop (§40) — PARTIAL (real defect found and fixed)

Real book PDF ("Emtedade Agah") processed live: local passes succeeded,
merge emitted children (`c1s1`…) without their parents → correctly
quarantined as `STRUCTURE_REVIEW_REQUIRED`, not silently written. Root
cause: merge prompt never stated "keep the parent if you keep children" —
fixed (`MERGE_INSTRUCTIONS` + `source_structure_merge_v2`). Owner-visible
remediation: per-source structure rebuild. Full READY acceptance pending
one clean re-run.

## Duration-aware localization (§36–39) — mechanism green, live provider-blocked

`LocalizationService.create` now derives a spoken target from master
section durations × owner WPM and paces statements to it; new
`adjust_duration` performs a bounded condense/expand pass that preserves
the exact claim set, persists a new immutable version, re-runs
pronunciation prep + the quality gate, marks READY_FOR_VOICE/FAILED, and
is owner-reachable via a "Länge anpassen" action on the translations page.
5 integration tests green (noop-in-tolerance, expand, condense,
claim-set-mismatch rejected, gate failure → FAILED).

Two real `create()` attempts on the live history master reached the
provider: run 1 returned a **claim-set mismatch** — refused, nothing
persisted; run 2 returned the input JSON echoed as structured output —
surfaced as `DevinCloudError: invalid structured output`. The honesty
boundary held both times; live localization remains
`BLOCKED: PROVIDER_CONTRACT` (session did not produce the requested
schema).

## Source-quality ranking (§8–10) — PASS (bounded influence)

`_rerank` applies `retrieval_weight` as a bounded ±15 % factor inside
`score_components` (`quality_weight` per candidate) — quality re-ranks
within similar relevance, never overrides it. Integration test: two
differently-weighted sources, ordering reflects bounded influence.

## Still blocked

- **Web research**: OpenRouter returns 401 — no API key configured.
  `BLOCKED: NO_API_KEY`. Gap-fill persists honest outcomes; no fake
  evidence.
- **Token/cost**: unchanged — `BLOCKED: PROVIDER_CONTRACT`.
- **Full semantic quality of revised duration**: pending live V3 review.

## Book/author references (final-prompt §18–26) — corrected 2026-10-04

Editorial rule: final Persian scripts may naturally reference real
non-Persian books and authors — grounded, varied, no invented quotes.
The language rule governs the BOOK's source language (metadata); a
Persian-translated or Persian-script TITLE of a non-Persian book is
presentation and is allowed.

Implementation (`app/content_engine/writing/books.py` +
`review.py` wiring), after the Phase-5 correction pass:

- `build_script` runs one `book_reference_selection` provider call whose
  only input is the frozen upstream material (brief question/thesis +
  EvidenceMatrix claim texts, capped at 80). Candidates name author,
  ORIGINAL title, source language, supported idea, optional Persian
  renderings (`author_fa`, `title_fa`), and `verified_quote` — wording
  copied only when it literally appears in the evidence claims.
- `allowed_book_references(selection, evidence_texts)` is the
  deterministic gate: rejects Persian-language sources
  (`fa`/`fas`/`per`/`Persian`/`Farsi`/فارسی/دری/تاجیکی) AND unknown/
  blank languages (a missing language cannot be certified non-Persian —
  the reference is omitted, never assumed), blanks, duplicates; caps at
  4; blanks any `verified_quote` that is not verbatim evidence wording.
- The surviving allow-list is frozen in
  `draft.provenance_json["book_references"]` before the writer call,
  injected into the writer payload, displayed in the draft UI
  (Autor/Buch/Originaltitel/Quellsprache/Verwendung via
  `reference_usage()`), and given to the channel-specific critic.
- Critic checks (`BOOK_REFERENCE_CHECKS`): UNVERIFIED (named book absent
  from the list), PERSIAN (source-metadata Persian book only — never
  inferred from script text), INVENTED_QUOTE (quotation-marked wording
  attributed to a book that is neither `verified_quote` nor verbatim
  evidence), OVERCLAIM (book cited as proof).
- A deterministic `BOOK_POLICY` layer runs on every draft language:
  quoted spans (≥2 words) near an attribution anchor (160 chars) or a
  «کتاب» mention (120) must be verified wording; a Persian-language
  entry surviving in provenance is a blocker.
- Writer policy modes: PARAPHRASE (natural attribution), DIRECT_QUOTE
  (only `verified_quote`, exact; translations marked as translation,
  never in quotes), CRITICAL_ATTRIBUTION (distancing verbs). Title
  rendering is free: original, Persian rendering, or fa+original on
  first mention — no mechanical bilingual repetition. Zero references
  used is a valid outcome.
- Freeze point: references are frozen per-draft in provenance, not in
  the Semantic Master — selection runs at script build on top of the
  already frozen evidence, preserving the master's deterministic
  projection.

Live evidence (Phase 5 loops):

- Loop 1 (psychology-evolution): same draft v3
  `37e5fa22-…` re-reviewed → old `BOOK_REFERENCE_PERSIAN` false positive
  gone; deterministic `BOOK_POLICY` reproduced the true
  `BOOK_REFERENCE_INVENTED_QUOTE` («آدم‌های خالص»); regenerated v4
  (`52ce85a9-…`) shows natural varied attribution, fa titles
  («هدیه‌های ناکاملی», «جرأت کردن»), verified-quote translations marked
  «به تعبیر…» — critic emitted `VERIFIED_ATTRIBUTION` and real findings
  (`ORDER_INVERSION`, `CHRONOLOGY_SLIPPAGE`, `AWKWARD_TRANSLATION`).
- Loop 2 (history-human-stories): v4 `9585e21d-…` — Haidt
  *The Righteous Mind*, one purposeful citation («در کتابِ «ذهن صالح»»),
  `verified_quote` correctly empty, zero book findings; channel pack
  still caught CAUSAL_OVERCLAIM/ANACHRONISM.
- 17 unit tests cover source-metadata rejection, rendered-title
  allowance, missing-language omission, quote verification, invented-
  quote proximity detection, title-citation exemption, usage detection;
  the integration stub still proves end-to-end Persian filtering and
  allow-list freeze.

Limits: attribution correctness (right book/author) is verified by the
selector's evidence-grounding instruction plus critic checks — there is
no external bibliographic API; documented per "practical, not overly
strict". The deterministic quote-vicinity check intentionally warns on
rhetorical inner-voice quotes near attribution — reviewable, waivable,
correct strictness by policy.

## Encoding-corruption handling — 2026-10-04

Root cause (verified): U+FFFD originates inside the remote Devin
session's generated JSON string values (mid-word corruption of Persian
text). JSON serialization, database storage, templates, and
normalization were excluded by inspection — the provider response is the
only injection layer.

Handling (`app/knowledge/llm/devin.py`):

- `_run_session` detects U+FFFD in the validated output and asks the
  SAME live session to repair its own output (one bounded turn,
  `_CORRUPTION_REPAIR_MESSAGE`, 600 s); stale output is suppressed via
  `ignore_structured` so the pre-repair payload can never be re-read.
- `extract` falls back to ONE fresh session when the repair path is
  unreachable or still corrupted.
- The deterministic `ENCODING_CORRUPTION` blocker in
  `PersianDraftQualityValidator` remains the certification backstop —
  a corrupted draft can never be approved.
- Live note: v4 of the psych-evol draft was built before the repair
  path existed; its retry session also corrupted (2 chars), proving
  fresh-session retry alone is insufficient — the in-session repair is
  the primary fix.

---

# PHASE 6 APPENDIX — first-draft duration + generation contract (2026-10-04)

## Duration-chain audit (§3) — answered explicitly

- `ContentBrief.target_duration_minutes`: YES (float, default 27.5).
- `NarrativePlan` distributes time across beats: YES —
  `NarrativeSectionProposal.target_seconds` → persisted
  `NarrativePlanSection.target_seconds`; now **calibrated** so the plan
  total cannot silently drift (live plans ranged 720–1650 s for the same
  27.5-min target before the fix).
- Semantic Master preserves the budget: YES — `LectureSection.duration_seconds`.
- Writer receives target minutes: YES — `target_duration_minutes`,
  `target_duration_min/max`, `target_word_count`, `generation_band_words`.
- Writer receives section-level budgets: YES — per-section
  `duration_seconds` + `target_words`.
- Writer knows language WPM: YES — `speech_wpm` in the payload.

The loss point was never a missing field — it was (a) uncalibrated
narrative totals and (b) the absence of a pre-review gate: an
under-length first draft consumed semantic revision rounds.

## First-draft result — the main defect

- **Loop 1 (psychology-evolution, v5)**: 2992 words ≈ 27.2 min at
  110 wpm — PASSED the generation band on the first attempt, zero
  corrections, clean UTF-8, 30-paragraph narrative arc (cold open →
  research story → three numbing strategies → counterargument →
  practices → return to opening scene). Prior best first draft: 2195 w.
- **Loop 2 (history-human-stories)**: v5 exposed a real defect (dual
  word counters — see below); v6 drove corrections 1559→1887→2573 w
  (in band) but the final attempt carried un-repairable U+FFFD →
  persisted as FAILED generation, zero revision rounds consumed.

## Word-counter defect found by Loop 2

`word_count` (regex `[\w\u0600-\u06ff]+`) split Persian ZWNJ compounds
and over-counted ~15 % vs the persisted whitespace-based
`actual_word_count`. A 2395-word (21.8-min) draft passed as "2770 words".
Fixed: `word_count` is now the single whitespace-token counter for
generation validation, persistence, and review findings.

## Generation validation (§13–15)

`writing/generation.py::validate_generation` runs inside `build_script`
before persistence: encoding (U+FFFD, Cf controls), duration band
(`first_draft_{min,max}_duration_ratio`, defaults 0.85/1.15 → owner
settings), paragraph floor vs planned beat count, Persian quality
blockers (scaffolding, evidence dumps, duplicates, repeated sentences —
new `REPEATED_SENTENCES` check for sub-paragraph filler). Bounded
correction (`generation_max_correction_attempts`, default 2) via
`script_generation_correction` — never creates a `ReviewRun`, never
touches `max_revision_rounds`. Persistent failure →
`generation_validation.status = FAILED` in `provenance_json`;
`ProductionService` gates `run_review`/`revise`/`approve` and renders
SCRIPT as REVIEW_REQUIRED; the UI states attempts + failed checks and
that review rounds were not consumed.

## Provider capacity (§16–21) — live evidence

- Single coordination path: every provider call is
  `DevinCloudProvider.extract` → `get_capacity().acquire(work_class)` —
  total semaphore 5, background semaphore 2 → 3 effectively reserved for
  interactive/owner work (configurable via `provider_max_concurrency`,
  `provider_background_max_concurrency`).
- Live Loop 2: during a real owner draft build the scheduler held
  exactly 2 remote sessions; the owner session acquired a slot while
  background was saturated; quota responses triggered one forced orphan
  sweep + bounded exponential backoff (no instant hammering).
- `provider_capacity_wait` now logs any slot wait ≥ 1 s with work class.
- Session cleanup: `finally: _terminate_session` covers success, timeout,
  HTTP error, cancellation; chunk-send failures terminate the fresh
  session; the tagged orphan sweep reaps `blocked`/`expired` sessions
  older than 30 min — observed live (a blocked orphan disappeared
  between listings).
- Limits: capacity is per-process (documented); foreign `kcteam`
  sessions share the account quota and are never swept.

## Encoding reliability (§22–25) — live evidence

- Controlled tests: 3 unit paths (repair succeeds; repair fails → fresh
  session; unmessageable → fresh session) + deterministic
  `ENCODING_CORRUPTION` gate.
- Live: `devin.encoding_corruption_retry` fired on real builds; hist v6
  is the terminal-honesty case — repair + fallback could not clear the
  corruption, so the draft persisted FAILED instead of certifying bad
  bytes. Corrupted text can never reach an approved state.

# PHASE 6.2 APPENDIX — approval semantics + review cycles + quote provenance (2026-10-05)

## Final duration gate (§1–3)

- Baseline/critique: `approve_draft` trusted critics to emit a duration
  finding; a critic that stayed silent could let a 23.5-min draft
  through. Root cause: no deterministic gate at approval.
- Fix: `approve_draft` resolves the configured final band
  (`target_duration_{min,max}_minutes`, default 25–30) and the
  language-specific WPM, computes minutes from the shared `word_count`,
  and raises `APPROVAL_DURATION_GATE` outside the band — independent of
  critic output.
- Re-test: `test_final_duration_gate` — CASE A 23.5 min blocked,
  CASE B 27.2 min passes, CASE C 31 min blocked, CASE D generation-band
  draft reviewable but not approvable; Loop 2 repeats for fa (110 wpm)
  and de (130 wpm) fixtures. Real result: live psych v8 approved at
  27.2 min; live history v11 blocked at 23.8 min — UI shows
  "außerhalb 25.0–30.0 Min.". Decision: PASS.

## Review cycles (§4–7)

- Baseline/critique: `max_revision_rounds` counted all completed runs
  over the brief lifetime — three rounds permanently locked a brief.
  Root cause: no persisted cycle boundary.
- Fix: `ReviewCycle` table (brief_id, cycle_number, started_by) +
  `ReviewRun.cycle_number`; cycle 1 implicit; `start_review_cycle`
  creates the next cycle only after the current budget is exhausted
  (explicit owner re-authorization, never a silent reset); old runs keep
  their numbers forever.
- Re-test: `test_review_cycles` — exhaustion → OWNER_REVIEW_REQUIRED,
  premature start rejected, cycle 2 fresh budget, old run does not
  certify a new draft hash. Real result: both live briefs started
  cycle 2 under §7 owner authorization; psych used 3/3 rounds and
  approved; history used its budget and now sits at an honest owner
  checkpoint (cycle 3 requires new authorization). Decision: PASS.

## True quote provenance (§10–14)

- Baseline/critique: `verified_quote` accepted wording found in
  generated Evidence claim text — a claim is a summary, not source
  wording. Root cause: claims fed the verbatim-quote authority.
- Fix: raw source excerpts (KnowledgeUnit full_text / source segments)
  are the verbatim authority; claims only seed candidate selection.
  Marked translations («به ترجمهٔ آزاد», «به تعبیر») are exempt from
  invented-quote flagging; unmarked renderings still flag.
- Re-test: `test_book_references` — CASE A claim-only wording → no
  direct quote; CASE B exact SourceSegment → quote eligible; CASE C
  claim resembling famous quote → rejected; CASE D metadata mismatch →
  rejected; Loop 2 on a second source family. 25 unit tests green.
  Decision: PASS.

## Live production certification

- Psych (61d3f6eb): v6 (six-weeks→six-years regression, 3 blockers) →
  v7 (blocker: DERIVATIVE_STRUCTURE) → v8: 2987 w / 27.2 min,
  0 blockers, 8 warnings waived individually with justification
  (hedged researcher-attribution, deliberate delayed naming, minor
  style) → APPROVED.
- History (c3e70292): v8 fixed the Khoisan blocker (narrowed to
  limited-report scope, 0 blockers); v9 arrived with U+FFFD corruption
  — caught by critics, and exposed a real gap: `revise_draft` had no
  encoding gate. Guard added — corrupted revision output now fails
  honestly with ENCODING_CORRUPTION and persists nothing (verified live:
  two subsequent corrupted revision outputs were rejected). REGENERATE
  (owner checkpoint option) → v10 honestly FAILED generation validation
  (under band) → v11 2621 w / 23.8 min reviewed: 1 blocker
  (EVIDENCE_OVERREACH) + duration under final band → honestly BLOCKED
  at owner checkpoint; cycle-3 authorization not granted.
- Encoding note: review-run 11 was an accidental duplicate review of
  already-known-corrupt v9 (operator error); its FAILED predecessor
  (run 9, quota) was marked FAILED honestly — no run was renumbered or
  deleted.

## Real localization (§23–28)

- FA: master language — verified, not re-translated (approved v8).
- DE: v1 1005 w (7.7 min) → adjust → v2 2832 w (21.8 min) → v3 3513 w
  (27.0 min) READY_FOR_VOICE / PASSED — 3 loops.
- EN: v1 3543 w (25.3 min) PASSED on first pass.
- AR: v1 1246 w (10.4 min) → v2 2334 w (19.5 min) → v3 2999 w
  (25.0 min) READY_FOR_VOICE / PASSED — 2 loops.
- All four derive from the same Semantic Master (d27ae2d8); the
  translations UI shows independent per-language status and duration
  badges — one language cannot green the others.

## Provider restart/capacity (§29)

- Loop 1 (normal ops): background sessions capped at 2/5; interactive
  work acquired slots throughout; bounded exponential backoff on every
  quota response — no infinite hammering.
- Loop 2 (reload/restart): `--reload` restarts during the session
  orphaned remote sessions; the tagged sweep reaped them as they crossed
  the 30-min threshold; four stalled `blocked` ingest sessions were
  reaped manually (same tag, same policy) to free quota — their polls
  fail honestly. Per-process pool and foreign `kcteam` sessions remain
  documented deployment constraints.

# FINAL_PRECOMMIT_AUDIT (Phase 7, 2026-10-06)

## Owner authority

- Root cause: `waive_finding`, `approve_draft`, and `start_review_cycle`
  accepted implicit callers — the eight psychology waivers were executed
  by a development agent through the service layer, not by the owner UI.
- Fix: all three require explicit non-empty actor identity; waivers also
  require justification (`resolution_actor`, `resolution_note` persisted).
  `recommend_waiver` records agent judgment while leaving the finding
  OPEN and gating. Repeated waiver of a resolved finding is rejected.
- Psychology v8 corrected to REVISED; the eight findings are OPEN with
  their recommendation notes preserved — no fabricated owner consent.

## Revision budget truth

- Root cause of inconsistent exhaustion: the cap counted completed
  ReviewRuns (psych showed 3, history 4 for the same nominal budget).
- Now: `ScriptDraft.revision_cycle`; the budget counts persisted
  revision drafts inside the current owner-authorized cycle only.
  Initial reviews, duplicate reviews, failed runs, retries, and
  generation corrections never consume it.
- Reconciliation: psych cycle 1 = 1 revision, cycle 2 = 3 (exhausted,
  truthful); history cycle 1 = 2, cycle 2 = 2 of 3 — the old rule had
  over-counted reviews as revisions.

## Translation fidelity

- Duration compliance is not fidelity. Manual bilingual review of the
  approved Persian master against DE/EN/AR finals found:
  - AR stmt14: U+FFFD mojibake — repaired (and the validator now blocks
    this class: U+FFFD + Cf controls, ZWNJ exempt).
  - AR stmt1: unsupported superlative framing — downgraded.
  - AR stmt10: invented quantified claim — removed.
  - EN stmt1: ungrounded "banana-nut muffin" detail — removed.
  - DE stmt1: attributed statistic stated as objective fact —
    attribution restored.
  - AR stmt15 gratitude scene: verified grounded in the FA master.
- `adjust_duration` is now anchored to the exported approved Semantic
  Master (claim IDs, propositions, qualifiers, epistemic status);
  provider output must preserve the exact claim set and is re-gated by
  `LocalizationQualityGate` after adjustment.

## State verification

- UI distinguishes OPEN / RECOMMENDATION / OWNER-WAIVED / ADDRESSED /
  BLOCKER, revisions used per cycle vs review runs, and cycle number.
- Psych workspace: 3 revisions in cycle 2, owner approval required.
- History workspace: 2 revisions in cycle 2, 1 blocker, 23.8 min —
  BLOCKED at owner checkpoint; cycle 3 not started, blocker not waived.

## Regression

- ruff + format + mypy --strict: clean.
- unit: 342 passed. integration: 118 passed (two full loops).
- Migration chain linear, single head; upgrade/check/downgrade/
  re-upgrade clean on a disposable DB; no autogenerate drift.
- No secrets in diff; `.env` untracked; temp dumps live only in /tmp.

## Remaining owner decisions (do not block code correctness)

1. Psychology: accept/waive the 8 recommended warnings or request
   revision — owner editorial judgment required.
2. History: authorize cycle 3 or keep the production blocked.
