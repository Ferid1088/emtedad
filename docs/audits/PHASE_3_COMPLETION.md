# Phase 3 Completion — Manasek Ritual Domain

Date: 2026-09-19
Checkpoint target: `feat: implement manasek ritual domain`

## A. Files created or changed

Created:

- `alembic/versions/20260919_0004_manasek_ritual_domain.py`
- `app/ritual/{domain,extractor,importer,models,parser,repository,safety,schemas,seed,service,validator}.py`
- `app/api/routes/ritual.py`
- `tests/unit/ritual/test_safety.py`
- `tests/importers/test_manasek_pdf_extraction.py`
- `tests/integration/ritual/{conftest,test_manasek_import}.py`
- `docs/decisions/ADR-006-manasek-ritual-structure-and-safety.md`
- this report

Changed:

- `alembic/env.py`, `app/main.py`, and `app/cli.py`
- `README.md`
- `docs/architecture/DATA_MODEL.md`
- `docs/architecture/DOMAIN_RULES.md`
- `docs/audits/README.md`
- `docs/execution/CURRENT_PHASE.md`
- `docs/execution/MASTER_PLAN.md`

## B. Migration

Alembic revision `20260919_0004` creates the typed `ritual` domain. Clean
upgrade, repeat upgrade, `alembic current`, drift check, downgrade to
`20260918_0003`, and re-upgrade all passed on a disposable PostgreSQL database.
The downgrade explicitly removes Phase 3 enum types while retaining the shared
schema created by Phase 1.

## C. Ritual database model

The model separates Manasek documents, Working/Canon source versions,
extraction runs, and run-pinned passages. It adds stable/versioned families,
five gates, architecture versions, seven stages, rituals and versions,
relational sequence items, separately typed Returns, timed cues, music
specifications, Persian draft localizations, typed Ayin links, safety rules and
versions, validation results, and run-pinned review flags.

Deferred PostgreSQL triggers enforce approved aggregate completeness and
publishability. Typed foreign keys and explicit cascade behavior are used; no
generic `owner_type`/`owner_id` relationship exists. Approved records and their
important children are immutable.

## D. Manasek source/version/extraction statistics

- Source: `docs/source_material/Manasek_V1.pdf`
- SHA-256: `f5f07580d10b165b07513fe802ca86d8969cbe24a9d110d208b424c58c73f1af`
- Pages: 42
- Source versions: 1 `MANASEK_WORKING` / `draft`
- Extraction runs: 2 for the same source version
- Run-pinned passages: 84 total, 42 per run
- Poppler 26.08.0 output hash:
  `693c7b81d745ced1a67e23504e9d2b8ce9831d883d52dc466090aad87abd4d78`
- Poppler 25.03.0 output hash:
  `bddaf5905e42497b72f054d65d57630b5bfcd91faf8cc6932f2814f55735fac0`

Repeated imports reused the corresponding source version and extraction run.
The second extractor created a separate run without duplicating stable ritual
identities.

## E. Gates

Five stable, ordered gate identities were created: Earth, Water, Fire, Wind,
and Pull. Their Working versions explicitly state that gates are not Bon
components, metaphysical elements, or personality categories. Database checks
reject those classifications.

## F. Stages

Seven ordered stages were stored using `sequence_position`, not calendar days:
Contact, Distinction, Continuity in Change, Temporal Emtedad, Effect and
Responsibility, Other and Breadth of Presence, and Integration.

## G. Individual gate rituals

Thirty-five gate ritual versions were imported: five ordered gates for each of
seven stages.

## H. Returns

Seven Return versions were imported, one after the five gate pieces in each
stage. Return has its own type and extension record; database checks prevent it
from being classified or placed as a gate. The individual architecture has 42
pieces total.

## I. Collective structure

One source-backed collective ritual was imported under a distinct
`COLLECTIVE` architecture with no individual stages. It traverses the five
gates in one session without reusing or compressing the 42-piece sequence.

## J. Timed cues

The import produced 224 ordered cues. Individual gate rituals retain five
narration windows, Returns retain six review/reorientation cues, and the
collective ritual retains seven timeline cues. Database constraints reject
negative starts and invalid end intervals.

## K. Music specifications

Forty-three music specifications retain duration, sonic family, emotional arc,
intensity and transition policy, prohibited features, ending requirements, and
the complete original prompt. No music was generated.

## L. Ayin concept links

- 43 ritual-to-concept links
- 8 gate-to-concept links
- 11 stage-to-concept links
- 1 typed `horizontal_emtedad` proposal

All resolved links use real versioned foreign keys to the current
`AYIN_WORKING` version and retain Manasek source-passage provenance. The
unresolved horizontal concept was not invented or promoted.

## M. Safety rules

Thirty-three versioned rules cover consent, exit, touch, movement, breath,
intensity, interpretation, group pressure, disclosure, aftercare, music, and
mental-health boundaries. Every imported ritual and Persian localization is
bound to all 33 current Working/review rule versions.

## N. Safety validator results

Deterministic checks block forced eye closing, screaming/catharsis, required
outcomes, metaphysical proof, diagnosis/interpretation of resistance, breath
holding, denied exit, and sacred/hidden/healing-frequency certainty. The
required optional, stop, exit, non-interpretive examples pass.

The full structural validator reported `valid=true`, zero issues, and
`publishable=false`. The imported records are drafts and their safety rules are
in review, so they cannot be published or approved.

## O. Review flags

Each extraction run has one open, run-pinned review flag for the explicit
Manasek `horizontal_emtedad` reference whose Ayin concept identity does not yet
exist. Both flags retain page 33 provenance. No uncertainty was silently
resolved.

## P. Test results

- All unit tests: 47 passed
- All importer tests: 6 passed
- All integration tests: 16 passed
- Phase 3 focused unit/importer run: 14 passed
- Phase 3 focused integration run: 6 passed
- Full Phase 1–3 suite: 69 passed

Tests cover source/extraction identity separation, exact idempotency, new
source hashes, rollback, structure and sequence, collective separation, Return
typing, Working/Canon rules, immutable approval, concept foreign keys,
provenance, cues, music, review lifecycle, localization safety, deterministic
safety policy, API reads, and validators.

## Q. Formatting and typing

Ruff formatting checked 100 files and lint passed. Strict mypy passed for 71
source files.

## R. Manual page-aware QA

Rendered PDF pages were compared with the first run's stored page passage,
structured ritual, cue timings, music metadata, and 33 safety bindings:

| Selection | PDF/stored page | Structured result | Cue evidence |
|---|---:|---|---|
| Stage 1 Earth | 5 | Earth / `فرود` | 5 cues, 0:40–9:00 |
| Stage 1 Water | 5 | Water / `ورود به جریان` | 5 cues, 0:40–9:00 |
| Stage 1 Fire | 6 | Fire / `جرقه` | 5 cues, 0:40–9:00 |
| Stage 1 Wind | 7 | Wind / `وزش` | 5 cues, 0:40–9:00 |
| Stage 1 Pull | 8 | Pull / `میل` | 5 cues, 0:40–9:00 |
| Stage 1 Return | 8–9 | distinct Return review | 6 cues, 0:45–8:00 |
| Stage 4 Earth | 20 | Earth / `خاک مشترک` | 5 cues, 0:40–9:00 |
| Stage 5 Fire | 26 | Fire / `اوج و اثر` | 5 cues, 0:40–9:00 |
| Stage 6 Pull | 33 | Pull / horizontal relation | 5 cues, 0:40–9:00 |
| Stage 7 Earth | 35 | Earth / `این بودن` | 5 cues, 0:40–9:00 |
| Collective | 40–42 | separate collective architecture | 7 cues, 0:00–24:00 |

The rendered pages confirm optional gaze/movement/voice, distinct presence
without merging, ordinary reorientation, and the final statement that
intensity is not a measure of truth. No page mismatch was found.

## S. Unresolved review items

- `horizontal_emtedad` needs explicit Ayin editorial review before a stable
  concept identity or resolved link is created.
- Between and Life family identities are supported, but this source does not
  define sufficient standalone rituals to populate them.
- Canon approval remains unavailable until editorial identity, authorization,
  and governance are specified.
- Rights, production deployment, backups, privacy, and operational governance
  remain later review items.
- English and Arabic ritual localizations and cross-language semantic safety
  validation remain later work; no translations were generated.
- No preferred Manasek extraction was selected automatically. Both extraction
  runs remain retained for editorial QA.

## T. Working authority confirmation

The imported source and every source-backed ritual version remain
`MANASEK_WORKING` / `draft` (safety-rule versions remain `review`).

## U. Canon confirmation

`MANASEK_CANON = 0` and `AYIN_CANON = 0`. Import and preferred-extraction
decisions do not constitute Canon approval.

## V. Scope confirmation

No Phase 4 external/YouTube ingestion, claims, media, retrieval, embeddings,
RAG, research, lecture, translation-generation, publishing, playback, music
generation, or TTS implementation was introduced.

## Verification commands and observed corrections

The executed command set included:

```bash
docker compose ps --format json
docker compose exec -T db dropdb/createdb ... emtedad_phase3_verify
uv run alembic upgrade head
uv run alembic current
uv run alembic check
uv run alembic downgrade 20260918_0003
uv run ruff format --check .
uv run ruff check .
uv run mypy app tests
uv run pytest tests/unit/ritual tests/importers/test_manasek_pdf_extraction.py -q
uv run pytest tests/integration/ritual -q
uv run pytest -q
docker build -t emtedad-platform:phase3 .
uv run python -m app.cli manasek import docs/source_material/Manasek_V1.pdf
uv run python -m app.cli manasek validate
```

Failures were not hidden:

- The first migration invocation omitted required environment and storage
  settings; it was rerun with the complete test configuration.
- The first downgrade/re-upgrade exposed undeleted PostgreSQL enum types. The
  migration was corrected to reuse shared core types and explicitly drop
  Phase 3 enum types; the full lifecycle then passed.
- The first focused integration invocation omitted `EMTEDAD_DATABASE_URL`; it
  was rerun with the required database configuration and passed.
- `uv run emtedad` is not a packaged script because this repository uses
  `tool.uv.package=false`; the documented `uv run python -m app.cli` entrypoint
  was used instead.
- The container extraction exposed a missing run-specific review flag. The
  importer was corrected and tested so every retained extraction run carries
  the review provenance.
