# ADR-011: Semantic Lecture Master and ResearchPackage Writer Isolation

Status: Accepted
Date: 2026-09-23

## Context

Frozen ResearchPackages are the intellectual boundary for lecture preparation.
Phase 8 must preserve Ayin authority, external epistemic status, dialogue
review state, counterevidence, and optional Manasek context without producing
localized prose or performing new research.

## Decision

Introduce a structured, versioned Semantic Lecture Master in `content` with
typed lecture projects, sections, claims, dependencies, evidence bindings,
citations, ritual links, validation findings, and standalone JSON exports.
The architect reads only frozen ResearchPackage material. Deterministic
validators enforce Ayin fidelity, epistemic integrity, citation coverage,
dialogue status, open-question preservation, and ritual boundaries.

READY masters pin the package version and content hash and are database
immutable. A revision creates a new master version. Phase 9 receives the
standalone export and is responsible for language realization in Persian,
German, English, and Arabic. Phase 8 does not finalize localized prose or
German terminology choices.

## Consequences

Semantic structure is reviewable without pretending to be final prose. Every
substantive claim has package evidence or remains blocked. Proposed dialogue
relations cannot silently become approved claims, and Manasek remains an
optional experiential link rather than evidence.

## Alternatives considered

- Free-form language-neutral paragraphs were rejected because they hide claim
  boundaries and epistemic status.
- Allowing lecture-time retrieval was rejected because it breaks reproducible
  ResearchPackage writer isolation.
- Mutable READY masters were rejected because Phase 9 needs stable input.

## Supersedes / Superseded by

ADR-013 supersedes the frozen ResearchPackage as the sole writer input for
ordinary 100-lesson production. The writer boundary is now a pinned canonical
Lesson Content Package plus Core Concept Registry plus frozen external research;
writer isolation and immutable READY masters remain in force.
