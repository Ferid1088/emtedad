# Phase 5 Completion — Hybrid Retrieval

Date: 2026-09-19

## Scope delivered

Phase 5 implements immutable/versioned retrieval chunks over Ayin Working,
Manasek Working structured ritual content, and external primary segments. It
adds multilingual lexical, dense, and entity-aware retrieval; deterministic
RRF; deterministic reranking; source-local context expansion; persisted runs;
and provenance-complete API/CLI results.

No Canon promotion occurred. No Ayin↔external interpretation, ResearchPackage,
lecture, localization, publishing, or other Phase 6+ behavior was introduced.

## Architecture and data

- Alembic revision `effbbb690796` creates the `retrieval` tables, enums,
  generated lexical vectors, GIN index, typed source-membership relations,
  embedding registry/runs, retrieval runs/results, and evaluation records.
- Deferred database validation requires every chunk to have the correct typed
  source membership. Triggers make chunks, ordered membership, and embeddings
  immutable and enforce registered vector dimensions.
- The selected embedding is `intfloat/multilingual-e5-small`, revision
  `614241f`, 384 dimensions, normalized cosine vectors, MIT license.
- Exact pgvector search is used. No HNSW/IVFFlat index is justified at the
  measured corpus size.

## Live reproducibility evidence

- Final chunk run: `c82122da-78b9-46e5-a38c-d755ecc211b4`
- Output hash: `f23cd3281ee2b11d77c0ff7e9d51c3b4ff824cb63e35ac0c2ca8424546dbec66`
- 131 chunks: 53 Ayin Working, 43 Manasek Working, 35 external primary
- Final embedding run: `e8fa4e2f-309c-4d02-881d-b4574f506b10`
- 131/131 embeddings: 52 newly encoded, 79 content-hash cache hits
- Repeated chunk and embedding builds reused the same completed run IDs.
- Structural validation: valid, 131 chunks, 131 embeddings, zero issues.

Manasek has no explicitly preferred raw extraction run, so Phase 5 does not
silently select one. Its reviewed Working structured ritual versions are
retrievable and source-version pinned; raw Manasek passage retrieval will join
the same pipeline after an extraction preference is explicitly recorded.

## Multilingual evaluation

The persisted nine-query gold set uses source-linked Ayin Working concept
judgments across Persian, English, and Arabic. Final evaluation run:
`9b1442b3-a692-470a-b88f-04a6dbfddfbd`.

| Metric | Overall | Persian | English | Arabic |
|---|---:|---:|---:|---:|
| Recall@5 | 1.000 | 1.000 | 1.000 | 1.000 |
| MRR@5 | 0.870 | 0.611 | 1.000 | 1.000 |
| nDCG@5 | 0.903 | 0.710 | 1.000 | 1.000 |

Component Recall@5 was 0.000 lexical, 0.667 dense, 1.000 entity-aware, 1.000
RRF, and 1.000 after reranking. The lexical baseline is intentionally weak on
cross-language/paraphrase queries; measured fusion shows why no single
retriever is treated as sufficient.

Cold model load was 12,791 ms and is reported separately. Full-pipeline warm
steady-state p95 retrieval latency was 265 ms (nine samples), below the 3,000
ms gate.

## Verification

- PostgreSQL 17 Docker service: healthy
- pgvector 0.8.1: available
- Clean upgrade, downgrade to base, re-upgrade, repeated upgrade: passed
- Alembic metadata drift: none
- Ruff format/lint: passed
- Strict mypy: passed
- Unit tests: 65 passed; importer tests: 6 passed; integration tests: 18 passed
- Full suite: 89 passed
- Manual cross-lane inspection: Ayin remained `AYIN_WORKING`, Manasek remained
  `MANASEK_WORKING`, external remained `EXTERNAL_PRIMARY`; final results
  retained per-method ranks and scores.
- Secret/generated-file check: clean; model cache remains outside the repo.

## Deferred decisions

- Select a preferred Manasek raw extraction run through explicit editorial
  governance before adding its raw passage set to active retrieval.
- Benchmark approximate pgvector indexes only after corpus/query scale warrants
  them.
- Production model hosting/cache warm-up, privacy, retention/deletion,
  re-embedding, backup, and deployment policy remain production review items.
- Counterevidence classification and Ayin↔external dialogue remain Phase 6.
