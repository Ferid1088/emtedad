# Multichannel Migration — Phase 0: Baseline and Safety

Date: 2026-10-03

## Scope

Establish a reproducible baseline before the multi-channel resource-first
architecture migration described in
`docs/EMTEDAD_CODING_AGENT_MASTER_IMPLEMENTATION_PROMPT.md`.

## Baseline commands and results

| Command | Result |
|---|---|
| `uv run ruff check app/ tests/` | pass |
| `uv run ruff format --check app/ tests/` | fail — 14 files would be reformatted (pre-existing formatting drift) |
| `uv run mypy --strict app` | pass — 153 source files |
| `uv run pytest tests/unit -q` | pass — 232 tests |
| `EMTEDAD_DATABASE_URL=... uv run pytest tests/integration -q` | 29 passed, 4 failed |

## Known failures at baseline

1. `test_clean_migration_downgrade_and_second_upgrade_are_safe` — Alembic
   autogenerate detects index-name drift only:
   `ix_speech_sections_structure_id` → `ix_speech_sections_speech_structure_id`
   and `ix_speech_structure_runs_structure_id` →
   `ix_speech_structure_runs_speech_structure_id`. Cosmetic; no schema-shape
   difference.
2. `test_approved_persian_is_exact_source_for_tracks_and_voice`,
   `test_topic_discovery_batches_and_workspace_actions`,
   `test_persian_drafts_are_researched_versioned_and_owner_approvable` —
   fail with `DevinCloudError` HTTP 429 (concurrent-session quota on the
   Devin Cloud free tier). Environmental, not a code defect; they require a
   live LLM provider.

## Current surface inventory

- API routers: ayin, ritual, knowledge, lecture, retrieval, research,
  dialogue, health (47 routes).
- Web router: 62 routes including `/`, `/sources*`, `/knowledge`,
  `/lessons*`, `/stories*`, `/topics*`, `/strategy*`, `/workspace*`,
  `/texts*`, `/archive`, `/studio*`, `/lexicon*`, `/channels*`
  (source-channel monitoring).
- Speech-structure router mounted separately.
- Domain modules: `core/ayin`, `ritual`, `knowledge`, `retrieval`,
  `dialogue`, `research`, `lecture`, `localization`, `content_strategy`,
  `channel_monitoring`, `speech_structure`, `topic_discovery` (empty),
  `storage`, `ops`, `web`.

## Lesson-canon dependencies to retire later

- `app/content_strategy/lesson_canon.py` — `LessonCanonRepository` and
  `LessonContentPackage` loading from `resources/editorial/lesson_canon/`.
- `app/content_strategy/lesson_catalog.py`, `lesson_workflow.py`,
  `lesson_research.py` — 100-lesson catalog, project workflow, lesson-scoped
  research packages.
- `app/research/models.py` — `lesson_id`/`lesson_canon_hash` fields on
  research plans/packages (kept for historical provenance).
- `app/web/routes.py` — `/lessons*` routes and lesson navigation;
  `app/web/templates/lessons*.html`, `lesson_detail.html`,
  `lesson_concepts.html`.
- `app/cli.py` — `lessons` command group.
- `app/content_strategy/persian_service.py`, `persian_pipeline.py`,
  `story_library.py`, `text_library.py` — lesson-aware production services.

## Decisions recorded

- `docs/decisions/ADR-014-multichannel-resource-first-studio.md`

## Behavior changed

None. Phase 0 is inspection and decision-recording only.
