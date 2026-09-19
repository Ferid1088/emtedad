# ADR-006: Model Manasek Structure and Safety as Typed, Versioned Data

- Status: Accepted
- Date: 2026-09-19

## Context

The supplied Manasek source defines seven ordered individual stages. Each stage
contains the five gates Earth, Water, Fire, Wind, and Pull, followed by Return.
It also defines a separate collective practice. Return is explicitly not a
sixth gate, and collective practice is not a compressed form of the 42-piece
individual sequence. The source repeatedly makes choice, stop/leave rights,
non-coercion, and non-interpretation safety requirements part of the ritual
design.

The source remains a Working document. Its structure and experiential language
cannot be treated as proof of Ayin or promoted to Canon by import.

## Decision

Use the `ritual` PostgreSQL schema for a typed, versioned Manasek domain:

1. Separate document, source version, extraction run, and run-pinned passage
   identities, following ADR-005.
2. Keep stable identities for families, gates, rituals, and safety rules, with
   source-backed versions for editable content.
3. Represent individual and collective architectures with an explicit mode.
   Store seven stages and 42 relational sequence items for the individual
   architecture and a separate collective sequence.
4. Represent Return with its own ritual piece type and extension table. A
   composite foreign key and check constraint prevent a Return from being a
   gate.
5. Use deferred PostgreSQL constraint triggers to validate aggregate approved
   architecture completeness and publishability. Approval requires a
   `MANASEK_CANON` source, complete structure, approved safety bindings, a
   passing validation, and no open blocking safety review.
6. Store cues, music intent, Persian draft localizations, Ayin links, and
   review records in normalized typed tables. Important relationships use
   foreign keys, never generic owner identifiers.
7. Apply deterministic safety validation to coercive, diagnostic,
   metaphysical-proof, unsafe-breath, denied-exit, and pseudoscientific music
   language. Every ritual and localization retains explicit safety-rule
   bindings.
8. Keep `horizontal_emtedad` as a typed, source-grounded concept-link proposal
   because the current Ayin Working ontology has no such stable concept.

## Consequences

- Working imports cannot masquerade as approved Canon.
- Approved source, architecture, ritual, localization, gate, family, and safety
  versions are immutable and must be superseded by new versions.
- Five-gate ordering and seven-stage completeness are queryable and
  database-enforced for approval rather than existing only in Python.
- Timed cues and music intent are ready for later production systems, but Phase
  3 performs no playback, music generation, TTS, or translation.
- Between and Life family identities exist for future source-backed material;
  no missing ritual content is fabricated.
- A later approval service still requires authenticated editor identities and
  editorial authority. Phase 3 exposes no approval endpoint or command.

## Alternatives considered

- Store each ritual as one JSON document: rejected because it weakens ordering,
  provenance, safety, and foreign-key constraints.
- Treat Return as gate position six: rejected because it contradicts the
  source and domain rules.
- Reuse the 42-piece structure for collective ritual: rejected because it
  erases the source's distinct collective architecture.
- Rely only on application validation or an LLM safety reviewer: rejected
  because critical safety and approval invariants require deterministic and
  database-backed enforcement.
