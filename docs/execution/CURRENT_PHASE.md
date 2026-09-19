# Pending Phase: Phase 5 — Retrieval

## Execution status

Phase 4 is complete as of 2026-09-19. Phase 5 is prepared for repository-owner
review but is not active. Do not implement Phase 5 until the owner explicitly
approves this plan.

Completion evidence for Phase 4:
`docs/audits/PHASE_4_COMPLETION.md`.

## Goal

Build provenance-preserving multilingual retrieval over approved/queryable
Ayin, Manasek, and external material. Retrieval must preserve corpus zone and
epistemic role rather than treating similarity score as authority.

## Proposed scope

- versioned chunks derived from immutable parent passages or segments;
- separate Persian, Arabic, and English lexical normalization;
- PostgreSQL full-text search configurations and measured indexes;
- versioned multilingual embedding models and vector dimensions;
- idempotent embedding jobs/results with immutable input hashes;
- separate Ayin, external, ritual, and generated-content retrieval lanes;
- fusion, reranking, parent expansion, provenance, and authority filters;
- retrieval runs and evaluation fixtures with explicit configuration identity;
- thin read/evaluation APIs, CLI commands, migrations, and serious tests.

## Required review before activation

1. embedding model, license, hosting, dimension, and cost;
2. chunk policy per source domain and parent-expansion rules;
3. language configurations and Persian normalization policy;
4. HNSW/IVFFlat choice only after measured corpus/query benchmarks;
5. lane weights, fusion/reranking policy, and authority filters;
6. evaluation gold-set ownership and acceptance thresholds;
7. privacy, retention, deletion, and re-embedding policy.

## Out of scope

- Ayin-to-external dialogue classification (Phase 6);
- ResearchPlan, ResearchPackage, and Ayin Spine (Phase 7);
- lecture generation, localization, publishing, music, or TTS;
- automatic Canon promotion or claim verification.

## Required invariants

- Every chunk and embedding pins an immutable source version and exact ordered
  parent records.
- Model/config changes create new versioned results; old vectors are retained.
- Corpus zone, source type, language, epistemic status, and authority filters
  remain queryable through every retrieval result.
- External similarity cannot redefine Ayin; Manasek is not evidence.
- Raw vector score never encodes authority.
- Important relations use typed foreign keys, not generic owner IDs.

## Acceptance gate

Phase 5 requires owner approval, an accepted retrieval ADR, clean reversible
migrations, deterministic fixtures, measured lexical/vector/fusion evaluation,
failure isolation, API/CLI tests, Ruff, strict mypy, and the full suite. Phase 6
must not begin as part of Phase 5.
