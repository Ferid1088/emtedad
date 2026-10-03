# Multichannel Program — Phases 8–20 Audit

Scope: dynamic topic engine, content brief, distinctiveness, generic
research/evidence, argument and narrative architects, generic script
pipeline, review critics, production workspace UI, resource library/detail
UI, and publication targets — per
`docs/EMTEDAD_CODING_AGENT_MASTER_IMPLEMENTATION_PROMPT.md` §8–§20.

## Implemented

### Phase 8 — Dynamic topic engine

- `app/topics/`: `TopicCandidate` (+ `TopicCandidateUnit`,
  `TopicCandidateConcept` typed association tables), `TopicMiner` (LLM
  proposals over labeled Knowledge Units — `u1..uN` — from
  channel-assigned resources only), deterministic scorer, Jaccard novelty
  against prior candidates' concept sets.
- Scoring weights come from `ChannelStrategyVersion.
  topic_scoring_policy_json.weights`; no global hard-coded weights.
- §8.8 gap rule: coverage below `coverage_threshold` (strategy policy,
  default 0.4) lands in `NEEDS_RESEARCH`, never `READY_FOR_PRODUCTION`.
- Status lifecycle with explicit allowed transitions.
- UI: `/studio/channels/{slug}/topics` — mine (with owner instruction),
  score grid, gaps, status transitions, "Create brief" action.

### Phase 9 — ContentBrief

- `app/briefs/`: `ContentBrief` model with all §9.1 fields, NOT NULL gate
  fields, `positive_target_duration` check, DRAFT→READY service flow with
  `validate_ready` §9.2 gate. Briefs pin channel + strategy version.

### Phase 10 — Distinctiveness

- `ScriptSignature` (shape only — question/thesis/angle/concept ids/story
  unit ids/argument signature/hook/ending; never stored prose).
- `DistinctivenessPlanner`: per-dimension Jaccard/term overlap,
  per-strategy thresholds (`topic_scoring_policy_json.distinctiveness`,
  defaults `accept_below=0.5`, `review_above=0.8`), returning
  ACCEPT/REPLAN/REVIEW_REQUIRED.

### Phase 11 — Generic research + EvidenceMatrix

- `ResearchPlan` and `ResearchPackage` gained a third origin:
  `content_brief_id`, with the origin XOR CHECK extended to
  `num_nonnulls(...) = 1` — legacy spine/lesson rows untouched.
- `EvidenceMatrix` (versioned, content-hashed) + `EvidenceMatrixItem`
  (claim text/type, epistemic status, supporting/counter/alternative unit
  ids, source quality, limitations, allowed/forbidden wording).
- `GenericResearchService`: brief-origin plans, matrix build from the
  topic's grounding units, and `freeze_package` producing a frozen
  brief-origin `ResearchPackage` (selected units, claims, roles,
  counterevidence, alternative explanations, source provenance, source
  quality, uncertainty, content hash).
- `EvidenceSelectionRole` extended with the missing §11.2 values
  (PRIMARY_EVIDENCE, SUPPORTING_EVIDENCE, CASE_STUDY,
  PHILOSOPHICAL_CONTEXT) via `ALTER TYPE ... ADD VALUE`.

### Phases 12/13 — Argument + Narrative architects

- `app/content_engine/`: `ArgumentPlan`/`ArgumentPlanSection` and
  `NarrativePlan`/`NarrativePlanSection` (versioned, content-hashed,
  provenance JSON). LLM output is strictly structured
  (`ArgumentPlanOutput`, `NarrativePlanOutput`); sections reference
  upstream artifacts by label (`e1`, `a1`, `s1`) resolved locally —
  no prose at either stage.
- Gates enforced in `ContentEngineService` (`GateBlockedError`):
  argument requires brief READY/LOCKED + matrix READY/FROZEN; narrative
  requires a READY argument.

### Phase 14 — Generic script pipeline

- `ScriptDraft` model with all §14.2 fields (`content_brief_id` +
  optional legacy `editorial_project_id`, language, version, variant,
  text, status, provenance, hashes, duration metrics).
- `ScriptService.build_script` gated on READY NarrativePlan; writer
  receives only brief + narrative section structure + style instruction —
  no lesson canon dependency (legacy `PersianDraft` path untouched).

### Phase 15 — Review pipeline

- Five critic roles (`CriticRole`) each run an independent structured
  call producing `ReviewFinding`s (location, code, severity, explanation,
  correction_constraint). Critics never rewrite.
- `revise_draft` produces a new `ScriptDraft` version via a
  `RevisionAgent` step; findings become ADDRESSED, old draft ARCHIVED.
- `approve_draft` is blocked while any OPEN BLOCKER finding exists.
- §16 channel review packs: `CHANNEL_REVIEW_CHECKS` per slug; only the
  selected channel's checks reach the CHANNEL_SPECIFIC critic.

### Phase 17 — Production workspace UI

- `app/production/service.py` `ProductionService.state_for_brief` derives
  the stage (BRIEF → … → APPROVED) purely from persisted artifacts and
  returns `allowed_actions` — buttons are backend-driven (§17.3).
- `GET /studio/production/{brief_id}` renders the stepper, current
  artifact, open blockers, and gated action buttons
  (`studio/brief_workspace.html`).
- `POST /studio/production/{brief_id}/actions/{action}` dispatches to the
  services; invalid/blocked actions redirect safely.
- `POST /studio/topics/{candidate_id}/brief` creates a brief from a
  candidate and enters the workspace.

### Phase 20 — Publication targets

- `PublicationTarget` (channel, platform, language, name, status) in
  `app/production/models.py` + `ProductionService.create_target` /
  `list_targets`. No auto-publish; owner approval stays mandatory.

## Not done / deferred

- Phase 21 (retire the 100-lesson path): its checklist (generic brief,
  research, master, script paths all proven + historical readability)
  is only partially met — Semantic Master path not yet generalized —
  and deletion needs an explicit owner decision. Left as next phase.
- §23 automatic processing: structure/unit extraction remain deliberate
  actions (no queue exists; spec permits synchronous flows).
- `/library` already covers Phase 18/19 (assign/unassign, inspect,
  re-run structure, rebuild units) from earlier phases.

## Evidence

- `ruff check`/`format` clean on all new modules.
- `mypy --strict` clean on `app/topics`, `app/briefs`,
  `app/content_engine`, `app/production`, `app/research`, studio routes.
- `pytest tests/unit` — 247 passed.
- Integration: `test_topics.py` (mining, scoring, NEEDS_RESEARCH gap
  rule, transitions, brief gate, evidence matrix, package freeze,
  argument/narrative gates, script gate, critic findings, approve block,
  revision) + `test_studio_ui.py` — all pass.
- Migrations `c0d1e2f3a4b5`, `d1e2f3a4b5c6`, `e2f3a4b5c6d7`,
  `f3a4b5c6d7e8`, `f4a5b6c7d8e9`, `a5b6c7d8e9f0`, `b6c7d8e9f0a1` applied
  cleanly on dev and disposable test databases.
