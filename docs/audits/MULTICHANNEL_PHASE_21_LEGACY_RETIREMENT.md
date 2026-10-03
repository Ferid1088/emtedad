# Phase 21 — Legacy 100-Lesson Path Retirement

Date: 2026-10-03. Scope: retire the active 100-lesson production
architecture, consolidate `speech_structure` onto `knowledge/structure`,
extract generic Persian writing capability, and preserve all historical
data read-paths. Owner approval for the deletion list was given in the
Phase-21 kickoff with the explicit instruction to classify before deleting.

## 1. What was removed

**Lesson-only production code (class A: delete):**

- `app/content_strategy/lesson_catalog.py` — file-backed 100-lesson catalog.
- `app/content_strategy/lesson_research.py` — `LessonResearchService`,
  lesson-bound automatic external research.
- `create_lesson_project` and the active project-generation half of
  `lesson_workflow.py`.
- `LessonCanonRepository`, catalog loaders, and canonical-explanation
  generators from `lesson_canon.py`.
- `MASTER_PERSIAN_WRITING_PROMPT` (`persian_prompt.py`) — replaced by
  generic voice contracts in `app/content_engine/writing/prompts.py`.
- `persian_quality.py` — moved (not deleted) into
  `app/content_engine/writing/quality.py`.
- Lesson-ID-hash-based `_diversity_plan` and `ScriptOutline` — superseded
  by `ScriptSignature` / `DistinctivenessPlanner`.
- `generate()` / draft generation from `PersianEditorialService`.
- File-backed canon: `resources/editorial/lesson_canon/{Ayin_Emtedad_100_Dars.md,lessons.json,lesson_relations.json}`.
  No runtime reads remained (verified by global search before removal).

**Duplicate active speech-structure code (class A: delete):**

- `app/speech_structure/{service,pipeline,prompts,schemas,validator,routes,scheduler}.py`
- Templates `lessons.html`, `lesson_detail.html`, `lesson_concepts.html`,
  `speech_structures.html`, `speech_structure_detail.html`, `studio.html`
  (superseded by `studio/`).

**Routes:**

- `GET /lessons`, `GET /lessons/{id}`, `GET /lessons/concepts`,
  `POST /lessons/{id}/projects` → replaced by `GET /lessons` +
  `GET /lessons/{rest:path}` 303-redirects to `/studio`.
- `POST /workspace/{id}/research` (lesson-bound research trigger).
- `POST /workspace/{id}/persian/drafts` (lesson-canon draft generation).
- `/speech-structures*` router unmounted from `app/main.py`.
- Draft `edit`/`review`/`approve`, translations, voice, publication and
  all Studio routes are unchanged.

**CLI:** `lessons status|package|project|research|draft|ledger` and the
speech-structure backfill command were already removed in the surgery
session; the CLI now exposes only ayin, manasek, knowledge, retrieval,
dialogue, research, and lecture domains.

## 2. What was retained (class C: historical read support)

- `app/content_strategy/lesson_canon.py` — `LessonContentPackage`,
  `LessonRelation`, `AyinProvenance`, `CoreConceptDefinition` Pydantic
  models only, so persisted snapshots still validate.
- `app/content_strategy/lesson_workflow.py` — `lesson_project_metadata`,
  `lesson_package_from_project`, `lesson_project_snapshot`,
  `lesson_research_summary` (read-only snapshot readers).
- `app/content_strategy/persian_pipeline.py` — `LessonConsistencyReviewer`,
  `review_bundle`, `final_semantic_findings` (lesson-semantic review used
  only when a historical draft carries a pinned package snapshot).
- `app/content_strategy/persian_service.py` — `edit` / `review` /
  `approve` for existing drafts; review now also runs a generic
  deterministic path (quality + native + diversity) for drafts without a
  pinned lesson package.
- `app/speech_structure/{domain,models}.py` — enums + ORM models so
  historical `speech_structures` / `speech_sections` /
  `speech_section_segments` rows remain readable and migrations work.
- All `lesson_id` / `lesson_canon_hash` / `lesson_content_package_*`
  columns on `research_plans`, `research_packages`, `channel_ledger_entries`,
  `editorial_projects.strategy_topic_snapshot` — marked
  `LEGACY_PROVENANCE_ONLY`; no migration drops them.
- `app/lecture/service.py` `architect()` — legacy Ayin/spine lane, reads
  historical lesson provenance, emits `LEGACY_*` origins only.

## 3. Generic capabilities extracted (class B: moved)

New package `app/content_engine/writing/`:

| Module | Extracted capability | Source |
|---|---|---|
| `quality.py` | `PersianDraftQualityValidator`, `clean_source_text`, `word_count`, `duration_findings` | `persian_quality.py` |
| `text.py` | `extract_examples`, `extract_open_promises`, `explicit_ayin_reference_ratio`, `deduplicate_findings` | `persian_pipeline.py` |
| `memory.py` | `PublishedMemoryItem`, `PublishedMemoryReader`, `ScriptDraftMemoryReader` (lesson metadata optional; `lesson_id=None` for generic items) | `persian_pipeline.py` |
| `diversity.py` | `ScriptDiversityValidator` | `persian_pipeline.py` |
| `native.py` | `PersianNativeReviewer`, `PersianNativeOptimizer` | `persian_pipeline.py` |
| `prompts.py` | `PERSIAN_VOICE_CONTRACT` (channel-agnostic), `EMTEDAD_VOICE_CONTRACT` (Ayin boundaries, Emtedad channel only) | `persian_prompt.py` |
| `findings.py` | `PipelineFinding` shared finding type | `persian_pipeline.py` |

`ScriptService.build_script` appends `PERSIAN_VOICE_CONTRACT` for `fa`
drafts (+ `EMTEDAD_VOICE_CONTRACT` on the emtedad channel);
`ScriptService.review_draft` runs the deterministic Persian checks
(`_persian_findings`: quality validator, native reviewer, archive
diversity) under `CriticRole.PERSIAN_QUALITY`. None of these requires a
lesson package, lesson ID, or canon hash.

## 4. speech_structure consolidation matrix

| Feature | Legacy `speech_structure` | `knowledge/structure` | Action |
|---|---|---|---|
| Hierarchy | `SpeechSection` rows | `SourceStructureNode` (parent/child, exact segment FKs) | canonical kept; legacy model retained read-only |
| Segment links | `SpeechSectionSegment` M2M | `start_segment_id`/`end_segment_id` contiguous spans | canonical kept |
| Retry/backoff | scheduler `failed_attempts` + exponential + quota backoff | ported to `SourceProcessingScheduler`; attempts persisted on `source_processing_states.attempt_count` | migrated |
| Auto processing | enqueue on import + periodic scan | `schedule_structure_analysis` on import + `run_forever` scan | migrated |
| Owner review UI | `/speech-structures*` pages | structure review via canonical `STRUCTURE_REVIEW_REQUIRED`/`UNIT_REVIEW_REQUIRED` states on source/resource views | consolidated |
| Extraction dedup | `SpeechStructureRun` | `ExtractionRun` unique key; retries upsert the same row | canonical kept |
| FSM | `StructureStatus` per structure | `SourceProcessingState` per source — authoritative | canonical kept |
| KnowledgeUnit integration | none | units bound to structure nodes | canonical kept |

## 5. speech_structure migration result

No data migration was needed: the two systems never shared tables, and
canonical rows already exist for every processed SourceVersion (they feed
KnowledgeUnits → retrieval → topics). Legacy `speech_structures*` tables
are retained read-only for historical inspection; no row mapping was
invented, per §21.

Canonical ownership now: `app/knowledge/structure` is the single owner of
transcript → Vortragsstruktur. `app/knowledge/processing.py`
(`SourceProcessingService`) is the single synchronous entry point
(structure → units → READY); `app/knowledge/structure/scheduler.py` is
the in-process queue/scan/backoff owner. Both `web/service.py` and
`channel_monitoring/service.py` schedule the canonical path on import.
`ExtractionRun` retries reuse the dedup-keyed row (unique constraint
made naive re-insert unsafe); `attempt_count` on
`source_processing_states` (migration `c1d2e3f4a5b6`) persists backoff
state across restarts.

## 6. Historical data preservation

- All lesson-bearing columns kept and marked `LEGACY_PROVENANCE_ONLY`.
- Historical projects render through `/workspace/{id}` with
  "Historische Lektion" provenance; drafts remain editable/reviewable/
  approvable.
- Published memory keeps historical `lesson_id` values; new generic
  entries write `lesson_id=None`.
- Story-library `related_lessons` are curator provenance; the UI shows
  them as text badges (no dead links).
- `speech_structures*` tables untouched (model-only package).

## 7. DB migrations

- `c1d2e3f4a5b6_add_processing_attempts` — additive
  `source_processing_states.attempt_count` (retry bookkeeping). No
  destructive changes; `downgrade` restores the prior shape.

## 8. Remaining lesson references (post-sweep classification)

`ACTIVE_GENERIC`: **0**. Remaining matches are `LEGACY_READ_ONLY`
(lesson_workflow/persian_service/persian_pipeline/lesson_canon models,
`lecture/service.py` spine lane, research model columns), `TEST_FIXTURE`
(retirement + historical-readability tests), `MIGRATION` (schema
history), or `DOCUMENTATION`.

## 9. Test results

- `ruff check` + `ruff format --check`: clean on all changed files.
- `mypy --strict app`: clean (203 files).
- Unit: **220 passed**.
- Integration: **52 passed, 3 failed** — all three are the documented
  baselines, unchanged by this phase:
  - `test_clean_migration_downgrade_and_second_upgrade_are_safe`: the
    downgrade→upgrade cycle passes; `command.check` reports only the
    Phase-0 `ix_speech_*` index-name cosmetic drift.
  - `test_multilingual_editorial`: pre-existing ZWNJ ezafe insertion in
    voice preparation (`آیین امتداد` → `آیینِ امتداد`), untouched pipeline.
  - `test_owner_topic_detail`: depends on the live Devin provider; this
    run produced an empty suggestions batch (same environmental
    dependency as the baseline 429s).
- New/updated tests:
  - `test_source_processing_scheduler.py` — eligibility, backoff,
    review-block, dedup, crash-resilience of the canonical scheduler.
  - `test_lesson_retirement.py` — `/lessons*` redirects, no creation
    route, no lesson nav, historical project readable + draft edit/
    approve gate preserved.
  - `test_persian_editorial.py` — generation POST gone; edit/review/
    approve work on a lesson-free draft via the generic review path.
  - `test_generic_e2e.py` — §24 full chain: YouTube fixture → import →
    SourceVersion → segments → Vortragsstruktur → KnowledgeUnits →
    channel → topic → brief → plan → matrix → frozen package → argument
    → narrative → generic master → ScriptDraft; asserts exact-segment
    node mapping, single dedup run per task, retry without run/hierarchy
    duplication, `CONTENT_BRIEF` origin, and `lesson_id`/`lesson_canon_hash`
    NULL on the produced package.
  - `test_persian_{quality,prompt,pipeline}.py` — repointed to
    `app.content_engine.writing` (+ hand-built `LessonContentPackage`
    fixture for the retained `LessonConsistencyReviewer`).
  - `test_owner_web.py`, `test_owner_dashboard.py`,
    `test_topic_strategy.py` — updated to the post-retirement UI.

## 10. Acceptance gate review (§28)

- No new Lesson Canon project can be created — routes + service gone; ✓
- 100-lesson UI gone — nav, dashboard, catalog templates removed; ✓
- Fixed lesson resources no longer runtime inputs — canon files deleted,
  zero reads; ✓
- New productions use `CONTENT_BRIEF` — verified E2E; ✓
- Generic master + writer functional — `test_generic_master_path`,
  `test_generic_e2e`; ✓
- Generic Persian quality preserved — writing package + ScriptService
  wiring + adapted tests; ✓
- Published memory requires no lesson metadata — `lesson_id=None` on
  generic items; ✓
- Historical lesson projects readable — `test_lesson_retirement`; ✓
- Ayin remains a resource — ayin domain/CLI/knowledge lanes untouched; ✓
- `knowledge/structure` canonical; no second active system — legacy
  package is models-only; ✓
- KnowledgeUnits use canonical structure — unchanged, E2E-verified; ✓
- YouTube import works — E2E imports via `ExternalKnowledgeImporter`
  and schedules canonical processing; ✓
- Processing state coherent — one `SourceProcessingState` row per
  source; retry/attempt bookkeeping persisted; ✓
- All affected tests pass — 3 documented baseline failures remain. ✓
