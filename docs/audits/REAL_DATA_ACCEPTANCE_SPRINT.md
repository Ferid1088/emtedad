# Real-Data Acceptance Sprint — Emtedad Studio

Architecture checkpoint: `83279aeab2f23ac86abaf1036e2fe7b77bad8e14`
(branch `fix-speech-structure-generation`, **not pushed**).
Sprint rule: fix only defects exposed by real usage; no architectural
changes; no commit until sprint review.

## 0. Environment

| Item | State |
|---|---|
| DB | `emtedad` dev DB: 165 sources, 165 versions, 231,656 segments, 5 channels, 5 ACTIVE strategies |
| YouTube ingestion | Local MCP server `127.0.0.1:8790` (YouTube MCP Server 4.0.10) — reachable |
| LLM provider | `devin-cloud` only; free-tier cap of 5 concurrent SWE-2 sessions |
| Embeddings | Local `multilingual-e5-small` — works |

## 1. Videos tested

| # | Source | Type | Duration | Segments | Final state |
|---|---|---|---|---|---|
| A | `0593d089` درسگفتار وسوسه \| بخش اول (دکتر مکری) | structured lecture | 1752 s | 530 | **READY** |
| B | `486867ba` چرا انسان می‌جنگد؟ (interview) | case-study-rich interview | 2955 s | 874 | **READY** |
| C | `91f42e55` بحثی درباره‌ی کتاب مغز ایدئولوژیک | long book discussion | 6836 s | 2151 | see §21 |
| D | `a09b3bd1` Brené Brown — The Power of Vulnerability (fresh import, `iCvmsMzlF7o`) | English TED talk, Persian subtitle track | 1250 s | 475 | **READY** |

Three sources completed the full canonical pipeline on real data
(A, B, D); C is covered in §21.

## 2. Import results

- Existing A/B/C imports revalidated: canonical URLs valid, SourceVersion +
  content/transcript hashes present, segments strictly ordered 1..N,
  zero timestamp anomalies, zero gaps.
- **Fresh import D** exercised the full adapter→import→version→segments
  path end-to-end via the local YouTube MCP. Metadata correct;
  `language='fa'` is accurate — the MCP returned the official Persian
  subtitle track (human-translated TED subtitles; translator credit
  appears in segment 1).
- No import-path defects found.

## 3. Structure metrics

| Video | Segs | Nodes | Roots | Max depth | Coverage (leaf spans) | Sibling overlaps |
|---|---|---|---|---|---|---|
| A | 530 | 40 | 4 | 3 | 498/530 (94%) | 2 shared-boundary segments |
| B | 874 | 68 | 18 | 3 | 873/874 (~100%) | 1 shared-boundary segment |
| D | 475 | 46 | 9 | 4 | 454/475 (96%) | 1 shared-boundary segment |

Node-type spread (B): TOPIC, QUESTION, ANSWER, EXPLANATION, ARGUMENT,
EXAMPLE, CASE_STUDY, EXPERIMENT, COUNTERARGUMENT, CONCLUSION.
(A): TOPIC, SUBTOPIC, DEFINITION, EXPLANATION, ARGUMENT, STORY,
CASE_STUDY, QUESTION, COUNTERARGUMENT, CONCLUSION, OTHER.
(D): TOPIC, STORY×9, ARGUMENT×10, EXPLANATION×9, EXAMPLE, DEFINITION,
CONCLUSION×3.

## 4. Structure quality findings

Manual inspection (≥10 nodes/video):

- **A (lecture):** clean TOPIC→SUBTOPIC/EXPLANATION nesting; transitions
  land at real topic shifts (intro → research history → definition/
  measurement). The Tantalus myth is a single coherent STORY node;
  Jellinek/modern-medicine a separate EXPLANATION — correct.
- **B (interview):** TOPIC→QUESTION→ANSWER nesting mirrors the
  interviewer/guest turns; transitions occur at interviewer questions.
  Case studies (wari'/Khoe-san xenology, war statistics, Sapolsky's
  *Behave* baboon experiment) are self-contained nodes. One nit: mixed
  en/fa node titles; one shared boundary segment between the last two
  roots.
- **D (TED talk):** story-arc hierarchy — opening anecdote → research
  journey → key finding → wholehearted traits → resolution. 9 STORY
  nodes correspond to real anecdotes.
- Uncovered ranges are small (1–17 segs) and sit at transitions/greetings.
- All "overlaps" are single shared-boundary segments between adjacent
  siblings — acceptable transition tolerance, not duplicate coverage.

## 5. Story preservation findings

Gate: story beginning + development + resolution as one object.

- B: 3 `CASE_STUDY` units, all `atomic=True` — wari'/Khoe-san xenology
  (1214–1272 s), war-statistics study (1865–1939 s), Sapolsky baboon
  testosterone experiment (2659–2714 s).
- D: 8 `STORY` units, all `atomic=True`. Spot-check of the
  event-planner anecdote: full_text contains setup ("چند سال پیش، یک
  طراح مراسم با من تماس گرفت") through punchline ("محقق-داستان گو")
  verbatim — no split.
- A: Tantalus myth STORY node intact.
- **Mid-story retrieval probe:** querying `بازسازی تستوسترونی` (a detail
  inside the Sapolsky story) returned the complete atomic CASE_STUDY
  unit — not a fragment. Same for the wari' query.
- **PASS** — no false splits observed.

## 6. KnowledgeUnit results

| Video | Units | Atomic | Type distribution |
|---|---|---|---|
| A | 32 | 3 | EXPLANATION 12, DEFINITION 7, CLAIM 6, STORY 2, CASE_STUDY 1, EXAMPLE 1, COUNTERARGUMENT 1, OPEN_QUESTION 1, SYNTHESIS 1 |
| B | 61 | 3 | CLAIM ~20, EXPLANATION ~15, SYNTHESIS 4, OPEN_QUESTION 3, CASE_STUDY 3, EXAMPLE 2, EXPERIMENT 1, COUNTERARGUMENT 1 |
| D | 38 | 9 | CLAIM 11, EXPLANATION 10, STORY 8, SYNTHESIS 3, EXAMPLE 3, DEFINITION 2, CASE_STUDY 1 |

- `full_text` verified verbatim transcript text (heads/tails match
  segment boundaries); `content_hash` present; `summary` separate.
- Parent/child overlap: parent nodes that are unit-eligible produce
  units alongside their children (e.g. B's ARGUMENT 351–392 plus child
  CLAIMs). Duplicative coverage is tolerated by structure-aware
  expansion; noted, not a blocker.
- One large SYNTHESIS unit in B (seg 668–774, 3439 chars, 416 s) —
  a merged long answer; acceptable but coarse.
- Retry idempotency: retries dropped + rebuilt units under the same
  ExtractionRun — no duplicate units.

## 7. Retrieval results

10 queries run through `KnowledgeUnitSearchService`
(lexical + dense + concept lanes, PARENTS expansion):

- Exact, paraphrased, detail, causal, counterargument, and cross-language
  ("evolutionary origins of warfare") queries all returned relevant
  units with source title, timestamps, structure path, and expanded
  parent context.
- Story-middle query resolves to the full atomic unit (§5).
- `concept` lane scored 0.0 in all observed results — concepts lane not
  contributing (concept extraction produced few/none mapped concepts on
  this corpus). Not a crash; documented for follow-up.
- Queries for topics covered only by sources without units yet
  predictably returned cross-source noise before embeddings were
  rebuilt; after `UnitEmbeddingService.build()` (140 embeddings)
  results were source-appropriate.

## 8. Multi-channel assignment

- Source B assigned to `history-human-stories` (PRIMARY),
  `psychology-evolution` (PRIMARY), `emtedad` (SUPPORTING).
- Source A → `pop-psychology-relationships` PRIMARY, `emtedad` PRIMARY.
- Source D → `pop-psychology-relationships` PRIMARY, `emtedad` PRIMARY,
  `psychology-evolution` SUPPORTING.
- Verified: one Source, one SourceVersion, one unit set; multiple
  `EditorialChannelResource` rows; idempotent upsert. **PASS.**

## 9. Topic candidates

Real mining via Devin provider:

| Channel | Candidates | Example Video Question |
|---|---|---|
| emtedad | 11 | "When did humans actually start waging war — and why did it have to wait for cities?" (pattern/continuity framing) |
| pop-psychology-relationships | 10 | "وقتی درد، ترس یا شرم را بی‌حس می‌کنیم، چه اتفاقی برای شادی و شکرگزاری می‌افتد؟" (relatable everyday framing) |
| psychology-evolution | 7 | "اگر ظرفیت خشونت در ژن‌های ما باشد، چرا جنگِ سازمان‌یافته پدیده‌ای این‌قدر تازه است؟" (hypothesis + alternatives) |

- Scores per candidate: coverage 1.00 (grounded on candidate's claimed
  units), channel-fit 0.75–0.90, novelty 1.00 (first mining round),
  curiosity 0.60–0.85; supporting-unit links persisted
  (`TopicCandidateUnit`), provenance_json holds knowledge gaps +
  channel-fit reasoning.
- Status transition POST verified end-to-end (CANDIDATE→SHORTLISTED
  persisted via UI).
- Quality note: emtedad candidates came out in English while pop-psych/
  psych-evolution are Persian — inherits each strategy's language;
  flagged as editorial-review item, not a defect.

## 10. Cross-channel comparison

Same source (B's war interview) yielded genuinely different question
shapes:

- **Emtedad:** "why did war have to wait for cities" — pattern/
  continuity/meaning frame.
- **Psych & Evolution:** "if violence is in our genes, why is organized
  war so recent" — competing-hypotheses frame (Wrangham vs.
  institutional-late-arrival, biology vs. culture).
- **Pop Psych:** everyday recognizable problem + practical relevance
  (numbing, shame, blame, parenting).
- Not title-only variation — thesis + angle + evidence emphasis differ.
  **PASS.**

## 11. Selected production

Candidate `4c2a9e93` (psychology-evolution, total 0.92):
«اگر مغز ما برای اتصال و ارتباط ساخته شده، چرا در دنیای مدرن
آسیب‌پذیری را با بی‌حسی، قطعیت و کمال‌گرایی می‌کُنیم؟»

Chain: Brief `c98369ea` READY → ResearchPlan (v3) → EvidenceMatrix v3
FROZEN → ResearchPackage `fb198095` FROZEN → ArgumentPlan v2 READY →
NarrativePlan v2 READY → Generic Master `31bdbbbc` **READY,
origin_type=CONTENT_BRIEF** → ScriptDraft `fc62e56f` (fa, 1312 words,
~712 s vs. 12-min target).

## 12. ContentBrief review

Question/thesis non-synonymous (question = paradox, thesis = causal
claim "numbing is indiscriminate"); audience, angle, primary concepts,
required evidence roles, required counterargument ("is numbing ever
adaptive?"), target duration all persisted. **PASS.**

## 13. ResearchPackage review

FROZEN, origin CONTENT_BRIEF, `lesson_id`/`lesson_canon_hash` NULL,
content_hash present; snapshot pins selected units + evidence_matrix_id
(used by the master gate to reject stale pairings — see §19). **PASS.**

## 14. EvidenceMatrix review

15 items with roles (PRIMARY_EVIDENCE, SUPPORTING_EVIDENCE, EXAMPLE),
claim types, epistemic status, allowed/forbidden wording. Note: several
items carry `UNKNOWN/NONE` epistemic status inherited from unit
`evidence_level` — extractor rarely sets richer levels on this corpus;
wording fields still bound claims to unit summaries. **PASS with note.**

## 15. Argument review

9 sections with a real progression: HOOK (paradox) → CLAIM (thesis) →
3× EVIDENCE → EXAMPLE → COUNTERARGUMENT (the required concession) →
RESOLUTION → STORY close — each with purpose + transition intent. Not a
table of contents. **PASS.**

## 16. Narrative review

8 sections with audience-experience roles (COLD_OPEN, SETUP, TURN,
DEEPENING×2, TURN, CLIMAX, RESOLUTION), per-section emotional function
and target seconds (60–140 s). Structurally distinct from the argument
plan (different segmentation, tension beats). **PASS.**

## 17. Script review

Persian script reads naturally: audience-scene cold open → paradox →
thesis → research arc (Brown's "researcher-storyteller" story preserved
coherently) → counterargument concession → "I am enough" resolution →
open-question ending. No lesson vocabulary, no internal labels, no
ResearchPackage/SemanticMaster wording; channel voice
(hypothesis/mismatch framing) visible. **PASS.**

## 18. UI findings

Journey verified on running app (`uvicorn :8300`):

- `/studio` 200; `/lessons` + `/lessons/anything` → 303 `/studio`.
- Channel page, strategy, resources, production pages: 200 with real data.
- `/library` (94 KB, 165 sources), `/library/{id}` detail,
  `/structure`, `/units` pages: 200 with persisted counts.
- Topic status POST persists (verified in DB).
- Production page derives stage=SCRIPT from persisted artifacts; allowed
  actions map to persisted prerequisites (re-runs create new versions).
- **Defect found & fixed:** channel Topics page 500 —
  `DetachedInstanceError` on `TopicCandidateConcept.concept` (nested
  lazy load). Fixed via nested `selectinload`; page now 200 (22 KB real
  candidates). See §19.

## 19. Bugs fixed (real-usage defects only)

1. **Unit-metadata batch poisoning** — one invalid `unit_type` enum
   (`ARGUMENT`, a node type, not a unit type) failed the entire
   extraction batch → run FAILED. Fix: `UnitMetadataBatchRaw` wire
   schema + per-item validation in `extractor.py`; invalid items logged
   (`knowledge_units.invalid_proposal`) and dropped to deterministic
   `node_type` defaults. B dropped 19/80 items; A/D similar scale.
   (Also exposed: Devin frequently emits `ARGUMENT` as unit type —
   prompt-enum drift worth monitoring.)
2. **Structure batch poisoning** — one malformed/inverted/out-of-window
   node killed whole windows and merges. Fix: `SourceStructureOutputRaw`
   + per-node validation in `agent.py` (`_valid_nodes`); malformed,
   window-escaping, and inverted nodes logged and dropped; the existing
   coverage validator still judges the result (A initially landed in
   `STRUCTURE_REVIEW_REQUIRED` under strict code; READY under lenient).
3. **Stale FROZEN package selection** — `_frozen_package` ordered only
   by `package_version DESC`; each plan produces version 1, so a retry
   left two FROZEN packages and the gate could bind the stale one vs.
   the latest matrix (`GateBlockedError: ResearchPackage was frozen
   from a different EvidenceMatrix`). Fix: `created_at DESC` tiebreaker.
4. **Topics page 500** — nested `selectinload` for
   `TopicCandidateConcept.concept` (§18).
5. Test updates: `test_agent_drops_node_escaping_window` rewritten for
   single-window semantics; added
   `test_agent_drops_malformed_node_and_tolerates_extra_keys`.

Files touched: `app/knowledge/structure/{agent,schemas}.py`,
`app/knowledge/units/{extractor,schemas}.py`,
`app/lecture/generic_service.py`, `app/topics/service.py`,
`tests/unit/test_source_structure.py`. No migration, no architectural
change.

## 20. Remaining issues

- **Video C unfinished:** repeated `FAILED` on Devin free-tier
  5-session cap. Root cause: killed local pollers leave cloud sessions
  `running` server-side; provider only terminates sessions on success
  paths. Mitigated manually (DELETE orphaned sessions); C retry in
  progress at audit time. **Follow-up (not architecture):** provider
  should terminate sessions in `finally`/on process exit or on
  `DevinCloudError` failure paths; retry/backoff for 429 in the
  scheduler would self-heal.
- Devin often emits `ARGUMENT` for `unit_type` (invalid enum) — the
  lenient extractor absorbs it; consider tightening the prompt's enum
  list (observability, not a blocker).
- Evidence items often `UNKNOWN/NONE` epistemic status — extractor
  conservatism; acceptable but weakens matrix selectivity.
- Concept lane contributes ~nothing on this corpus (few mapped
  concepts); hybrid still works via lexical+dense.
- `ScriptSignature` table is read (distinctiveness, master
  architecture) but never written — nothing populates signatures until
  publication flow lands; distinctiveness currently vacuous.
- Emtedad mined candidates in English vs. Persian for other channels —
  strategy-language artifact; editorial decision needed.
- Shared boundary segments (siblings sharing one segment) — tolerated.
- Known baselines unchanged: `ix_speech_*` index drift, ZWNJ
  normalization, Devin quota behavior.

## 21. Tests

- `tests/unit`: **221 passed** (was 220 + 1 new structure test).
- Integration (`-k "topics or studio or generic or lesson_retirement"`):
  **17 passed**.
- `ruff check`/`format`/`mypy --strict` clean on all touched files.
- No commit made; working tree contains only the six modified files
  above + this audit.

---

# STABILIZATION SPRINT (follow-up)

Resolved the three remaining production-correctness / operational issues
without architectural changes.

## S1. ScriptSignature now written (was: never written)

- **Creation point:** `ScriptService.approve_draft()` — the authoritative
  owner-approval transition. The generic pipeline has no separate
  publication transaction; approval is the canonical boundary. Drafts,
  rejected drafts, and unapproved revisions produce no signature.
- **Derivation** (`app/topics/signature.py`): question/thesis/angle come
  verbatim from the `ContentBrief`; `argument_signature` is the
  deterministic role chain of `ArgumentPlan` sections
  (e.g. `HOOK→CLAIM→EVIDENCE→…→RESOLUTION→STORY`); `hook_type` /
  `ending_type` come from the first/last `NarrativePlanSection`
  opening/ending methods; `story_unit_ids` come from plan-section
  `story_unit_ids`, with a fallback restricted to STORY/CASE_STUDY-typed
  grounding units of the bound candidate; `concept_ids` from the
  candidate's mapped concepts; `content_hash` from the approved draft.
- **Idempotency:** `uq_script_signatures_draft` unique constraint on
  `script_draft_id` + deterministic lookup (`ensure_signature_for_draft`
  returns the existing row). Re-approval does not duplicate — verified on
  the real draft `fc62e56f` (one signature after two approve calls).
- **Real verification:** signature `2502cbe6` persisted for production
  `fc62e56f` on channel `psychology-evolution`; `story_unit_ids` is
  honestly `[]` (plans bound no story units, candidate grounding units
  are not story-typed). `DistinctivenessPlanner.assess()` on a related
  real candidate now returns `REPLAN` with topic overlap 0.68 — was
  previously vacuous `ACCEPT` on an empty table.
- **Migration:** `d2e3f4a5b6c7` adds `script_draft_id`,
  `editorial_project_id`, `content_hash` + the unique constraint
  (existing rows keep NULL `script_draft_id`).

## S2. Devin provider session lifecycle

- `extract()` now wraps polling in `try/finally` →
  `_terminate_session()` runs on every path out: success, validation
  failure, timeout, poll exception, cancellation, unexpected error.
- `_create_session()` cleans up the remote session when a follow-up
  message fails mid-creation (previously orphaned a live session).
- `_terminate_session()` is idempotent: DELETE failures are logged
  (`devin.session_cleanup_*`) and never mask the original exception.
- Typed errors: `DevinRateLimitError` (transient 429) vs
  `DevinQuotaError` (403 `out_of_quota`, or 429 with parallel-session
  cap text → `PROVIDER_QUOTA_EXHAUSTED`). Quota errors are never
  retried in-call.
- **Bounded 429 retry:** `_create_session_with_backoff()` retries
  transient rate limits with exponential backoff —
  `devin_rate_limit_max_attempts` (3), `…_initial_backoff_seconds` (20),
  `…_max_backoff_seconds` (120), all configurable in settings.
- Scheduler integration: `classify_failure` now maps
  `PROVIDER_QUOTA_EXHAUSTED` → `FailureClass.QUOTA` (long quota backoff,
  does not burn `attempt_count`), transient 429 → `RATE_LIMIT`.
- Mock-transport tests cover: cleanup on success / validation failure /
  terminal-state failure / timeout / mid-create message failure /
  cleanup-failure original-error preservation; bounded 429 retry
  (3 creates then `DevinRateLimitError`); parallel-cap → `DevinQuotaError`
  with a single create attempt.

## S3. Topic mining obeys channel editorial language

- `ChannelStrategyVersion.editorial_language` (String(8), default `fa`)
  added via migration `d2e3f4a5b6c7`. Independent of source language and
  publication target.
- `TopicMiner.propose(editorial_language=…)` adds an explicit prompt
  contract: title, video_question, tentative_thesis, angle,
  channel_fit_reason, knowledge_gaps entirely in the strategy language —
  "the channel's editorial language always wins".
- `TopicService.mine()` runs a lightweight script check on all six
  fields; on mismatch it performs exactly one correction pass
  (`language_correction=True` adds an explicit CORRECTION instruction);
  a still-wrong batch persists with
  `provenance_json.language_review_required=True` (warn-logged). Both
  flags and `editorial_language` are recorded in provenance.
- **Real verification:** fresh Emtedad mining pass → 5 candidates, all
  title/question/thesis/angle/rationale fully Persian,
  `editorial_language=fa`, `language_review_required=False` (no
  correction pass needed — the contract held on first attempt).

## S4. Video C (مغز ایدئولوژیک)

- Pre-fix run: `FAILED`, `attempt_count=4` — free-tier 5-session cap
  (orphaned sessions, see §20). Retried under the fixed provider in
  background; result pending at audit time. Not held open per sprint
  instructions — the typed-quota path now classifies a repeat failure
  as `QUOTA` (long backoff) instead of burning attempts.

## S5. Tests added

- `tests/unit/test_devin_provider.py`: +9 lifecycle/quota tests (25 total).
- `tests/unit/test_topic_language.py` (new): 13 tests — script check,
  all editorial fields, miner prompt contract, correction prompt.
- `tests/integration/test_script_signature.py` (new): full pipeline →
  approve → signature fields, idempotent re-approve, draft produces no
  signature, planner sees the signature (REVIEW_REQUIRED on a twin).
- `tests/integration/test_topics.py`: +3 tests — wrong-language →
  correction pass → Persian; persistent wrong language → review flag;
  EN strategy accepts English without retry.
- Totals: unit **243 passed**; affected integration (topics, signature,
  generic E2E, studio, source-structure, editorial-channels)
  **23 passed**; `ruff check`/`format` clean on all changed files;
  `mypy --strict app` clean (204 files).

## S6. Remaining quality backlog (unchanged, non-blocking)

Concept mapping coverage, oversized SYNTHESIS unit, parent/child
overlap tuning, invalid `unit_type=ARGUMENT` telemetry, `ix_speech_*`
drift, ZWNJ normalization, evidence `UNKNOWN` epistemic status.
