# ADR-010: Ayin Research Engine and Frozen ResearchPackages

Status: Accepted
Date: 2026-09-23

## Context

Research must begin with a human question while preserving the exact Ayin
versions assessed. Retrieval, Manasek context, external evidence,
counterevidence, and reviewed Phase 6 dialogue relations must remain distinct.

## Decision

Phase 7 introduces versioned `AyinSpine`, targeted `ResearchPlan`, and frozen
`ResearchPackage` records. The spine pins Ayin concepts, principles,
distinctions, open questions, and passages to one corpus version. Plans select
retrieval lanes explicitly. Packages snapshot retrieval configuration, result
provenance, typed Ayin associations, external chunks, and dialogue relations.
Machine-built packages freeze only after construction; a database trigger
rejects mutation or deletion of frozen packages.

Research is query-driven, never all-pairs. Counterevidence is a first-class
question and an empty result is valid. External material cannot modify Ayin or
Manasek records, promote authority, or become a lecture.

## Consequences

Historical research remains reproducible and stale dependencies can be found
through the pinned version foreign keys. Package construction is deterministic
and cacheable by its input and content hashes. Editorial review remains
required before any later publishing phase.

## Alternatives considered

- A generic owner/target research graph was rejected because it loses typed
  referential integrity.
- All-pairs concept comparison was rejected as noisy and expensive.
- Mutable evidence bundles were rejected because they undermine reproducibility.

## Supersedes / Superseded by

ADR-013 supersedes Ayin retrieval inside the ordinary 100-lesson production
path. Frozen external research, counterevidence, reproducibility, and specialist
research behavior remain in force.
