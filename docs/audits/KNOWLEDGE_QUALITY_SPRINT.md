# KNOWLEDGE QUALITY SPRINT

Quality improvements to the knowledge layer on real acceptance data.
No architectural changes.

## 0. Baseline (before changes)

Measured on real processed videos (video C still processing).

| Metric                              | A — وسوسه | B — جنگ | D — Brené Brown |
|-------------------------------------|-----------|---------|-----------------|
| SourceSegments                      | 530       | 874     | 475             |
| SourceStructure nodes               | 40        | 68      | 46              |
| KnowledgeUnits                      | 32        | 61      | 38              |
| Units with concept links            | 0         | 0       | 0               |
| Concept coverage                    | 0%        | 0%      | 0%              |
| Avg concepts / unit                 | 0         | 0       | 0               |
| Concept-lane retrieval contribution | 0         | 0       | 0               |
| Oversized units (>180s or >6000ch)  | 1 (204s DEFINITION) | 1 (416s SYNTHESIS) | 0 |
| Max non-atomic unit duration        | 204s      | 416s    | 64s             |
| Parent/child unit pairs ≥50% overlap| 5         | 19      | 4               |
| claim_type=UNKNOWN                  | 12/32 (37%)| 30/61 (49%)| 15/38 (39%) |
| evidence_level=NONE                 | 18/32 (56%)| 35/61 (57%)| 20/38 (53%) |
| Invalid unit-type proposals         | not persisted (log only); 19 observed on B run |

Global: 3712 `external_concepts` exist (import-time corpus), **0**
`knowledge_unit_concepts` links — `ConceptMappingService` was never run
on the acceptance videos, so the concept retrieval lane contributes
nothing.

### Root causes identified

1. Concept mapping service exists but was never executed (one LLM call
   per unit; no batching, no reuse-aware resolution beyond exact
   normalized-name match, no proposal validation).
2. Oversized non-atomic units are returned by retrieval as equal
   evidence; no summary/index role exists.
3. Parent/child units both surface in retrieval results with ~full
   span overlap; no dedup policy.
4. `claim_type`/`evidence_level` come straight from the LLM proposal
   with UNKNOWN/NONE defaults; matrix items copy them verbatim into
   `epistemic_status`; nothing flags UNKNOWN for science content.
5. Invalid `unit_type` proposals are dropped with a warning log but no
   persisted telemetry.

## 1. Changes

| Issue | Change | Files |
|---|---|---|
| Concept coverage | Batched `map_source_units` (10 units/call), `ConceptProposal` validation (noise words, >6-word names, low confidence), reuse-first `resolve_concept` (canonical normalized name → alias labels → create), role normalization (`PRIMARY/SECONDARY/CONTEXT/CONTRAST`), multilingual label keys tolerant (`canonical_name`/`name`/`concept`) | `units/concepts.py`, `units/mapping_service.py` |
| Oversized units | `unit_quality_flags()`: soft `size_warning` at >180s or >1300 words (config `unit_soft_max_*`); non-atomic oversized parent units with unit-bearing children get `retrieval_role=SUMMARY`; reranker demotes SUMMARY ×0.15; `refresh_retrieval_roles()` deterministic backfill | `units/quality.py`, `units/service.py`, `retrieval/unit_retrieval.py`, `core/config.py` |
| Parent/child overlap | `span_overlap_ratio()` (intersection/smaller span, node seconds); `_dedup_nested()` in search drops the ancestor of an ancestor/descendant pair at ≥50% span overlap; ancestor stays reachable via PARENT expansion; SUMMARY descendant never displaces a regular ancestor | `units/quality.py`, `retrieval/unit_retrieval.py` |
| Epistemic UNKNOWN | `classify_epistemic()` deterministic mapping (unit_type × claim_type × evidence_level → 11-value `EpistemicStatus`); `build_evidence_matrix` stores it per item; `unknown_evidence_warnings()` logs `REVIEW_REQUIRED` per UNKNOWN item for `science-mystery` | `research/epistemic.py`, `research/generic.py` |
| `unit_type=ARGUMENT` telemetry | Extraction prompt explicitly enumerates the 11 allowed unit types and states ARGUMENT is a *node* type; rejections counted per run into `extraction_runs.stats_json.rejected` (migration `e3f4a5b6c7d8`); batch still resilient | `units/extractor.py`, `units/service.py`, `units/schemas.py`, `alembic/…` |

No splitting/chopping of unit content was introduced — oversized parents
are demoted, not rewritten; atomic STORY/CASE_STUDY units are exempt
from the SUMMARY role entirely.

## 2. After metrics

| Metric                              | A — وسوسه | B — جنگ | D — Brené Brown |
|-------------------------------------|-----------|---------|-----------------|
| Units with concept links            | 32        | 60      | 38              |
| Concept coverage                    | 100%      | 98%     | 100%            |
| Avg concepts / unit                 | 4.1       | 4.2     | 3.4             |
| Mapping stats (links/reused/rejected)| 132/68/0 | 255/67/0| 130/50/0        |
| Units flagged size_warning          | 1         | 1       | 0               |
| Units demoted to SUMMARY role       | 1         | 1       | 0               |
| Parent/child pairs ≥50% overlap     | 5         | 19      | 4 (unchanged — units kept; dedup is a retrieval policy) |
| claim_type=UNKNOWN                  | 12/32     | 30/61   | 15/38 (unchanged — signal now classified downstream instead of overwritten) |

185 concept proposals resolved to *existing* concepts out of 517 links —
the shared concept layer is converging rather than multiplying rows.

### Retrieval regression (10 queries, lexical+dense+concept, PARENTS)

| Query | Before | After |
|---|---|---|
| وسوسه (exact) | relevant | relevant + concepts (addiction, craving) |
| بازسازی تستوسترونی (detail, mid-story) | atomic case study | **Sapolsky baboon CASE_STUDY, atomic, intact** |
| چرا انسان می‌جنگد (causal) | relevant | relevant CLAIM + concepts (War, cost-benefit) |
| evolutionary origins of warfare (cross-lingual) | relevant | relevant + concepts (War, agricultural revolution) |
| fear of abandonment | noise/0-concept | relevant CLAIM + concepts (emotional numbing, joy) |
| attachment | noise/0-concept | relevant DEFINITION + concepts (blame, discharge of pain) |
| vulnerability | relevant | relevant CLAIM + concepts (emotional numbing, joy) |
| tribal identity | — | relevant EXPLANATION (in-group out-group bias) |
| خشونت ذاتی نیست (counterarg) | relevant | relevant CLAIM + concepts (Noble savage, archaeological evidence) |
| cognitive dissonance | — | relevant CLAIM + concepts (cognitive processes, craving) |

- Concept lane contribution: **0 → 10/10 queries** carry
  `matched_concepts`; contribution is additive (RRF lane), lexical and
  dense ranking unchanged.
- Parent/child duplicates: ancestor units no longer co-occur as equal
  evidence in results (`_dedup_nested`); parents still appear in
  `expanded_context` on PARENT/PARENTS expansion.
- Story atomicity: **15/15 atomic units verified unchanged** (Tantalus
  myth 1091 chars, Sapolsky baboon CASE_STUDY 767 chars, Brené Brown
  researcher-storyteller arc and Diane session story) — none split,
  none demoted, all `retrieval_role=UNIT`.
- `بازسازی تستوسترونی` resolves to the full atomic CASE_STUDY — the
  mid-story probe still lands on the complete unit.

## 3. Tests

- `tests/unit/test_knowledge_quality.py` (20 tests): span overlap,
  quality flags (oversized parent → SUMMARY; atomic never SUMMARY),
  concept validation (noise/sentence/empty/low-confidence), role
  normalization, epistemic mappings (story→ANECDOTAL, experiment→
  STRONG_EVIDENCE, interpretation→PHILOSOPHICAL, UNKNOWN stays
  UNKNOWN), science-channel UNKNOWN warnings, extractor rejection
  telemetry.
- `tests/integration/test_unit_retrieval.py` extended: batched concept
  mapping fixture (new `UnitsConceptBatch` shape), nested dedup prefers
  the specific child while the parent remains as expansion context,
  noise-concept rejection + idempotent reuse.
- Full unit suite: 263 passed. Affected integration: 15 passed
  (retrieval, knowledge units, source structure, topics, generic E2E).

## 4. Final gate additions

### Automatic concept mapping (canonical pipeline)

`SourceProcessingService.process_source` now runs the full canonical
chain — structure → units → **concept mapping → retrieval indexing** →
READY — with no manual `ConceptMappingService` call. The Devin provider
varied the concept-name key (`canonical_name`/`name`/`concept`);
`ConceptProposal` accepts all three via `AliasChoices`.

- The scheduler's `service_factory` passes the app's embedding provider,
  so `UnitEmbeddingService.build` refreshes the dense lane after every
  successful unit extraction.
- Mapping/indexing failure marks the state `FAILED` with `last_error`
  (structure and units are never destroyed); the existing bounded retry
  and quota classification apply unchanged.
- Proven in `test_generic_e2e`: one `process_source` call produces 2
  `KnowledgeUnitConcept` links automatically; a second full run creates
  **no** duplicate units, links, or concept rows.

### Concept precision (deterministic 85-link sample)

`sample_concept_links()` orders by (unit_type, unit id, concept id),
cap 9/type, across A/B/D — fully deterministic, no RNG.

| Class | Count | Share |
|---|---|---|
| STRONG (concept is central to the unit) | 52 | 61% |
| ACCEPTABLE (clearly retrieval-useful) | 28 | 33% |
| WEAK (broad background only) | 5 | 6% |
| WRONG (unsupported) | 0 | 0% |

- `precision_strict` = 52/85 = **61%**
- `precision_useful` = (52+28)/85 = **94.1%** ≥ 90% target
- Weak links cluster in SECONDARY/CONTEXT roles on generic terms
  (`relationships`, `love`, `empathy`, `cooperation`, `patriarchy`) —
  consistent with role semantics, not false positives.

### Generic segment-based overlap

`_dedup_nested` now computes overlap on **SourceSegment sequence
ranges** of the units (`(start_seq, end_seq)`), not node timestamps —
the canonical metric works identically for video, PDF, book, and
article sources. Units lacking resolvable sequences are skipped rather
than wrongly deduplicated.

- `test_nested_dedup_works_without_timestamps`: a BOOK-type source
  whose child-node pseudo-timestamps deliberately fall *outside* the
  parent's seconds — seconds-based overlap would see 0, sequences see
  the true (3–8 ⊂ 1–10) nesting and the parent is correctly dropped.

### Oversized SUMMARY context safety

`expanded_context` items carry only `title`/`summary`/`node_title`/
`atomic` — a SUMMARY parent injects its metadata into context, never
its 416-second `full_text`. Regression assertion added to the nested
dedup test (`"full_text" not in item` for every context entry).

### Final retrieval regression (post-sequence-dedup)

10/10 queries return relevant results, `matched_concepts` on all 10,
mid-story probe still resolves to the complete atomic CASE_STUDY, and
**15/15 atomic units keep `retrieval_role=UNIT`**. No lexical/dense
degradation.

## 5. Remaining weaknesses

- `claim_type=UNKNOWN` (37–49%) is still high at extraction time; the
  epistemic layer classifies around it but upstream prompting could
  reduce UNKNOWN proposals (candidate follow-up, not in scope).
- `evidence_level=NONE` (~55%) similar — units carry no external
  source-quality signal for lectures.
- Concept precision is good on the probed queries; no precision
  harness exists yet for systematic measurement.
- Video C still unprocessed (provider session cap during stabilization);
  its metrics are excluded from both baseline and after tables.
- The oversized B SYNTHESIS (416 s) keeps its `size_warning` flag and is
  demoted to SUMMARY, but is not decomposed — the spec prefers
  structure-derived units over splitting text; a decomposition pass is
  backlog.
- `UnitConceptBatch` (per-unit shape) retained for backwards
  compatibility; remove once no call sites remain.
