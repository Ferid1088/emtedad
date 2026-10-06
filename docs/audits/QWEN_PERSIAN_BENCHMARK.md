# Qwen Persian Benchmark — qwen/qwen3-235b-a22b-2507 via OpenRouter

> HISTORICAL — recorded before the APIMaster gateway migration
> (2026-10-05). The `benchmarks/qwen/` harness is retired; OpenRouter
> results below are provenance only.

- **Baseline commit:** `7c0d5d2859d6f046da159c86d489b6d3b3e572b5` (branch
  `openrouter-qwen-benchmark`, created from the verified baseline)
- **Model:** `qwen/qwen3-235b-a22b-2507` (Instruct, 262 144 ctx,
  `response_format`/`structured_outputs` supported per `/models`)
- **Date:** 2026-10-05
- **Harness:** `benchmarks/qwen/` (benchmark-only; no production routing
  change, no commits). Artifacts: `docs/audits/qwen_benchmark/`
  (`telemetry.jsonl`, `raw/`, per-loop JSON, scorecards).
- **Key:** read from `.env` `Emtedad_OPENROUTER_API_KEY` (existing
  OpenRouter var; project convention `EMTEDAD_*` is case-insensitive in
  pydantic-settings). Key never logged/stored; absence verified.
- **Existing OpenRouter support:** PARTIAL — `app/web_research/providers.py`
  has an `_OpenRouterProvider` for web research only (annotations-based);
  no general chat/structured-extraction client existed. The benchmark
  client (`benchmarks/qwen/client.py`) does not duplicate production code;
  it is a benchmark adapter implementing `LLMProvider`.

## Methodology

- Short form: 2 independent loops × 12 Persian cases mirroring real task
  categories; deterministic checks (`PersianDraftQualityValidator`,
  `PersianNativeReviewer`, Unicode/Cf/U+FFFD, repetition) plus an
  **independent** scorecard from the production critic provider (Devin
  Cloud) — Qwen never scored itself.
- Long form: the **real** `ScriptService.build_script` path with a
  benchmark provider — identical payload (brief, Semantic Master,
  sections/claims, duration contract, WPM, voice contracts, book-ref
  selection). Benchmark drafts were deleted after capture; no owner state
  touched. Critics: all five LLM critic roles via the **Devin** provider
  plus the deterministic gates; the same roles also ran via Qwen to assess
  Qwen-as-critic.
- Blind A/B: anonymized Qwen draft vs baseline production draft, judged by
  the production critic on 7 axes.
- Failure loop: missing key, invalid model, malformed body, empty choices,
  timeout, 429 bound — mocked transport plus two real invalid-model calls.

## Short-form Loop 1 (independent critic, mean 1–10)

| dimension | mean | min |
|---|---|---|
| naturalness | 6.2 | 5 |
| spoken_fluency | 5.6 | 4 |
| grammar | 7.7 | 6 |
| idiomatic_vocabulary | 5.2 | 4 |
| semantic_correctness | 8.2 | 8 |
| terminology | 7.0 | 6 |
| nuance | 7.6 | 6 |
| epistemic_honesty | 8.3 | 7 |
| instruction_following | 8.7 | 7 |
| repetition_freedom | 7.8 | 7 |
| native_not_translated | **4.5** | 3 |
| attribution_discipline | 8.4 | 8 |

Findings: translation-flavored register when prompts did not explicitly
demand colloquial speech; markdown asterisks leaked into spoken text
(`*شبکه‌ای از عوامل*`, `*1984*`); one untranslated English token
(`«-threatening»`); calques (`آبمیوه‌های یخی` for ice-cream example);
dubious coinage (`نگرش گنایی`); ASCII quotes instead of `«»`.

## Short-form Loop 2 (independent critic, mean 1–10)

| dimension | mean | min |
|---|---|---|
| naturalness | 7.7 | 6 |
| spoken_fluency | 7.8 | 7 |
| grammar | 7.8 | 6 |
| idiomatic_vocabulary | 7.2 | 6 |
| semantic_correctness | 8.0 | 6 |
| terminology | 7.5 | 6 |
| nuance | 8.0 | 6 |
| epistemic_honesty | 8.6 | 7 |
| instruction_following | 8.7 | 6 |
| repetition_freedom | 7.8 | 7 |
| native_not_translated | 7.2 | 6 |
| attribution_discipline | 8.8 | 7 |

Findings: register strongly prompt-sensitive (asking for colloquial speech
works); still leaks `*italics*` around book titles; micro-glitches in
spoken register (`همه میرن یا میرن` for «می‌میرن», `عادت آدم‌نواز`);
one invented personal anecdote; one pedantic unprompted correction
(Rome east/west). Perfect quote-refusal case (s2-10). Correct book
attributions (Sapiens/انسان خردمند, The Body Keeps the Score + real
criticism). No invented quotes in either loop.

**Short verdict:** usable Persian with epistemic discipline, but NOT
reliably native-sounding; translation-like register is systemic unless the
prompt forces spoken style; formatting leakage is systemic.

## Long-form Loop 1 — psychology-evolution (`61d3f6eb`)

- Words **1250** → **11.4 min** vs 25–30 contract; `generation_validation:
  FAILED` (`DURATION_BELOW_GENERATION_BAND`,
  `NARRATIVE_STRUCTURE_COLLAPSED`) after 2 corrections.
- Deterministic Persian gate: `ROBOTIC_SENTENCE_SYMMETRY` (repeated
  sentence openings), no encoding corruption.
- Devin critics: **28 findings — 1 BLOCKER** (internal contradiction in
  shame framing), ~15 WARNING (adaptationism/just-so-story upgrades,
  correlational→mechanistic overclaim, individual-differences erasure,
  invented physiological detail), INFO rest.
- Qwen critics (same draft): 16 findings, 2 BLOCKER; misses FACT and
  CHANNEL_SPECIFIC returned empty in 3–4 s (shallow review signal).
- Blind A/B vs baseline v8 (2987 w): **baseline wins all 7 axes** — judge:
  "A is fluent but generic … asserts claims flatly … B anchors every
  strong claim to Brené Brown's actual research … flagging her statistics
  as her own claim".

## Long-form Loop 2 — history-human-stories (`c3e70292`)

- `book_reference_selection` returned a bare list → schema-invalid,
  repair failed → degraded to zero references (pipeline degraded as
  designed).
- First `script_draft` returned `script`/`duration_estimate_minutes`
  instead of schema fields — repaired once → **813 words = 7.4 min**.
- Both corrections returned `corrected_script` — including after an
  explicit repair prompt; `build_script` raised, transaction rolled back,
  no draft persisted. The repaired first draft was evaluated in replay.
- Devin critics: **27 findings — 1 BLOCKER** (`SOURCE_CONFLICT`:
  «خوک و شغال» — invented animal specifics not in sources), 13 WARNING
  (timeline compression, anachronistic «حقوق انسانی», causal overclaims,
  ANECDOTAL evidence oversold as fact).
- Qwen critics: 25 findings, **7 BLOCKER** — harsher, same substance
  (Wari'/San sourcing, oxytocin overclaim) but code taxonomy sloppier
  (`BOOK_REFERENCE_UNVERIFIED` used for non-book claims).
- Blind A/B vs baseline v11 (2621 w): **baseline wins all 7 axes**.
- Prose quality of the fragment itself is decent and epistemically hedged
  — the failure is length/fidelity, not fluency per se.

## Structured-output reliability

| task | calls | schema-valid first try |
|---|---|---|
| small classifications (structured_output cases) | 6 | 6/6 |
| agent tasks (A–D) | 6 | 6/6 |
| `book_reference_selection` | 2 | 1/2 |
| `script_draft` (long) | 2 | 1/2 |
| `script_generation_correction` | 3 | 0/3 |

Pattern: field-name drift on *long* payloads (`corrected_script`,
`script`, `duration_estimate_minutes`, bare list) — the model follows
task wording over schema field names. Strict `json_schema` is not
reliably enforced through the routed upstreams. One in-conversation
repair fixed 1/5 cases. **Qwen must not be used for schema-critical
agents without a tolerant/repairing wrapper.**

Epistemic classification calibration is imperfect: quantum-mechanics
statement labeled `SPECULATION` (should be `ESTABLISHED_SCIENCE`);
`CONTESTED` chosen where `LIMITED_EVIDENCE` fit better; 3/3 correct on
clearly-worded second batch.

## Agent-suitability evidence (representative tasks, all schema-valid)

| group | task | result |
|---|---|---|
| A | TopicMiner | 3+ materially distinct, well-framed angles |
| A | CounterargumentAgent | real steelmen (context, culture, wisdom) |
| A | SearchPlanner | mixed fa/en primary-source queries, no dupes |
| B | evidence validation | correct support judgment + Persian reasoning |
| C | NarrativeAgent | coherent 5–7 beat arc, sane minutes |
| D | Persian critic (planted defects) | **5/5 detected**: stereotype, false certainty, fake book, invented quote, pipeline leakage |

## Telemetry (real OpenRouter accounting, `usage.include`)

- Calls: **68** (63 ok; 5 failures are the intentional failure tests)
- Tokens: **197 221 in / 85 890 out**
- Reported cost: **$0.0633 total**
- Latency: mean 33.8 s, min ~3 s (short), max 158 s (long draft)
- Schema-repair calls issued: 5 (1 effective)
- Upstream providers observed: Novita, Alibaba, GMICloud, StreamLake,
  Venice, Nebius, Parasail, Google, DeepInfra — **material provider
  variance; do not assume stable behavior across upstreams.** If adopted,
  pin a provider once evidence shows which are reliable.

## Failure loop — PASS

missing key (explicit error), invalid model (truthful 400), malformed
body, empty choices, timeout, and 429 (bounded: 3 attempts then raised)
all surface truthfully. No silent fallback anywhere. Key absent from all
errors, telemetry, and artifacts (scanned `docs/`, `benchmarks/`).
Caveat: OpenRouter 400 bodies echo `user_id` — account identifier, not
the key; note for log hygiene if errors are persisted.

## Role decision matrix (evidence above)

| role | decision | evidence |
|---|---|---|
| TopicMiner | PRIMARY_QWEN | distinct grounded angles, cheap |
| SearchPlanner / SearchQueryAgent | PRIMARY_QWEN | clean mixed-language plans |
| CounterargumentAgent | PRIMARY_QWEN | fair steelmen |
| HumanProblemAgent / PatternAgent | QWEN_ACCEPTABLE | reasoning solid; not directly measured |
| ContradictionFinder | QWEN_ACCEPTABLE | critic pass caught contradictions |
| SearchResultEvaluator / SourceQualityReviewer | QWEN_ACCEPTABLE | evidence-check correct, calibrated |
| ScientificEvidenceAgent / EpistemicStatusAgent | KEEP_CURRENT_MODEL | epistemic mislabels (SPECULATION on QM) |
| Evidence validation | QWEN_ACCEPTABLE | correct but watch schema wrapper |
| ArgumentAgent / NarrativeAgent / Semantic Master | QWEN_ACCEPTABLE | coherent outlines; long-form untested at master scale |
| ScriptWriter | **KEEP_CURRENT_WRITER** | 11.4/7.4 min vs 25–30 contract; schema drift; blind A/B 0/14 |
| RevisionAgent | NOT_RECOMMENDED | correction task broke schema 3/3 |
| LogicCritic / ChannelCritic | QWEN_ACCEPTABLE | convergent findings, harsher coding |
| PersianLanguageCritic | QWEN_ACCEPTABLE | 5/5 planted-defect recall; two roles returned empty fast |
| FactCritic | QWEN_ACCEPTABLE | caught source conflicts; some code misuse |

## Decisions

- **ScriptWriter:** `KEEP_CURRENT_WRITER` — cannot meet the duration
  contract (~40–45 % of target), systematic schema drift on revision,
  and loses the blind comparison on every axis. Not cost-motivated.
- **Persian critic:** `QWEN_ACCEPTABLE` — high defect recall and cheap;
  keep the production critic as the gate until a harness can bound
  shallow-review cases (empty fast responses).
- **FINAL RECOMMENDATION:** `USE_QWEN_FOR_SELECTED_AGENTS` —
  high-volume reasoning (Group A), evaluators, and critics; keep the
  current writer and epistemic-critical roles on the existing provider.

## RECOMMENDED_ROUTING (not implemented — owner approval required)

```yaml
writer_script_draft: devin            # unchanged
revision: devin                       # unchanged — Qwen unreliable here
epistemic_status / evidence_grading: devin  # unchanged
topic_mining / search_planning / counterargument: openrouter-qwen
search_result_evaluation / source_quality: openrouter-qwen
critics (logic/channel/persian-quality assist): openrouter-qwen
  with deterministic gates as the contract
provider pinning: evaluate Novita/Alibaba/DeepInfra stability before pin
wrapper: field-name normalization + 1 repair turn before any schema use
```

## Known weaknesses (global critique)

1. Duration contract failure is systematic across both channels —
   ~40–45 % of target after corrections.
2. Strict JSON schema not enforced on long tasks; field-name drift
   follows task wording; single repair insufficient (1/5 fixed).
3. Translation-flavored register unless colloquial style is forced by the
   prompt; markdown/`*`/ASCII-quote leakage into spoken text.
4. Evidence fidelity: fabricates specifics (animal names), upgrades
   correlational findings to mechanism, erases individual differences.
5. Occasional micro-glitches (duplicated word, dropped morpheme),
   invented anecdotes, unprompted corrections.
6. 9 upstream providers observed → variance; pin before production use.
