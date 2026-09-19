# ADR-008: Lane-aware hybrid retrieval and multilingual embeddings

## Status and date

Accepted — 2026-09-19

## Context

Phase 5 must retrieve Ayin Working, Manasek Working, and external primary
material without allowing similarity to collapse their different authority and
epistemic roles. Results must be reproducible across source, chunking, model,
and retrieval-configuration changes and must support Persian, English, and
Arabic queries.

## Decision

- Persist immutable, versioned chunks with ordered typed foreign keys to Ayin
  passages, Manasek passages/ritual versions, or external segments.
- Keep Ayin, Manasek, and external retrieval in explicit lanes. Apply lexical,
  dense, and entity-aware retrieval per lane, deterministic reciprocal-rank
  fusion with `k=60`, and a deterministic overlap/signal reranker. Interleave
  final lane results in explicit Ayin, Manasek, external order.
- Normalize only the search representation. Preserve source text unchanged.
- Use PostgreSQL `simple` full-text search with a generated `tsvector` and GIN
  index. The normalizer handles Unicode normalization, Arabic/Persian glyph
  variants, diacritics, zero-width characters, and multilingual tokenization.
- Use `intfloat/multilingual-e5-small` at revision `614241f`, through
  sentence-transformers, with 384-dimensional normalized vectors and cosine
  distance. Record model identity, revision, dimensions, language capability,
  parameters, and MIT license.
- Store embeddings in pgvector and enforce their dimensions against the model
  registry with a database trigger. Cache only by model and immutable chunk
  content hash.
- Use exact pgvector cosine search at the measured Phase 5 corpus size. Do not
  create HNSW or IVFFlat before a measured scale/latency need justifies its
  recall and operational trade-offs.
- Pin retrieval runs to chunk run, embedding model, and configuration. Persist
  component ranks/scores, fused/reranked scores, expanded context, and complete
  typed provenance.
- Evaluate reviewed source-linked queries independently in Persian, English,
  and Arabic. Record cold model load separately from steady-state latency.

## Consequences

Authority stays visible and cannot be inferred from vector score. Exact source
locations remain reconstructable. Model and normalization changes create new
runs while historical results remain available. The first process query pays a
model-loading cost; steady-state requests reuse the loaded model. Exact vector
search is deliberately favored over premature approximate indexing.

## Alternatives considered

- A single global ranking was rejected because it lets score imply authority.
- Generic `owner_type`/`owner_id` chunk provenance was rejected because it
  cannot enforce domain integrity.
- An external vector database was rejected because PostgreSQL is canonical and
  pgvector meets the measured Phase 5 need.
- HNSW and IVFFlat were deferred because 131 current chunks do not justify
  approximate-search recall loss or tuning complexity.
- An LLM reranker was rejected for Phase 5 because it adds hidden network,
  cost, and nondeterminism to a foundational retrieval gate.

## Supersedes / superseded by

None.
