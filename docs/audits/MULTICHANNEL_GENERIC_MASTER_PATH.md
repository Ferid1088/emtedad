# Generic Semantic / Lecture Master Path — Audit

Scope: the missing generic `Semantic/Lecture Master` path for productions
originating from `ContentBrief`, per the NEXT IMPLEMENTATION TASK brief
(§1–§25). This closes the last hard blocker for Phase 21 (legacy 100-lesson
retirement).

## 1. Previous blocker

The only path into `LectureMasterVersion` was `LectureService.architect()`,
which requires a `ResearchPackage` whose origin is `ayin_spine_id` or
`lesson_id` + `lesson_canon_hash` + `LessonContentPackage` — so every
CONTENT_BRIEF production could reach Narrative READY and then dead-end:
`ScriptService` had no semantic contract to write from. The generic path
adds a third, explicit origin and removes `LessonCanonRepository`,
`LessonContentPackage`, `lesson_id`, `lesson_canon_hash`, and `AyinSpine`
as requirements of the *new* pipeline (they remain for historical rows).

## 2. Dependency map (pre-implementation)

| Dependency | Active callers |
|---|---|
| `LessonCanonRepository` | `app/web/routes.py` (owner lesson pages), `app/cli.py` (lessons commands), `app/content_strategy/persian_service.py`, `lesson_catalog.py`, `lesson_workflow.py`, `lesson_research.py` |
| `LessonContentPackage` | `lesson_canon.py`, `lesson_catalog.py`, `lesson_research.py`, `lesson_workflow.py`, `persian_pipeline.py`, `persian_service.py` |
| `lesson_id` / `lesson_canon_hash` | `app/research/models.py`+`schemas.py` (plan/package origin columns — schema, kept), `app/lecture/service.py` (legacy architect + term/authority payload), `app/web/routes.py`, `app/cli.py`, `app/content_strategy/*` |
| `AyinSpine` / `AYIN_FRAME` / `ResearchPackageAyin*` | `app/research/service.py` (spine research), `app/api/routes/research.py`, `app/lecture/service.py` (legacy architect), `app/lecture/domain.py` (`AYIN_FRAME` is a `SectionRole` value only), `app/cli.py` |

None of these were or are imported by the CONTENT_BRIEF pipeline files
(`app/briefs`, `app/research/generic.py`, `app/content_engine`,
`app/lecture/generic_service.py`, `app/production`,
`app/web/studio_routes.py`).

## 3. New architecture

```text
TopicCandidate → ContentBrief (READY/LOCKED)
  → ResearchPlan → EvidenceMatrix (READY/FROZEN) → ResearchPackage (FROZEN)
  → ArgumentPlan (READY) → NarrativePlan (READY)
  → GenericMasterService.build_from_content_brief  → LectureMasterVersion
     (origin_type=CONTENT_BRIEF, status=READY, frozen_at set)
  → ScriptService.build_script (gated on READY CONTENT_BRIEF master)
  → review → revise → approve
```

`app/lecture/generic_service.py` (`GenericMasterService`) is deterministic —
no LLM call, no plan regeneration. It is a pure projection of the frozen
upstream artifacts into the master contract:

- `_frozen_package` / `_matrix` / `_argument` / `_narrative` load the latest
  qualifying artifact **scoped to the brief** and raise `GateBlockedError`
  when a gate fails (§16):
  - brief must be READY or LOCKED;
  - `ResearchPackage` must be FROZEN for this brief;
  - `EvidenceMatrix` must be READY or FROZEN;
  - `ArgumentPlan`/`NarrativePlan` must be READY;
  - `argument.evidence_matrix_id == matrix.id`,
    `narrative.argument_plan_id == argument.id`;
  - `package.retrieval_snapshot.evidence_matrix_id` must match the matrix
    (when recorded) — a package frozen from another matrix is rejected;
  - `brief.strategy_version_id` must resolve to a `ChannelStrategyVersion`
    belonging to the brief's channel — cross-channel strategy is rejected.
- `_project` reuses the `LectureProject` bound to the package or creates a
  HUMAN_QUESTION project (duration/audience from the brief).
- `input_hash` covers builder version + brief/strategy ids + package,
  matrix, argument, narrative ids **and content hashes** — identical inputs
  are idempotent (same master returned); changed inputs mint version n+1.

### Master origin

`MasterOriginType` (`app/lecture/domain.py`): `LEGACY_AYIN`, `LEGACY_LESSON`,
`CONTENT_BRIEF`. New builders write it explicitly — legacy `architect()`
now tags `LEGACY_LESSON`/`LEGACY_AYIN` based on `package.lesson_id`;
historical rows keep NULL (the column postdates them, per docstring).

### Architecture snapshot (§7)

`LectureMasterVersion.architecture` stores: question, thesis, angle,
channel (id+slug), pinned strategy version, per-channel
`semantic_constraints` (§10 — `CHANNEL_SEMANTIC_CONSTRAINTS` keyed by the
five channel slugs), `distinctiveness` compact constraints
(§14: avoid hook/ending/argument signatures from `ScriptSignature` —
shapes only, no prose), `upstream` (versions + content hashes of package,
matrix, argument, narrative), `target_duration_minutes`, the narrative
section structure and the argument section structure verbatim.

### Sections (§8)

`LectureSection` is reused. `NarrativePlanSection`s map onto master
sections via `_NARRATIVE_ROLE_MAP`; unmapped roles fall back to the new
`SectionRole.NARRATIVE_BEAT` — the original narrative role is preserved in
`rhetorical_function` and in `architecture.sections`. `must_not_claim`
constraints from linked argument sections become
`prohibited_formulations`; `transition_out`/argument `transition_intent`
become `transition_intent`. No lesson-specific roles are introduced.

### Claims / evidence (§9)

One `LectureClaim` per `EvidenceMatrixItem`, placed on the master section
that maps the argument section referencing it (fallback:
counterargument/limitation section, else middle). Each claim preserves:
claim text, epistemic status (matrix role → `ClaimEpistemicStatus`),
allowed wording (`formulation_constraints`), forbidden wording
(`prohibited_overstatements`), limitations (`required_qualifiers`), and a
`source_evidence` snapshot per referenced KnowledgeUnit
(unit/source-version ids, title, summary, content hash).

`LectureClaimEvidence` binds the claim to its matrix item id and every
supporting/counterevidence/alternative unit with PRIMARY / COUNTEREVIDENCE
/ CONTEXT roles and JSON provenance. `LectureCitation` records unit →
source-version traceability per supporting unit. No `ResearchPackageAyin*`
tables are involved.

### Writer path (§11–§13)

`writer_export(master_id)` returns a bounded dict: master contract,
strategy policy JSONs, brief fields, sections, claims, citations, upstream
ids — never corpus/archive data (integration test asserts "lesson"/"canon"
absent). `ScriptService.build_script` now **requires** a READY
CONTENT_BRIEF master, builds the writer payload from master
sections+claims+uncertainty/channel constraints+distinctiveness, links
`ScriptDraft.lecture_master_version_id`, and records
`lecture_master_version` in `provenance_json`. The `script_draft` LLM task
is unchanged in shape — the input is the semantic master, not a lesson
package.

### UI (§15/§21)

- `/studio/production/{brief_id}` shows a "Semantic master" artifact row,
  the MASTER stepper stage, and a "Build Semantic Master" action when a
  READY narrative exists; "Build script" appears only once a READY master
  exists. No lesson fields are rendered.
- `ProductionService._latest_ready_master` reads only
  `origin_type=CONTENT_BRIEF` + `status=READY` masters — legacy masters
  never leak into the generic stage derivation.
- Resource processing stays synchronous/deliberate (no queue);
  `SourceProcessingState.status` is displayed on the structure and units
  pages with real enum values (STRUCTURE_PENDING … FAILED).

## 4. Schema changes

`b7c8d9e0f1a2` (additive): `master_origin_type` PG enum + six nullable
columns on `content.lecture_master_versions` (`origin_type`,
`content_brief_id`, `channel_strategy_version_id`, `argument_plan_id`,
`narrative_plan_id`, `evidence_matrix_id` — all FK, RESTRICT) +
`ix_lecture_master_versions_content_brief_id` +
`content.script_drafts.lecture_master_version_id` (FK, nullable).
Downgrade drops them in reverse. No historical column changed; NULL on all
existing rows.

`ScriptDraft.lecture_master_version_id` links each generic draft to the
master version it was written from — per-language drafts keep
`(brief, language, version)` uniqueness.

`f3a4b5c6d7e8` downgrade fix (functional, same migration): the downgrade
now drops the new-origin constraints by their emitted `ck_*` names and
re-creates the pre-brief `valid_research_origin` /
`valid_research_plan_origin` definitions (as last set by `b5c6d7e8f9a0`)
before dropping `content_brief_id`. Previously a downgrade→upgrade cycle
failed with `constraint ... does not exist`. Note: `op.drop_constraint`
emits the literal name for generic constraints but applies the
`ck_{table}_{name}` convention when `type_="check"` — mixing the two
double-prefixes; the file now uses the full `ck_` name without `type_`,
matching the upgrade.

`app/topics/models.py`: `UniqueConstraint`s on the topic association
tables declare the explicit names the migration created
(`uq_topic_candidate_unit`, `uq_topic_candidate_concept`) — removes the
autogen name drift introduced in Phase 8.

## 5. Legacy compatibility

- Legacy `LectureService.architect()` is untouched apart from writing the
  `origin_type` marker; all lesson/spine fields, validators, exports stay.
- All lesson/spine columns, tables, routes, CLI commands, and the Persian
  lesson pipeline remain readable and functional.
- `MasterOriginType`/`NARRATIVE_BEAT`/`master_origin_type` enum were added
  via `ALTER TYPE/CREATE TYPE` — historical rows unaffected.

## 6. Tests

New/updated coverage:

- `tests/unit/test_generic_master.py` (5): all five channel slugs have
  semantic constraints; role map only targets real `SectionRole`s; known
  roles map; unknown → NARRATIVE_BEAT; ending mode derivation.
- `tests/integration/test_topics.py::test_generic_master_path`: gate
  ladder (brief → package → matrix → argument → narrative), READY master,
  `CONTENT_BRIEF` origin, all upstream ids pinned, `canon_version_id` is
  NULL, architecture carries question/thesis/versions, idempotent rebuild,
  section/claim/binding/citation traceability, workspace stage=MASTER with
  `build_script` allowed, script draft linked to the master, bounded
  writer export (no lesson/canon), cross-channel strategy rejected.
- `tests/integration/test_topics.py::test_engine_gates`: script blocked
  without master; draft → critics → BLOCKER-gated approve → revise →
  approve still green.
- `tests/integration/test_studio_ui.py::test_production_workspace_generic_master_flow`:
  real pipeline → workspace shows "Build Semantic Master", POST advances
  stage to MASTER, "Build script" appears, no "lesson" strings rendered.

## 7. Verification results

- `ruff check` / `ruff format --check` on all touched files: clean.
- `mypy --strict app`: 204 files, no issues.
- `pytest tests/unit`: 252 passed.
- `pytest tests/integration`: 49 passed, 4 failed — all four pre-existing
  or environmental, none in the generic path:
  - `test_clean_migration_downgrade_and_second_upgrade_are_safe`: the
    downgrade→upgrade cycle now passes; `command.check` still reports only
    the two `ix_speech_*` index-name diffs documented as cosmetic drift in
    the Phase-0 baseline.
  - `test_multilingual_editorial`: Persian voice-prep normalization
    inserts ZWNJ (`آیین امتداد` → `آیینِ امتداد`) — pre-existing, untouched
    pipeline.
  - `test_owner_topic_detail`, `test_persian_editorial`: live Devin Cloud
    API 429 ("5 SWE-2 sessions running") — quota, not code.
- All §29.5 production gates exercised in `test_topics.py` /
  `test_engine_gates` / `test_generic_master_path` pass.

## 8. Remaining Lesson Canon dependencies

The CONTENT_BRIEF runtime path has **zero** references to
`LessonCanonRepository`, `LessonContentPackage`, `lesson_id`, or
`lesson_canon_hash` (verified by grep over
`app/{briefs,research/generic,content_engine,lecture/generic_service,production,web/studio_routes}.py`
and their transitive module deps `lecture/{models,validator,domain}` — the
only `AYIN_FRAME` hit is a `SectionRole` value never emitted by the
generic role map).

Still active (legacy-only):

- `app/web/routes.py` — owner lesson pages (`LessonCanonRepository` ×6).
- `app/cli.py` — `lessons status|package|project|research|draft|ledger`.
- `app/content_strategy/persian_service.py`, `persian_pipeline.py`,
  `lesson_canon.py`, `lesson_catalog.py`, `lesson_research.py`,
  `lesson_workflow.py`, `story_library.py`, `text_library.py`,
  `models.py` — the legacy Persian lesson pipeline.
- `app/lecture/service.py` — legacy `architect()` and spine/lesson
  payloads (historical readability required).
- `app/research/{models,schemas}.py` — `lesson_id`/`lesson_canon_hash`
  **columns** (schema for historical rows — must stay).
- `app/research/service.py`, `app/api/routes/research.py` — Ayin Spine
  research lane (not lesson-canon, but legacy-origin).

## 9. speech_structure vs knowledge/structure

| | `app/speech_structure/` (legacy) | `app/knowledge/structure/` (target) |
|---|---|---|
| Purpose | Auto-generated hierarchical "Vortragsstruktur" per transcript with a background scheduler, retry/backoff, owner review UI | Canonical source-structure system for the resource-first pipeline; feeds Knowledge Unit extraction, concept mapping, unit retrieval |
| Models | `SpeechStructure` (versioned), `SpeechStructureRun` (provider/model/prompt/metrics), `SpeechSection` (tree, `section_role`, `section_number`), `SpeechSectionSegment` (explicit M2M to segments with relation_type+confidence) | `SourceProcessingState` (1:1 lifecycle FSM), `SourceStructureNode` (composite-FK tree, contiguous `start/end_segment_id` spans, `extraction_run_id` provenance) |
| Services | `SpeechStructureService` (two-pass global+local pipeline, regenerate, backfill_all), `SpeechStructureScheduler` (in-process queueing, rescan, retry) | `SourceStructureService` (idempotent via `ExtractionRun` dedup keys; deterministic processing-state transitions; `process_source`, `get_tree`, `get_node_detail`, `validate_stored`) |
| Routes | `/speech-structures*` owner pages + generate/regenerate/scan/retry POSTs; scheduler boot in `app/main.py`; auto-enqueue on YouTube import (`web/service.py`, `channel_monitoring/service.py`), CLI `speech-structure backfill` | `/library/{id}/structure` studio page + POST build; called by `/library/{id}` actions; no scheduler (deliberate, synchronous) |
| Stored data | Structure + runs + sections + segment links in `knowledge` schema | Processing state + nodes in `knowledge` schema |
| Tests | `tests/unit/test_speech_structure{,_scheduler}.py` | `tests/unit/test_source_structure.py`, `tests/integration/test_source_structure.py` |
| Overlap | Both build a hierarchical transcript structure per source version | Same |
| Unique to legacy | Scheduler/retry/backoff, `SpeechSectionSegment` M2M (multi-relation segment links), regenerate/versioning UX, auto-enqueue on import | — |
| Unique to target | `SourceProcessingState` FSM driving the whole resource lifecycle, contiguous span FK guarantees, `ExtractionRun` dedup/provenance, feeds units→concepts→retrieval→topics | — |

Consolidation direction (target: `knowledge/structure`):

1. Keep `knowledge/structure` as the canonical Vortragsstruktur; the
   resource-first pipeline already depends on it.
2. Before deleting `speech_structure`, migrate its unique behaviors:
   - the segment↔section M2M (`SpeechSectionSegment`) if multi-relation
     segment links are ever needed — currently `SourceStructureNode`'s
     contiguous span suffices;
   - decide whether the import-time auto-enqueue should schedule
     `SourceStructureService.process_source` instead (spec keeps
     processing manual/deliberate — likely keep manual);
   - owner UI `/speech-structures*` vs studio `/library/{id}/structure` —
     retire the legacy pages once owner confirms.
3. Historical `speech_*` tables: keep for read access (RESTRICT FKs from
   segments), then archive in Phase 21+.

No destructive consolidation performed — unique behavior (scheduler,
segment M2M) requires an owner decision first.

## 10. Next deletion steps (Phase 21 preview)

Safe to delete after owner confirmation (nothing in the generic path
imports them):

- `app/content_strategy/lesson_canon.py`, `lesson_catalog.py`,
  `lesson_research.py`, `lesson_workflow.py`
- `app/content_strategy/persian_pipeline.py`, `persian_service.py`,
  `persian_prompt.py`, `persian_quality.py` (legacy lesson writer)
- Lesson routes/templates inside `app/web/routes.py` + lesson templates
- `app/cli.py` lesson subcommands
- `resources/editorial/lesson_canon` data loader references

Must stay: `lesson_id`/`lesson_canon_hash` **columns** and the
`research_plans`/`research_packages`/`script_drafts` lesson-origin
schema/history; `app/lecture/service.py` legacy reader behavior for
historical masters; `app/speech_structure/` pending §9 consolidation
decision.
