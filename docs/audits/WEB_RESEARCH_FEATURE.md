# Web Research + Duration-Gap Fill — Audit

> HISTORICAL — written before the APIMaster migration (2026-10-05). The
> `openrouter` provider described below was replaced by `apimaster`; the
> text records the original design.

Date: 2026-10-03
Scope: owner-configurable internet research, 20–25-minute material rule.

## What was built

### Provider-agnostic web research (`app/web_research/`)

- `providers.py` — three adapters behind one protocol:
  - `openrouter`: chat-completions API (any compatible endpoint); URL
    citations are read from message `annotations[].url_citation`. The model
    must have web access (e.g. OpenRouter's `:online` suffix).
  - `tavily`: `POST /search` returning `{answer, results[]}`.
  - `custom`: `POST {query, context, max_results}` to the configured URL;
    parses `results`/`items`/`data`/`findings` lists and `url`/`link`/`href`
    fields, plus bare-list payloads.
- `service.py` — fetches each result URL, extracts text via a minimal
  stdlib HTML parser, and ingests pages through the canonical
  `import_web_resource()` path. Pages under 200 chars or non-text content
  types are skipped with a failure record, not an exception.
- `domain.py` — `WebFinding`, `WebResearchReport`, `IngestedWebSource`.
- `gap_fill.py` — `GapFillService.assess()` counts the topic candidate's
  grounded units vs `ceil(target_duration_minutes * units_per_video_minute)`;
  `fill_gap()` runs up to 3 queries (question, thesis-as-evidence-search,
  recorded `knowledge_gaps`), ingests results into the brief's channel, and
  optionally drives `SourceProcessingService` inline so new units are linked
  back to the candidate immediately.

### Provenance rule (non-negotiable)

Only fetched page text becomes `SourceSegment.raw_text` — the provider's
synthesized answer is stored in `Source.raw_metadata["research_answer"]`
and `SourceVersion.provider_metadata` for provenance, never as evidence.
`SourceQuality.primary_or_secondary = "secondary"`,
`publication_type = "web_research"`; corpus zone stays `EXTERNAL_PRIMARY`
(the only zone `source_versions` accepts; the primary/secondary split lives
on `SourceQuality`).

Dedup: `external_id = sha256(canonical_url)[:48]` on `platform="web"`.

### Owner settings (`app/ops/settings/`)

- `ops.owner_settings` table (migration `g8a9b0c1d2e3`): `key` unique,
  `value` JSONB, `updated_by`/`updated_at`.
- `StudioSettingsService`: effective = DB override → env default; typed
  coercion via an explicit `_KEY_TYPES` map (bool/int/float/str); `None`
  deletes the override.
- Editable keys: `web_research_enabled`, `web_research_provider`,
  `web_research_base_url`, `web_research_api_key`, `web_research_model`,
  `web_research_max_results`, `web_research_timeout_seconds`,
  `target_duration_default_minutes`, `target_duration_min_minutes`,
  `target_duration_max_minutes`, `units_per_video_minute`.
- Env names: `EMTEDAD_WEB_RESEARCH_*`, `EMTEDAD_TARGET_DURATION_*`,
  `EMTEDAD_UNITS_PER_VIDEO_MINUTE`, `EMTEDAD_WEB_RESEARCH_MAX_PAGE_BYTES`.

### UI

- `/settings` — "Internet-Recherche" card (toggle, provider select,
  base URL, model, masked API key, max results, timeout) + "Video-Länge"
  card (default/min/max minutes, units-per-minute estimate). Empty fields
  fall back to env defaults; masked key is not overwritten on re-save.
- `brief_workspace` — "Material" row shows gap badge
  (`Lücke: n/m Units` / `Ausreichend`); when a gap exists and research is
  enabled, an "Im Internet recherchieren" button posts to
  `/studio/production/{id}/web-research` and redirects back with a German
  notice.
- Automatic gap fill runs before `plan_research` and `build_evidence`
  actions (only when the toggle is on and material is insufficient).
- Brief creation clamps duration to the configured min/max; default 22.

## Test coverage

- `tests/unit/test_web_research.py` (10) — provider parsing with
  `httpx.MockTransport`, error paths, `html_to_text`.
- `tests/integration/test_web_research.py` (12) — settings service
  round-trip/coercion/delete, `import_web_resource` (dedupe, provenance,
  URL validation, answer-not-in-segments), gap assess/fill/link with a
  stub research service.
- `tests/integration/test_studio_ui.py` (+3) — settings page round-trip
  incl. masked-key preservation, 22-minute default, gap badge and
  button visibility.

## Verification

- `ruff check` / `ruff format --check` — clean on all touched files.
- `mypy --strict` — clean on `app/web_research`, `app/ops/settings`,
  `file_import.py`, `studio_routes.py`.
- Migration: applied `g8a9b0c1d2e3` to dev DB; autogenerate shows no drift
  from `owner_settings` (only the pre-existing `speech_sections` index
  drift).
- Full suite: 368 passed; 4 deselected pre-existing/environmental
  (2 migration-drift foundation tests, live-DB Persian diacritic,
  provider-dependent topic batch).

## Known limitations / risks

- Inline processing inside the HTTP request can take minutes when
  `process_inline=True` — acceptable for an owner tool; a background job
  would need scheduler work.
- OpenRouter citations depend on model support for `:online`/web plugins;
  if the model returns no annotations, nothing is ingested (outcome shows
  0 sources, no error).
- No SSRF guard on the custom provider URL or fetched result URLs —
  owner-configured feature, but a URL allowlist may be worth adding.
- `units_per_video_minute = 1.5` is a heuristic; tune per channel after
  observing real productions.
