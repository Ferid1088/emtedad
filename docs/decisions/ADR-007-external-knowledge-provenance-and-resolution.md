# ADR-007: Preserve External Knowledge Provenance and Resolution Uncertainty

- Status: Accepted
- Date: 2026-09-19

## Context

External lectures and publications are research material, not Ayin or Manasek
authority. Provider content can change, transcript tooling can change without
the source changing, LLM windows can fail independently, and bibliographic
identity resolution is often ambiguous.

## Decision

Use the `knowledge` schema with separate source, immutable source version, raw
timestamped segment, deterministic window, extraction run, and window-result
identities. Keep raw and normalized Persian text separate. Every mention and
claim has typed foreign keys back to its exact source version, segment, and
extraction run.

Adapters are provider-independent; YouTube is the first implementation. LLM
extraction uses a replaceable structured-output interface, with Codex CLI as
the first provider. Its cache key includes source version, window content and
configuration, task, prompt, provider, and model. Successful windows are
reused and failed windows remain independently retryable.

People, works, organizations, and concepts are external identities. Mentions
remain occurrences. Crossref, OpenAlex, Open Library, and Wikidata contribute
candidates; strong identifiers are globally unique, while ambiguous matches
remain review items. Extracted claims begin as `attributed_only` and citation
resolution cannot promote their truth status.

Media uses typed links to content-addressed `ops.object_assets`. Download is
limited to directly accessible URLs, rights remain explicit or unknown, PDF
magic/MIME are validated, and PyMuPDF renders only a verified first page.

## Consequences

- External records cannot enter Ayin or Manasek Canon.
- Transcript history, exact timestamps, extraction configuration, failures,
  candidates, and review decisions remain reproducible.
- Changing an extraction model/configuration creates a new run, not a false
  source version.
- No Phase 5 chunks, full-text retrieval, embeddings, or vector indexes exist.
