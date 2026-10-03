# Owner Workflow & UI Product Sprint

Baseline commit: `cf39c90` (`feat: improve structured knowledge quality and retrieval`).
Branch: `fix-speech-structure-generation`. No commit made — sprint stops for owner review.

Scope: turn the working backend into a clear owner application. No knowledge
architecture, retrieval, or pipeline changes.

## Routes

### Existing routes kept unchanged

- `GET /studio/channels`, `GET /studio/channels/{slug}/strategy`,
  `GET /studio/channels/{slug}/resources`, `GET /studio/channels/{slug}/topics`
- `POST /studio/channels/{slug}/resources` (assign),
  `POST /studio/channels/{slug}/resources/{source_id}/unassign`
- `POST /studio/channels/{slug}/topics/mine`,
  `POST /studio/channels/{slug}/topics/{candidate_id}/status`
- `POST /library/import`, `POST /library/{source_id}/assign`
- `GET /library/{source_id}/structure`, `POST /library/{source_id}/structure`
- `GET /library/{source_id}/units`, `POST /library/{source_id}/units`
- `POST /library/{source_id}/concepts`
- `GET /studio/search`, `GET /analytics`, `GET /settings`
- `POST /studio/production/{brief_id}/actions/{action}`,
  `POST /studio/topics/{candidate_id}/brief`

### Routes added or materially reworked

| Route | Change |
| --- | --- |
| `GET /studio` | Now an attention dashboard: resources needing review/failed, active productions with derived stage + allowed actions, recent approvals (signatures), real channel counts |
| `GET /studio/channels/{slug}` | Four areas: strategy card, recent resources with unit/concept counts and processing state, topic pipeline counts + top candidates, production queue with stage/blockers |
| `GET /studio/channels/{slug}/topics?status=` | Status filter chips; rows link to topic detail; manual question form |
| `GET /studio/channels/{slug}/topics/{candidate_id}` | NEW — topic detail: question/thesis/angle, score grid, knowledge support (units, concepts, sources), knowledge gaps, distinctiveness verdict + overlap report, status + create-brief actions; scoped 404 for foreign channels |
| `POST /studio/channels/{slug}/topics/manual` | NEW — owner-entered candidate via `TopicService.create_manual`; scores stay 0.0 (honest, not fabricated) |
| `POST /studio/channels/{slug}/strategy/draft` | NEW — creates DRAFT version cloning active; optional new core question |
| `POST /studio/channels/{slug}/strategy/{version_id}/activate` | NEW — activates draft, archives previous ACTIVE; cross-channel version IDs return 404 |
| `GET /studio/channels/{slug}/production` | NEW DATA — real brief productions with derived stage, blockers, allowed actions; approved split out |
| `GET /studio/channels/{slug}/published` | NEW DATA — ScriptSignature memory (question, thesis, angle, hash, approved date) + publication targets |
| `GET /library?q=&source_type=&status=` | NEW — search (title/URL/external ID) + type + status filters; per-source unit/concept/processing columns |
| `GET /library/{source_id}` | Reworked to Overview tab: metadata, journey stepper (segments → structure → units → concepts with real counts), channel assignments, versions, review-warning count |
| `GET /library/{source_id}/original` | NEW — transcript moved out of overview; shows sequence span for non-timed sources |
| `GET /library/{source_id}/concepts` | NEW — canonical concepts with linked-unit counts, confidence range, cross-source reuse |
| `GET /library/{source_id}/processing` | NEW — five owner-readable stages (Transcript/Vortragsstruktur/Units/Concept Mapping/Retrieval Index) derived from persisted artifacts, warnings (oversized SUMMARY, UNKNOWN claim types, unmapped units, last error), retry/reprocess actions |
| `GET /production` | NEW DATA — brief productions table (question, channel, stage, status, blockers, actions) + legacy lesson-era projects under "Historical productions" |
| `GET /studio/production/{brief_id}` | Enriched — brief fields (audience, concepts, required evidence, forbidden claims), artifact readiness, ScriptSignature panel after approval, `localize` action wired to `LocalizationService` |

## Screens

- Studio home answers "what needs my attention" with real counts only
- Channel switcher cards show real resource/topic/production/published counts
  (service now queries TopicCandidate, ContentBrief, ScriptDraft, ScriptSignature)
- Resource journey is a visible stepper; every step links to a real tab
- Units show epistemic status (computed deterministically) and SUMMARY demotion
- No fake dashboard values, no decorative charts, no vanity metrics

## Owner journey (real data)

Walked against the live database (166 sources):

1. `/studio` — five channels, attention list (9 real review/failed states),
   1 active production, recent approvals
2. `/studio/channels/emtedad` — strategy card, resources with units/concepts,
   topic pipeline counts, production queue
3. `/library` — filters and search work on all 166 sources
4. `/library/{id}` (Brené Brown TED, `a09b3bd1…`) — overview with journey counts;
   assigned to emtedad + pop-psychology-relationships + psychology-evolution
5. `/original` — timestamped transcript; `/structure` — tree;
   `/units` — units with atomic chips and epistemic status;
   `/concepts` — 130 concepts (vulnerability, shame, wholeheartedness, …);
   `/processing` — all five stages Ready
6. `/studio/channels/emtedad/topics` — 17 mined candidates; detail page shows
   scores, supporting units/sources, gaps, distinctiveness ACCEPT
7. `/studio/production/{brief_id}` — stage stepper, artifact readiness,
   signature panel after approval
8. Strategy page — draft creation POST verified (v2 created, then cleaned up);
   activation verified in tests (archives previous active, cross-channel 404)

## Cross-channel UX

The Brené Brown source renders three channel badges on one Source record;
channel topic lists remain isolated (foreign candidate → 404); production
queues are per-channel via `ContentBrief.editorial_channel_id`.

## Bugs found and fixed

- `localize` was emitted by `ProductionService._allowed` but had no handler →
  wired to `LocalizationService.create` with the latest ready master
- `/production` listed only legacy lesson-era projects → now shows real brief
  productions with derived stage
- Channel cards showed hardcoded 0 for topics/productions/published → real
  grouped counts in `channel_summaries`
- `/library` had no search/filter despite spec → added q/type/status filters
- Resource detail mixed transcript with metadata → split into Overview +
  Original; added Concepts and Processing tabs (both were GET-inaccessible)
- Strategy page exposed no actions → draft create + activate POST routes,
  draft panel, gated by status
- Global nav had a stray "Search" item → removed to match the 7-item spec

## ORM/query notes

- All list loaders batch: `_source_stats` (units, concepts, processing state)
  and `_brief_states` (derived `ProductionState` per brief)
- Topic detail uses `selectinload` for units and `concepts → concept` — no
  detached lazy loads
- No N+1 introduced; every list route groups/counts in SQL

## Action gates

- Production actions render only from `state.allowed_actions` (persisted-artifact
  derivation); blockers suppress `approve` per existing service rule
- Strategy: draft creation always allowed; activation only on DRAFT rows;
  version must belong to the URL channel
- Topics: status dropdown limited to legal transitions; brief creation rejects
  REJECTED/ARCHIVED candidates server-side
- Resource processing actions are idempotent (re-run is safe; dedup constraints
  on units/concepts already exist)

## Tests

- `tests/integration/test_studio_ui.py`: +2 tests (resource tab family,
  topic detail + cross-channel 404 + manual topic; strategy draft/activate/archive +
  foreign-version 404). Suite now 8 tests.
- Full run: `tests/unit` + `test_studio_ui` + `test_topics` +
  `test_generic_e2e` = **279 passed**
- `ruff check`, `ruff format --check`, `mypy --strict app` (206 files) — all clean

## Remaining product gaps

- `/knowledge` remains the legacy knowledge browser (fine as exploratory view;
  not re-built this sprint)
- Stage-level artifact inspection inside the production workspace is summary-level
  (artifact existence + status); deep drill-down into evidence matrix cells,
  narrative beats, and critic findings is a follow-up
- Strategy editing is limited to core question at draft creation; full policy
  field editing is not yet a form
- No HTMX — every action is a full POST + redirect; acceptable for owner scale
- Analytics page shows internal counts only (correct per spec); external
  platform metrics are not connected
- Import accepts YouTube URL only; PDF/book/web import forms are future work
  (the underlying pipeline is already non-timed-source capable)
