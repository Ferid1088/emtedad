# Multichannel Program — Phases 4–7 Audit

Scope: source structure (Vortragsstruktur), Knowledge Units, concept mapping,
and structure-aware Retrieval V2, per
`docs/EMTEDAD_CODING_AGENT_MASTER_IMPLEMENTATION_PROMPT.md` §4–§7.

## Implemented

### Phase 4 — Source structure

- New module `app/knowledge/structure/` (domain, models, schemas, prompts,
  agent, validator, repository, service).
- `knowledge.source_structure_nodes`: hierarchical nodes with typed
  `structure_node_type`, contiguous `start_segment_id`/`end_segment_id`
  spans, level, ordinal, confidence, `extraction_run_id`, and JSON metadata.
- Database enforcement: composite FK to `source_segments(id,
  source_version_id)` for both span endpoints, composite self-FK
  `(source_version_id, parent_id)`, `level >= 1`, `ordinal > 0`, and a
  sibling-ordinal unique index with `NULLS NOT DISTINCT`.
- `knowledge.source_processing_states`: explicit post-ingestion lifecycle
  (`INGESTED → STRUCTURE_PENDING → STRUCTURING → STRUCTURED /
  STRUCTURE_REVIEW_REQUIRED / FAILED`, plus the later unit states).
- `SourceStructureAgent`: two-pass extraction. Pass A proposes local nodes
  over overlapping transcript windows (`app/knowledge/windowing.py`); Pass B
  merges into a global hierarchy. Single-window transcripts skip Pass B.
  The model only sees segment `sequence` numbers; the service resolves them
  to real segment UUIDs.
- `SourceStructureValidator`: span existence/ordering, parent-in-hierarchy,
  level consistency, sibling ordinals, child-inside-parent containment,
  timestamp ordering, empty atomic spans, missing summaries; warnings for
  uncovered regions, sibling overlap, oversized/tiny nodes.
- Idempotency via `knowledge.extraction_runs` dedup keys
  (source_version + provider + model + prompt_version +
  configuration_hash).
- UI: `/library/{id}/structure` renders the persisted tree and a
  `?node=<id>` detail panel with the exact transcript segments and
  timestamps; a synchronous "Build structure" action runs the extraction
  awaited (no fake async).

### Phase 5 — Knowledge Units

- `app/knowledge/units/` (domain, models, schemas, extractor, validator,
  service).
- `knowledge.knowledge_units`: type, title, summary, `full_text`, span,
  `atomic`, evidence level, claim type, `content_hash`,
  `extraction_version`, `extraction_run_id`.
- `full_text` is reconstructed deterministically from ordered
  `normalized_text` segments; the LLM summary is never authoritative.
- Atomicity: STORY/CASE_STUDY units are always atomic; container nodes
  (TOPIC/SUBTOPIC with children) produce no unit.
- Validation before persistence; dedup via unique
  (source_version_id, unit_type, content_hash).
- UI: `/library/{id}/units` lists units with concepts, atomic badge,
  evidence/claim metadata, and source-derived full text; `?q=` filters.

### Phase 6 — Concept mapping

- `knowledge.knowledge_unit_concepts` (unit, concept, relation_role,
  confidence; unique per triple) linking units to the existing shared
  `external_concepts` table — one concept row is reused across sources.
- `knowledge.concept_relationships` with the spec'd relation vocabulary and
  provenance JSON.
- `ConceptMappingService`: LLM concept proposal per unit, normalized-name
  resolution, idempotent links, RELATED_TO edges between concepts
  co-occurring in one unit. Source structure and the global concept graph
  remain separate.

### Phase 7 — Retrieval V2

- `retrieval.knowledge_unit_embeddings`: per-unit SUMMARY and FULL_TEXT
  vectors via the existing embedding provider boundary; idempotent by
  (unit, model, kind, content_hash).
- `knowledge.knowledge_units.search_vector` persisted TSVECTOR + GIN index.
- `KnowledgeUnitSearchService`: lexical (FTS), dense (pgvector cosine), and
  concept lanes fused via RRF plus deterministic reranking; expansion modes
  NONE/PARENT/PARENTS/SIBLINGS/FAMILY/SUBTREE resolved against the
  structure tree.
- Results carry the full spec'd payload: unit + whole atomic text, matched
  concepts, score components, source provenance, timestamp span, structure
  path, and expanded context. Hits always return complete units — never
  excerpts.
- UI: `/studio/search` global unit search with expansion selector.

## Existing `speech_structure` relationship

The pre-existing `app/speech_structure` module (a looser versioned section
tree with its own scheduler and `/speech-structures` UI) remains untouched
and functional. The new `source_structure_nodes` model is the
spec-contract implementation that Knowledge Units and Retrieval V2 build
on. Consolidating `speech_structure` onto the new node model is a recorded
review item for a later phase; no historical data was changed or removed.

## Evidence

- `uv run ruff check app/` — pass
- `uv run mypy --strict app` — pass (178 files)
- `uv run pytest tests/unit -q` — 247 passed
- Integration (with `EMTEDAD_DATABASE_URL`): studio UI, editorial channels,
  source structure, knowledge units, and unit retrieval — 15 passed
- Migrations: `e5f6a7b8c9d0` (structure nodes + processing state),
  `f7a8b9c0d1e2` (knowledge units), `a8b9c0d1e2f3` (concept links),
  `b9c0d1e2f3a4` (unit FTS + embeddings) — applied cleanly on the dev
  database and disposable test databases.

## Known gaps / review items

- Unit extraction and structure builds are deliberately synchronous
  (awaited) — the master prompt permits synchronous execution where no task
  queue exists; the speech-structure scheduler remains real for its own
  feature.
- Retrieval V2 legacy-chunk fallback lane and the A/B evaluation harness
  (§7.5) are partially scoped; unit retrieval is primary and the old chunk
  system is untouched.
- Devin Cloud session limits (5 concurrent SWE-2 sessions) still throttle
  unrelated legacy tests, as recorded in the Phase 0 baseline.
