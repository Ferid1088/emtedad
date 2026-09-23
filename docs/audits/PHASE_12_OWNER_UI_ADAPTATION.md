# Phase 12 — Owner UI Adaptation for Lesson Canon and Channel Memory

## Outcome

The owner UI now treats the approved 100-lesson canon as the stable editorial
map while retaining dynamic topics as a separate workspace. Canonical lesson
projects reuse `EditorialProject`, Studio, multilingual tracks, and the text
library. Published-only memory is visible without exposing internal ledger
tables or using published prose as writer context.

## Acceptance evidence

- Primary navigation contains Dashboard, Lektionen, Themen, Quellen, Kanäle,
  Wissensbasis, Studio, Texte, and Archiv; the historical strategy tree is not
  an owner-facing content surface.
- `/lessons` renders exactly 100 imported lessons and the real 837-relation and
  22-core-concept health counts.
- Search, status/concept/prerequisite/range filters, lesson detail, relation
  links, and owner-facing status labels are covered by tests.
- Starting from a lesson creates an existing `EditorialProject` with a pinned
  Lesson Content Package and opens the existing Studio workflow.
- Studio presents Ayin-Kern and external research as separate panels and does
  not offer ordinary full-book Ayin retrieval.
- Studio, Texte, and text detail retain lesson, AI-topic, owner-topic, or
  historical provenance without forcing every text into the canon.
- Legacy strategy URLs redirect to `/lessons`; tree rendering, approval, and
  topic-use actions cannot recreate or expose the old fixed strategy.
- Archiv and the knowledge-base script archive contain only published texts;
  unpublished drafts are explicitly excluded.
- A safe local-browser fixture was created, approved, published, observed in
  channel memory, and then removed from the development database.

## Verification

```text
uv run ruff check <changed Python files>
All checks passed!

uv run ruff format --check <changed Python files>
16 files already formatted

uv run mypy --strict app
Success: no issues found in 137 source files

uv run pytest tests/unit -q
146 passed

EMTEDAD_DATABASE_URL=... uv run pytest \
  tests/integration/test_owner_dashboard.py \
  tests/integration/test_owner_lessons.py -q
2 passed
```

The full database-backed suite was also run: `181 passed, 3 failed`. The three
remaining failures are outside this UI change and are not hidden:

- the existing Persian voice normalizer changes `آیین` to `آیینِ`, while a
  multilingual regression test still expects byte-identical voice text;
- the topic-suggestion integration fixture selects a latest persistent batch
  that contains no topics after repeated local runs;
- the historical strategy-tree integration fixture expected a seeded strategy,
  but the current local database contained none. This obsolete expectation was
  closed by the later tree-retirement regression test.

The directly affected owner tests, all unit tests, strict mypy, changed-file
Ruff, template parsing, and browser QA pass.

Legacy-tree retirement follow-up:

```text
uv run pytest tests/unit/test_owner_web.py tests/unit/test_text_library.py -q
9 passed

EMTEDAD_DATABASE_URL=... uv run pytest \
  tests/integration/test_topic_strategy.py \
  tests/integration/test_owner_dashboard.py \
  tests/integration/test_owner_lessons.py -q
3 passed
```

## Browser QA

Desktop, 375-pixel mobile, and 768-pixel tablet layouts were inspected in
Chrome. The real journey covered Dashboard, the 100-lesson catalog, Persian
search, lesson detail and relation links, project creation, Studio context,
external-research separation, text provenance, unpublished-memory exclusion,
safe-fixture publication, published-memory inclusion, and cleanup. No owner
route in that journey returned a 500 response.

## Migrations and protected files

No schema migration was required. The lesson package and publication metadata
reuse existing versioned JSONB and editorial-project boundaries.

`docs/specification/MASTER_IMPLEMENTATION.md` and
`resources/ayin/working_seed.v1.json` were not modified by this work and are not
part of its commit.
