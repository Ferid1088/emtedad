# Audit: OpenRouter → APIMaster gateway migration

Date: 2026-10-05 (uncommitted — branch `openrouter-qwen-benchmark`)

## Decision

APIMaster is the canonical external LLM gateway. OpenRouter is retired
from all active runtime paths; its artifacts remain as historical
provenance only. No commit, no push — owner review checkpoint.

## Live capability evidence (GET /v1/models + probes)

- `GET /v1/models` → HTTP 200, 76 models; all four required IDs present.
- `POST /v1/chat/completions` → HTTP 200 for `qwen3.8-flash`,
  `gpt-6.1-sol`, `gemini-3.8-flash`, `gpt-6-astra`.
- `POST /v1/responses` → responds for `qwen3.8-flash`/`gpt-6.1-sol`
  (gateway shim; production path uses chat completions).
- `POST /v1/batches` → HTTP 404 `Invalid URL` — **no batch API**.
- Structured output: Qwen/Sol/Astra honor strict `json_schema`;
  `gemini-3.8-flash` ignores `json_schema` (returns prose) — handled via
  `json_object` mode + schema-in-prompt + Pydantic validation + one
  bounded repair.
- Usage: `usage.cost` returned for `qwen3.8-flash`; Sol/Astra/Gemini omit
  it (NULL — never estimated). `cached_tokens` under
  `prompt_tokens_details`; `reasoning_tokens` under
  `completion_tokens_details` when the gateway reports them.
- Request identity: `x-request-id` header / body `id`.
- Unknown model → HTTP 503 `error.code=model_not_found`
  (`new_api_error`) — classified non-retryable despite 5xx.
- No upstream-route/fingerprint fields are exposed by the gateway.

## What changed

- `app/knowledge/llm/apimaster.py` — provider: typed errors (auth /
  model_not_found / rate_limit / quota / timeout / transport / malformed
  / schema), bounded retries on classified kinds, one schema repair,
  provider-reported usage only, secret-free diagnostics.
- `app/core/config.py` — `apimaster_*` settings + bare marketplace model
  IDs as role defaults; `web_research_provider` defaults to `tavily`
  (`apimaster` remains in the value space but is refused as a retrieval
  backend — an LLM answer endpoint cannot return verifiable source URLs).
- `app/knowledge/llm/factory.py` — role routing produces APIMaster
  providers and fails closed: routing enabled + unmapped role →
  `RoutingConfigurationError`; routing disabled or no role without
  `allow_devin_runtime_fallback=true` → `RoutingConfigurationError`.
  Devin is an explicit opt-in, never a silent fallback.
- `app/knowledge/llm/openrouter.py`, `batch.py`, `batch_poller.py` —
  deleted.
- `app/knowledge/llm/models.py` — `LLMCallEvent` only; `ProviderBatchJob`
  and `batch_job_id` removed (never committed).
- `app/localization/` — premium final edit runs synchronously; batch
  stages (`PREMIUM_FINAL_PENDING/RUNNING`), `batch_job_id`, and
  `resume_after_batch` removed.
- `app/web_research/providers.py` — retrieval backends are `tavily`,
  `custom`, and a keyless `wikipedia` adapter (MediaWiki
  `action=query&list=search`, descriptive `EmtedadApp` User-Agent,
  URL-bearing findings). `apimaster` is refused at build time:
  an LLM synthesis endpoint cannot provide verifiable URLs.
- `app/main.py` — batch poller removed from the lifespan.
- `app/ops/settings/service.py` — `premium_execution_mode` retired; model
  role keys remain owner-editable.
- `app/web/templates/studio/` — settings options + placeholders migrated;
  batch-job panel removed from the brief workspace.
- `alembic/versions/l4d5e6f7g8h9_*` — the (never committed) migration no
  longer creates `ops.provider_batch_jobs`, `batch_job_id` columns, or
  the batch pipeline stage values.
- `benchmarks/qwen/` — marked HISTORICAL (OpenRouter provenance only).
- `benchmarks/pipeline/run_smoke.py` / `run_dry_run.py` — migrated to
  APIMaster; batch canary replaced by a recorded `NOT_AVAILABLE` fact.

## Retired requirements

- `EMTEDAD_OPENROUTER_API_KEY` and every `openrouter_*` setting: gone —
  zero active runtime references. A stale key may remain in a local
  `.env`; it is inert (`extra="ignore"`).

## Honest limitations

- `gemini-3.8-flash` structured output is weaker than strict-schema
  models: `json_object` mode plus schema-in-prompt, enforced by Pydantic
  + repair. If a model-family change is needed, it is a one-line
  configuration change (`json_object_models`).
- Only `qwen3.8-flash` reported `usage.cost` in probes; other models'
  `cost_usd` remains NULL rather than estimated.
- Web research via APIMaster returns a synthesized answer but **no
  `url_citation` annotations** (verified live: `findings: 0`). APIMaster
  chat models have no provider-verified web grounding, so the `apimaster`
  research adapter produces zero ingestible source URLs — answer text is
  never promoted to evidence. Retrieval now runs through `tavily`
  (default), `custom`, or the keyless `wikipedia` backend — verified
  live: two certification loops returned 10 URL-bearing findings and
  ingested 10 sources (`benchmarks/pipeline/artifacts/research_loop_*.json`,
  `ops.web_research_runs` rows).
- `gpt-6.1-sol` answers `POST /v1/responses` live (not advertised on
  `GET /v1/models` except for `qwen3.8-flash`). A chat-vs-Responses
  probe showed Responses avoids the ~4.4k injected prompt prefix
  (204 vs 4581 prompt tokens on identical structured work, schema OK
  both ways). Production stays on Chat Completions — Responses is
  undocumented and not advertised as a stable contract; it is a vetted
  optimization path for a later phase.
- `qwen3.8-flash` did not certify for any production role: live A/B
  (2 loops × 5 cases × 4 roles, Astra judge) showed 50% structured-output
  success vs Sol's 100%, 2-3× latency, and lower judged quality on every
  role (`ab_qwen_sol_loop{1,2}_*.json`). TOPIC_MINER / SEARCH_PLANNER /
  SEARCH_QUERY / COUNTERARGUMENT now route to `model_role_reasoning`
  (Sol); `HIGH_VOLUME_REASONING` remains for a future certified model.
- Sol/Astra responses carry a ~4k-token gateway-injected prompt prefix
  on chat calls (observed in `prompt_tokens`; Astra route-dependent).
  It is mostly cache-served (`cached_tokens` ≈ `prompt_tokens`), but
  sets a hard token floor on tiny calls. Gemini passes through cleanly
  (13 tokens on a trivial call); Qwen has no prefix but burns
  substantial completion/reasoning tokens on trivial requests.

## Evidence

- `benchmarks/pipeline/artifacts/smoke_*.json` — 16 live calls, all ok.
- `benchmarks/pipeline/artifacts/dry_run_*.json` — full DE/EN/AR native
  pipeline runs with real telemetry.
- Unit: `tests/unit/test_apimaster_provider.py`, `test_llm_routing.py`,
  `test_web_research.py`. Integration: `test_localization_gate.py`,
  `test_web_research.py`.
