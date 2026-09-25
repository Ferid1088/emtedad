# Vortragsstruktur

Vortragsstruktur is an additive interpretation layer over an immutable source
transcript. It never rewrites `knowledge.source_segments`; sections retain
ordered references to those segments and may map non-contiguous discussion back
to one conceptual chapter.

## Pipeline

`TranscriptLoader` selects the latest source version, `AnalysisWindowBuilder`
creates overlapping segment-safe windows, and the structured LLM produces local
topics. A second versioned prompt builds a global hierarchy. Assignment is
deterministic from topic segment IDs, followed by relational validation and
version finalization. Unknown IDs, orphan parents, duplicate primary mappings
and low coverage are never hidden; low coverage is stored as `REVIEW`.

The module reuses the existing `LLMProvider`/Codex provider and does not change
the current RAG path.

## Storage and backfill

The additive `knowledge.speech_structures`, `speech_structure_runs`,
`speech_sections`, and `speech_section_segments` tables pin a source version,
keep `root_id` for every section, and preserve every regeneration as a new
version. Raw transcript provenance remains in `source_segments`.

After migrations, run the idempotent one-time initial backfill:

```bash
python -m app.cli speech-structure backfill
```

Use `--limit` for a pilot and `--force` to create a new version when the input
hash is unchanged. Failed sources are reported independently.

## Owner UI and future retrieval

Open `/speech-structures` or choose **Vortragsstruktur** in the owner
navigation. The detail page shows an expandable hierarchy, validation coverage,
and original timestamped segments. `get_root_family(section_id)` returns the
complete ordered subtree beneath the level-one root; it is intentionally not
connected to production RAG yet.

The first implementation does not build a knowledge graph, rewrite transcripts,
or provide manual merge/split editing. Tests use fake providers and do not call
a live model.
