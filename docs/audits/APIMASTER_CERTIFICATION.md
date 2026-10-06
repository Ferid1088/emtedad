# Audit: APIMaster final quality certification

Date: 2026-10-06 (uncommitted — branch `openrouter-qwen-benchmark`)

Scope: close the remaining certification gaps after the OpenRouter →
APIMaster migration — fail-closed routing, URL-grounded research, real
A/B role certification, Persian premium writing, DE/EN/AR localization
convergence, token/cost calibration, and honest end-to-end evidence.

## Provider and routing

- APIMaster is the only active external LLM gateway. `openrouter.py`,
  `batch.py`, `batch_poller.py` are deleted; the only remaining
  `openrouter` references in the tree are the explicitly historical
  `benchmarks/qwen/` client (not imported by `app/`).
- `resolve_llm_provider` fails closed
  (`app/knowledge/llm/factory.py`):
  - routing enabled + declared role with no model mapping →
    `RoutingConfigurationError`;
  - routing disabled without `allow_devin_runtime_fallback` →
    `RoutingConfigurationError`;
  - no declared role without `allow_devin_runtime_fallback` →
    `RoutingConfigurationError`.
- Every previously role-less production caller now declares an
  `AgentRole` (dialogue classifier → `EVIDENCE_VALIDATOR`, ingestion
  importer paths → `LEGACY_DEFAULT`, etc.). All 36 roles resolve to one
  of the four live-verified marketplace models.
- Devin remains reachable only through explicit opt-in
  (`allow_devin_runtime_fallback=true`) for development/manual use.

## Model certification — live A/B (qwen3.8-flash vs gpt-6.1-sol)

Two loops × five cases × four roles, judged by `gpt-6-astra`
(`benchmarks/pipeline/artifacts/ab_qwen_sol_loop{1,2}_*.json`,
140 recorded calls, `run_scope='ab_test'`):

| role | qwen schema ok | sol schema ok | qwen judge | sol judge |
|---|---|---|---|---|
| TOPIC_MINER | 2/10 | 10/10 | 5.5 / 8.0 / 2.0 (n=1) | 7.4 / 9.1 / 4.0 |
| SEARCH_PLANNER | 10/10 | 10/10 | 6.7 / 7.5 / 8.0 | 8.8 / 9.4 / 9.5 |
| SEARCH_QUERY | 3/10 | 10/10 | ~5.5 / ~5.0 / ~7.0 | ~7.0 / ~7.6 / ~7.5 |
| COUNTERARGUMENT | 5/10 | 10/10 | ~6.0 / ~5.3 / ~7.0 | 9.2 / 9.7 / 9.3 |

(judge columns: content / persian / evidence, averaged over judged cases)

Decision: `qwen3.8-flash` did not certify for any production role —
50 % structured-output reliability, 2–3× latency, lower quality on every
judged axis. `TOPIC_MINER`, `SEARCH_PLANNER`, `SEARCH_QUERY`,
`COUNTERARGUMENT` re-mapped to `PROFESSIONAL_REASONING` (Sol).
`HIGH_VOLUME_REASONING` stays in the enum for a future certified cheap
model; `model_role_high_volume` remains a configurable setting.

Caveat recorded for honesty: the TOPIC_MINER case input contains
strategy + unit counts only, so `supporting_unit_refs` are inherently
unverifiable in both models' outputs — both scored low on
evidence_discipline there (sol 3.4–4.5). This is a case-design
limitation, not a model defect.

## Web research — real URL grounding

- `web_research_provider` default changed `apimaster` → `tavily`;
  `apimaster` remains in the stored value space but is refused at build
  time (`WebResearchError`) — an LLM answer endpoint cannot return
  verifiable source URLs.
- New keyless `wikipedia` backend (`app/web_research/providers.py`):
  MediaWiki `action=query&list=search` with `srprop=snippet`,
  descriptive `EmtedadApp/1.0` User-Agent (required — default httpx UA
  is 403'd), URL construction from titles, dedup, bounded results.
- Live evidence (`benchmarks/pipeline/artifacts/research_loop_*.json`,
  `ops.web_research_runs` ×3, `trigger='certification_loop'`):
  10 findings, all URL-bearing; 10 source rows ingested; second run of
  the same query correctly deduplicated (`status='existing'`).
  Provenance persisted in `result_json`.

## Persian premium writing — Astra certification

Harness `benchmarks/pipeline/astra_persian_writer.py` runs Astra
Semantic Master → Astra full Persian ScriptWriter → Gemini native critic
→ Sol evidence critic → bounded Astra revisions → post-revision critics.
Three real briefs produced complete scripts
(`benchmarks/pipeline/artifacts/astra_fa_*.json`):

| artifact | words | native | evidence |
|---|---|---|---|
| loop1 raw (c98369ea) | 3681 | 5.8 | 9.0 |
| loop2 raw (c3e70292) | 3518 | 6.5 | 9.0 |
| loop2 raw (61d3f6eb) | 3488 | 6.8 | 7.0 |
| loop2 rev1 (61d3f6eb) | 2788 | **8.5** | **9.0** |
| loop2 rev2 | 2700 | 7.8 | 9.0 |
| loop2 rev3 | 2812 | 6.5 | 7.5 |

Findings:

- Raw Astra scripts: clean evidence discipline (7–9) but academic/essay
  register (native 5.8–6.8) — the one-pass writer does not yet produce
  documentary narration quality.
- One targeted revision improves both axes substantially (8.5 / 9.0,
  2788 w ≈ 25.3 min at 110 wpm — inside the 25–30 band).
- Revisions 2–3 **regress**: the reviser injects narrator meta-voice
  («به روایت سخنران»), repeats imagery, drops a caveat, invents
  expansions. The harness now selects the *best-scoring prior revision*
  as the next revision base and tightened the word budget to ±8 %;
  best-of-N retention is essential.
- Baseline comparison (`run_baseline_critics.py`, same critics on the
  owner-approved Persian master `fc62e56f`, same brief):
  native 7.8, **evidence 4.0**, 1312 w ≈ 7 min. The historical approved
  draft predates the fidelity critic — it would fail today's evidence
  and duration gates. This is an owner-review item, not a regression of
  the new pipeline: the new pipeline's best artifact exceeds the
  baseline on both axes and on duration.

## Localization — DE/EN/AR from the shared semantic package

Package `eba81c94` (dry_run lineage Persian draft `07e80bb8` =
Astra revision-1, 2788 w, brief `61d3f6eb`) was used for certification
runs; `package_is_current` was satisfied through the harness gate patch
because dry_run drafts cannot be owner-approved by construction.

Pipeline fixes landed during certification:

- Context-firewall allowlists extended for `duration_contract`;
  `_duration_contract` injected into coverage / reconstruction /
  narrative-edit / correction / premium-final / post-premium payloads —
  writers now receive an explicit spoken-length target
  (25–30 min × language wpm) instead of discovering the band at the
  gate.
- `ProtectedTerminologyValidator`: standalone-word matching with
  Arabic/Persian-aware boundaries (بن inside مبنا, میان "between", جان
  inside unrelated words no longer match), optional `flagged_terms`
  scoping to the package's explicit `protected_terms` +
  `terminology_references` (free-form `localization_notes` excluded);
  unscoped callers (voice prep) keep conservative all-term behaviour.
- Deterministic duration check now runs **inside the review loop**: a
  `DURATION_TOO_SHORT`/`DURATION_TOO_LONG` BLOCKER finding feeds the
  bounded correction (package-only expansion / trim) instead of
  surfacing only at the final gate.
- Exactly one dedicated duration-only repair is allowed when the sole
  remaining blocker is the length contract — once inside the loop
  (past the quality budget) and once after the premium edit at the
  final gate; both re-run the complete verification path afterwards,
  so the repair can never bypass semantic checks.
- The premium final editor's prompt now states spoken length as a
  HARD REQUIREMENT (it compressed an in-band draft below the floor
  despite receiving the contract).
- Shared correction instructions no longer conflict with duration
  repair: when a `DURATION` finding is among the majors, the
  instruction explicitly promotes in-band length to a first-class
  repair target instead of demanding byte-identical preservation
  (the previous wording made `DURATION_TOO_LONG` structurally
  unfixable — observed on every loop of every language).
- Dry-run harness: stage-driven execution, no unconditional premium
  final, honest `BLOCKED` recording, per-run cost isolation.

(Results of the final three-language run — see "Final E2E result"
below.)

## Cost and token calibration

- `app/knowledge/llm/pricing.py` snapshots live marketplace pricing
  from `https://apimaster.ai/api/pricing`; artifacts report provider
  `cost_usd` (ACTUAL) and market-range estimate (MARKET_ESTIMATE)
  separately — never merged.
- Provider-reported `usage.cost`: returned only for `qwen3.8-flash`;
  Sol / Astra / Gemini omit it → recorded `NULL`, never estimated.
- Token-burn audit over `ops.llm_call_events`:
  - Sol and Astra carry a ~4.1–4.4k injected prompt prefix on chat
    calls (Astra route-dependent — a 949-token Astra call exists).
    Mostly cache-served (`cached_tokens` ≈ `prompt_tokens`), but it is
    a hard floor on tiny calls.
  - Gemini passes prompts through cleanly (13 tokens on a trivial call).
  - Qwen: no prefix, but large reasoning/completion burn on trivial
    requests (449 completion tokens) — consistent with its latency and
    failure profile.
- Sol chat-vs-Responses probe
  (`benchmarks/pipeline/artifacts/sol_chat_vs_responses_*.json`):
  identical structured work → chat 4581 prompt tokens, Responses 204.
  Both returned schema-valid output; similar latency. Production stays
  on Chat Completions — Responses is unadvertised for Sol and not a
  stable documented contract. Vetted optimization path for later.
- No batch API (`POST /v1/batches` → 404): all premium work synchronous.

## Final E2E result

Six sequential certification runs were executed on the shared package
`eba81c94` (source: Astra revision-1 Persian draft `07e80bb8`, 2788 w ≈
25.3 min). Iterative pipeline fixes landed between runs; the final two
runs carry the complete code (scoped terminology, in-loop duration
findings, duration-aware correction instructions, bounded duration-only
repairs in-loop and post-premium, hardened premium-editor length
requirement). Artifact: `benchmarks/pipeline/artifacts/dry_run_1791257524.json`
(+ `dry_run_1791258542.json` for the EN retry after a transient 429).

| language | blocker trajectory | terminal state |
|---|---|---|
| DE | 10 → 3 → 3 → 3 → quality clean | BLOCKED — `DURATION_TOO_LONG` at final gate (5103 w = 39.3 min) |
| EN | 8 → 1 → 4 → 2, retry: loop-3 clean then churned | BLOCKED — review budget, fidelity churn |
| AR | 8 → 2 → 2 → 2 | BLOCKED — review budget, `TARGET_ONLY` churn |

Verified-working machinery (live evidence this run):

- In-loop deterministic duration findings fire and get repaired (AR's
  `DURATION_TOO_LONG` resolved by loop 2; DE's in-loop finding resolved
  by loop 2 in the preceding run).
- The post-premium `final_duration_repair` fired live for DE — the
  repair ran and the complete final gate re-ran afterwards (no waiver).
- Scoped protected-terminology validation: zero findings on every
  language and every loop — no false positives, no drift.
- Premium final edit (Astra, synchronous) and final fidelity gate (Sol)
  executed for DE — DE's full quality path converged (fid+nat PASSED).
- The final gate honestly blocked DE's over-band script; no output was
  forced through. EN's first attempt recorded an honest
  `APIMasterRateLimitError` (429 after 2 retries) rather than hiding
  the provider failure.
- Per-run cost isolation: 46 calls, provider cost $0.00 (no model in
  this run reports `usage.cost`), market estimate $2.84–$3.07 — kept
  strictly separate.

Remaining non-convergence is model-side, not gate-side: targeted
corrections fix flagged passages but inject 1–3 new small
embellishments (`TARGET_ONLY`) elsewhere per pass, so the bounded
budget exhausts before all blockers stay simultaneously clean — and
the Gemini writer/editor models cannot reliably land inside the
25–30 min word band (DE over-produced to 39.3 min through both the
writers and the dedicated repair). The architectural fix is
patch-based repair (surgical span replacement instead of whole-script
rewrite) plus a deterministic length loop at the writer boundary —
recorded as follow-up work, not waived.

## Verification

- ruff check / ruff format: clean on the full tree.
- mypy strict: 237 source files + benchmark harnesses, no issues.
- Unit tests: 384 passed.
- Integration tests: 121 passed + 1 updated expectation
  (`test_web_research` now asserts the `tavily` default — intentional
  change); focused web-research integration suite 13 passed.
- Focused validator tests: 16 passed.

## Unresolved risks / owner-review items

- The owner-approved Persian master `fc62e56f` scores evidence 4.0 /
  ~7 min under today's critics — it predates the gates and needs owner
  re-review or regeneration before it can localize honestly.
- Fidelity-correction churn persisted across all languages and runs:
  each bounded repair fixed flagged passages but introduced 1–3 new
  small embellishments elsewhere (TARGET_ONLY at different locations
  each loop). The 4-loop budget is honest but expensive; a diff-based
  repair (patch-only output, not full-script rewrite) is the
  architectural fix for a follow-up phase.
- The writer/editor models cannot reliably hit the spoken-length band:
  German over-produced (39.3 min) through coverage, corrections, and
  even the dedicated duration repair; a deterministic length-check
  loop at the writer boundary is the follow-up fix.
- Sol hit one transient 429 under sequential certification load
  (bounded retries exhausted; recorded honestly as a rate_limit
  event, EN retried separately).
- Astra revision passes 2+ regress — the harness keeps the best
  revision; production revision loops should adopt the same
  best-of-N retention rather than chaining latest→next.
- Sol `/v1/responses` avoids the ~4.4k prefix (204 vs 4581 prompt
  tokens) but is unadvertised — adopt only after a stability contract
  exists.
- `run_scope` vocabulary (`production` / `localization` / `dry_run` /
  `ab_test` / `certification`) is consistent but informal — worth
  pinning as an enum in a cleanup phase.
