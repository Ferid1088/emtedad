# Audit: Master cost-quality content pipeline (Persian owner-approved master → native DE/EN/AR)

> HISTORICAL — OpenRouter-era audit (2026-10-04). APIMaster became the
> canonical external LLM gateway on 2026-10-05; OpenRouter models, batch
> mode, and costs recorded here are provenance, not active configuration.

Date: 2026-10-04 (worktree, uncommitted — branch `openrouter-qwen-benchmark`)

## Scope delivered

Quality-first, cost-optimized multi-model production over OpenRouter,
preserving the existing architecture and the invariant that **the Persian
script is the owner-approved master** for every target language.

## Architecture evidence

- `app/knowledge/llm/openrouter.py` — production `LLMProvider` over
  OpenRouter chat completions: strict JSON-schema `response_format`
  (`strict_response_format`, shared by sync and batch paths), Pydantic
  validation, one bounded in-conversation schema repair, typed errors
  (auth/model/quota/rate-limit/timeout/transport/malformed/schema/
  upstream), bounded retries on transient statuses, provider-reported
  telemetry only.
- `app/knowledge/llm/roles.py` + `factory.py` — `AgentRole` → `ModelRole`
  → configured model ID. `resolve_llm_provider(role=…, effective=…)`
  routes to OpenRouter only when `llm_routing_enabled` is true (owner
  DB override via `StudioSettingsService.effective()`); otherwise the
  Devin provider is returned unchanged. Synchronous premium calls are
  refused while `premium_execution_mode=batch` — no silent standard-mode
  billing. Model IDs live in `Settings`/owner settings, never in domain
  code.
- `app/knowledge/llm/batch.py` + `batch_poller.py` — durable
  `ops.provider_batch_jobs`, deterministic `request_hash` idempotency,
  truthful status mapping (`validating`/`in_progress`/terminal states),
  eventual-consistency-tolerant polling, background poller wired into the
  FastAPI lifespan and gated by `background_processing_paused`.
- `app/knowledge/llm/context.py` — per-role payload allowlists, forbidden
  credential keys, serialized secret scanning (OpenRouter keys, bearer
  tokens, PostgreSQL URIs, configured extra secrets) invoked immediately
  before every provider call.
- `app/knowledge/llm/models.py` + migration `l4d5e6f7g8h9` —
  `ops.llm_call_events` (provider-reported tokens/cost/latency/retries/
  schema repairs, agent role, task, prompt version, language, brief,
  batch link, run scope) and `ops.provider_batch_jobs`.
- `app/localization/gate.py` — `approved_persian_draft`,
  `require_approved_persian_draft`, `package_is_current`: localization may
  start only from the *latest* APPROVED primary Persian `ScriptDraft` of a
  brief with recorded `approved_by`; staleness (unapproved, hash mismatch,
  newer approved version) blocks entry points and marks runs
  `STALE_SOURCE`.
- `app/localization/semantic_package.py` — one shared
  `LocalizationSemanticPackage` per approved draft via the reasoning role;
  deterministic validation (no unknown/missing claims, no epistemic
  drift), hash/provenance/prompt-version persistence, staleness sweep.
- `app/localization/native_pipeline.py` — staged run per language:
  coverage translation → native reconstruction → narrative edit →
  native-spoken + audience-retention critics (editorial role) → fidelity
  critic (reasoning role) → bounded targeted repair (≤3 loops, may never
  add claims or certainty) → premium final editor (Astra via batch or
  standard) → final fidelity gate → deterministic native-quality +
  duration gates → `READY_FOR_VOICE` / `BLOCKED`. Localized texts persist
  as `ScriptDraft` with `lineage="localized"`, reusing review/duration
  machinery; intermediate artifacts live in `run.work_json`.
- `app/localization/native_quality.py` — deterministic pre-semantic
  checks: U+FFFD, disallowed Cf controls (ZWNJ allowed for Persian),
  internal-phrase leakage, duplicate paragraphs/sentences, dominant-script
  sanity, duration band from `speech_wpm()`.
- Studio (`studio_routes.py`, `brief_workspace.html`) — per-language
  pipeline truth (stage, loops, fidelity/native status, error), batch job
  state, and actual provider-reported cost/token totals per language.

## Live canary evidence (real OpenRouter calls)

Smoke (`benchmarks/pipeline/artifacts/smoke_1791208927.json`): all four
model families answered twice — qwen ~$2e-5/call, gpt-6.1-sol ~$4.9e-4,
gemini-3.8-flash ~$4.4e-4, gpt-6-astra ~$2.4e-3; native DE/EN/AR/FA calls
via the editorial model all succeeded. Batch API verified end-to-end:
submit → `validating` → `in_progress` → `completed` with per-request
results at `response.body.choices[].message.content` and provider-reported
`usage.cost` (~half standard pricing).

Real dry-run on a real approved Persian master
(`benchmarks/pipeline/artifacts/dry_run_1791211658.json`,
`run_scope='dry_run'`):

- Semantic package built by Sol from the approved History master
  (`1b60659f` v1).
- German: coverage → native draft → 3 review loops (fidelity FAILED →
  corrected → PASSED) → Astra **batch** premium edit (`batch-1791210015`,
  COMPLETED, provider cost $0.14053) → final fidelity gate **BLOCKED** on
  real target-only semantic additions the premium editor introduced
  ("Daseinsberechtigung verdienen", unsupported prevalence claims).
  The gate refused to ship drifted content — by design.
- English: 3 bounded review loops did not converge (persistent
  TARGET_ONLY blockers incl. a leaked editorial bracket) → pipeline
  stopped without producing a premium final — honest bounded failure, no
  forced pass.
- Arabic: stopped mid-run on `quota` (OpenRouter credit exhaustion) —
  typed error, clean stop.
- Totals: 46 recorded calls, $1.6186 provider-reported cost.

## Security / integrity

- Two secret scans: zero real-key occurrences in the full diff, benchmark
  artifacts, `llm_call_events`, `provider_batch_jobs` request/result
  payloads, or pipeline `work_json`.
- Context firewall unit tests cover allowlist rejection, forbidden keys,
  serialized secret detection.
- Owner-state integrity: all `fa`/`primary` drafts unchanged (approved
  History master `fc62e56f` still APPROVED, hash `b6f53e8b…`); dry-run
  rows are additive `localized`-lineage drafts and `dry_run`-scoped
  telemetry. Psychology/History primary states untouched.

## Verification results

- ruff check/format: clean on changed scope (pre-existing historical
  migration lint issues untouched, as on baseline).
- mypy strict: 232 app source files, no issues.
- Unit: 386 passed (44 new: provider, batch, routing, firewall,
  native quality, semantic package).
- Integration: 122 passed incl. `test_localization_gate.py`
  (gate, staleness, package, pipeline e2e) and the pre-existing
  localization duration suite.
- Migration `l4d5e6f7g8h9`: upgrade → downgrade → upgrade verified on
  PostgreSQL; all four new tables + enum values confirmed by inspection.

## Known limits / review items

- Critics are strict on first contact: DE/EN dry runs ended BLOCKED after
  bounded loops — expected gating behaviour, but per-language convergence
  tuning (e.g. repair-prompt calibration) is an owner-visible knob for a
  follow-up.
- AR dry run needs a rerun once OpenRouter credits are replenished.
- Batch jobs currently have no owner-facing manual retry/escalation
  action; `OWNER_ACTION_REQUIRED` surfaces in Studio as state only.
- `run_scope` taxonomy: `production` / `localization` / `dry_run` /
  `semantic_package` — consolidate if a stricter vocabulary is wanted.
