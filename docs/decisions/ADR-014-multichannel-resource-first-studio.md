# ADR-014: Multi-Channel Resource-First Studio

Status: Accepted
Date: 2026-10-03

## Context

The platform currently produces one editorial product: the approved 100-lesson
Emtedad canon drives research, Persian drafting, localization, and voice
preparation. The owner now requires five independent editorial verticals
(`Emtedad`, `Science & Mystery`, `History & Human Stories`,
`Pop Psychology & Relationships`, `Psychology & Evolution`) that share one
knowledge infrastructure but have independent strategies, topic discovery, and
production pipelines.

The existing `knowledge.Channel` model already represents imported *source*
channels (e.g. YouTube channels). Token-window retrieval chunks exist for
indexing but are not meaningful writer-facing units. Source transcripts carry
timestamps but no hierarchical structure, so stories cannot be retrieved as
coherent wholes.

## Decision

1. **Resources are primary.** Sources, source versions, source segments,
   structure, Knowledge Units, concepts, embeddings, and provenance form one
   shared knowledge base. Topics and scripts are derived artifacts; no fixed
   topic or lesson list defines production.
2. **The 100-lesson path becomes legacy.** `LessonCanonRepository`, fixed
   lesson identity, and `lesson_id` as mandatory production origin are
   replaced by generic resource-derived production. Migration follows
   replacement-before-deletion: build the generic path, prove it, migrate
   active routes/services, preserve historical provenance, then retire the
   legacy path. Applied Alembic migrations and historical rows are never
   deleted.
3. **`EditorialChannel` is separate from `knowledge.Channel`.** The five
   content verticals use a new `content.EditorialChannel` aggregate with
   versioned `ChannelStrategyVersion` records. The source-channel model is
   neither renamed nor overloaded. Publication language/platform variants are
   modeled separately as `PublicationTarget`, not as extra channels.
4. **`KnowledgeUnit` is the writer-facing semantic unit.** Transcript source
   versions receive a first-class hierarchical `SourceStructureNode` tree
   (Vortragsstruktur) mapping to real segments. Knowledge Units are built from
   validated structure; `full_text` is reconstructed from source segments.
   Stories and case studies are `atomic`: retrieval returns the complete unit.
   Token chunks remain for indexing compatibility but are no longer the
   semantic product.
5. **Writer input firewall.** Script generation receives only the channel
   strategy snapshot, Content Brief, locked thesis, Evidence Matrix, frozen
   ResearchPackage, Argument Plan, Narrative Plan, owner style instruction,
   and revision constraints. Published scripts contribute signatures for
   novelty checking, never prose.
6. **Ayin remains a resource.** Ayin stays a high-value foundational resource
   for the Emtedad channel and keeps its canon/working, provenance, and
   dialogue boundaries. It is no longer the mandatory canon for the whole
   platform.

## Consequences

- New content-schema tables: `editorial_channels`, `channel_strategy_versions`,
  `editorial_channel_resources`, and later `topic_candidates`,
  `content_briefs`, `evidence_matrices`, `script_signatures`, and
  `publication_targets`.
- New knowledge-schema tables: `source_structure_nodes`, `knowledge_units`,
  `knowledge_unit_concepts`, `concept_relationships`, and a source processing
  state record.
- Structure extraction, unit extraction, and indexing must be idempotent and
  carry provider/prompt/configuration provenance.
- Every generated artifact carries source/version, prompt version,
  model/provider, upstream artifact, and strategy-version provenance.
- Legacy lesson routes, templates, and repositories remain until the generic
  path passes end-to-end tests; then they are retired, not migrated silently.
- Owner approval remains mandatory before any packaging/publication step.

## Alternatives considered

- Extend `knowledge.Channel` for editorial verticals: rejected; it conflates
  imported source identity with editorial strategy.
- One knowledge base per channel: rejected; it duplicates provenance and
  prevents cross-channel knowledge reuse.
- Keep the 100-lesson canon as the production origin for all channels:
  rejected; it hard-codes one channel's corpus as platform law.
- Token chunks as the retrieval product: rejected; they cut stories and
  arguments at arbitrary boundaries.

## Supersedes / Superseded by

For new multi-channel production this ADR supersedes ADR-013's
lesson-canon-as-mandatory-origin assumption; ADR-013's writer-isolation and
full-corpus retrieval-boundary rules remain in force for the legacy lesson
path until its retirement and for Ayin source fidelity in the Emtedad channel.
