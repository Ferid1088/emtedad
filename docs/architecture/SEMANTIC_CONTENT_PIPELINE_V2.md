# Semantic Content Pipeline V2

This branch adds a data-preserving path for turning hundreds of hours of external
speech transcripts into coherent long-form scripts.

## Architecture

```text
immutable source segments
  -> semantic structure run
  -> hierarchical nodes (1 / 1.1 / 1.1.1 ...)
  -> existing hybrid retrieval
  -> hierarchy-aware context expansion
  -> synthesis + deduplication
  -> 4-6 section content architecture
  -> section evidence packs
  -> section-by-section writer with global state
  -> coherence audit
  -> targeted revision
  -> final script
```

Retrieval chunks remain optimized for search. The semantic tree represents the
speaker's conceptual structure and keeps exact source-segment/timestamp provenance.

A hit on a deep node can use `FULL_ROOT_FAMILY` to expose the complete top-level
family to synthesis, including all siblings and descendants. The writer still receives
only a bounded evidence pack for the section being written.

## Data preservation

The migration is additive. It does not delete or rewrite existing transcripts,
source versions, source segments, claims, embeddings, Ayin/Manasek data, lecture
masters, or publication records. Semantic trees are versioned derived artifacts.

## Generation stages

1. Research planner creates 4-8 focused retrieval queries.
2. Existing external hybrid retrieval supplies grounded candidates.
3. Semantic context expansion restores the source hierarchy around hits.
4. Synthesizer deduplicates and clusters evidence while preserving tensions.
5. Architect creates one coherent outline and word budget.
6. Writer works section-by-section with a small global state to avoid repetition.
7. Coherence audit finds structural problems without rewriting.
8. Targeted revision fixes only reported issues.

For a 20-minute request the default speaking rate is 125 words/minute, about 2,500
words. Both duration and speaking rate are configurable.

## API

- `POST /knowledge/source-versions/{source_version_id}/semantic-structure`
- `GET /knowledge/source-versions/{source_version_id}/semantic-structure`
- `POST /content/automated`
- `GET /content/automated/{project_id}`

The HTTP workflow is synchronous in this first implementation. The persisted stage
model is designed so execution can later move to a worker/queue without changing the
stored contracts.
