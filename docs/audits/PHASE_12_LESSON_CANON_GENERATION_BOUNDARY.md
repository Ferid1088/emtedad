# Phase 12 — Lesson Canon Generation Boundary

## Outcome

ADR-013 separates the four production roles:

```text
Generation = Canonical Lesson Content + Core Concept Registry + External Research
Review     = Channel Ledger + Published Script Archive + Lesson Relations
```

The full Ayin corpus remains stored and searchable for audit, lesson-canon
verification, revision, citations, provenance inspection, and specialist
research. It is not ordinary script-generation context.

## Implementation evidence

- `LessonCanonRepository` validates the 100 lessons, unique IDs,
  prerequisites, and all relation endpoints directly from the approved JSON.
- `LessonContentPackage` preserves supplied canonical fields and optional Ayin
  provenance without inference.
- The Studio requires an explicit lesson ID before Persian generation.
- Draft provenance stores the full Lesson Content Package snapshot, lesson ID,
  package version, canon content hash, provenance-completeness state,
  generation roles, and review-only roles.
- Persian writer context excludes every non-external Semantic Master claim and
  every non-`EXTERNAL_CHUNK` evidence item.
- Default ResearchPlan questions contain external evidence and counterevidence
  only. Explicit Ayin retrieval remains available to specialist workflows.
- Stable per-lesson diversity plans vary opening, argument structure, emotional
  movement, and ending without changing canonical meaning. The deterministic
  test currently yields 94 distinct four-part profiles across 100 lessons.
- The writer prompt prohibits full-book retrieval, replacement Ayin seeds,
  Published Script Archive prose, and Channel Ledger prose.

## Verification

```text
.venv/bin/ruff check <changed Python files>
All checks passed!

.venv/bin/mypy app/content_strategy/lesson_canon.py \
  app/content_strategy/persian_service.py app/research/service.py \
  app/web/routes.py tests/unit/test_lesson_canon.py \
  tests/unit/test_persian_prompt.py
Success: no issues found in 6 source files

.venv/bin/pytest -q tests/unit
142 passed

EMTEDAD_DATABASE_URL=... .venv/bin/pytest -q \
  tests/integration/test_persian_editorial.py
1 passed
```

The integration run emitted two upstream deprecation warnings from
FastAPI/Starlette test dependencies; it had no application failure.

The broader repository sweep was also attempted and its unrelated failures are
not hidden:

- `.venv/bin/ruff check .` reports 19 existing import-order/unused-import
  findings in `alembic/env.py` and legacy migration files outside this change.
- `.venv/bin/ruff format --check app tests` reports one existing formatting
  difference in `app/localization/validators.py`; the changed lesson-generation
  files pass the formatter check.
- `.venv/bin/pytest -q` without the required database environment produced
  `147 passed, 13 skipped, 2 failed, 16 errors`; all failures/errors came from
  integration fixtures requiring `EMTEDAD_DATABASE_URL`. The directly affected
  integration test was rerun with the configured local PostgreSQL URL and
  passed.

## Migrations

None. The immutable package snapshot and pins fit the existing JSONB draft
provenance boundary. No canonical or historical database records were changed.

## Review items and risks

- The supplied `lessons.json` has no per-lesson Ayin source version,
  passage/page, related-concept, or distinction fields. Each affected package
  explicitly reports `MISSING_LESSON_AYIN_PROVENANCE`; mappings must arrive in
  an approved canon revision and must not be inferred.
- Channel Ledger and Published Script Archive review services are not yet
  persisted in this checkpoint. Their absence cannot leak prose into generation;
  implementing their post-draft checks remains a future scoped task.
- Existing historical Semantic Masters may contain Ayin retrieval results, but
  the production context builder filters those claims and evidence before the
  writer call.

## Proposed next phase

Evaluation and acceptance should add fixtures for all 100 lessons, verify that
every production context contains exactly one canonical lesson package and no
raw Ayin-book evidence, and measure opening/example/argument/ending diversity.
