# ADR-002: Separate Knowledge Domains and Retrieval Lanes

- Status: Accepted
- Date: 2026-09-18

## Context

Ayin Canon, Manasek, external primary sources, external interpretations,
counterevidence, and generated lectures have different authority and epistemic
roles. A single undifferentiated corpus could allow retrieval score to override
meaning, authority, safety, or provenance.

## Decision

Model knowledge zones explicitly and use separate retrieval lanes for Ayin
Canon, external evidence, counterevidence/alternatives, and optional Manasek.
Preserve role labels and provenance through fusion, reranking, research, and
lecture generation.

## Consequences

- External material cannot silently redefine Canon.
- Counterevidence remains visible.
- Retrieval orchestration becomes more explicit and testable.
- More schema, filtering, evaluation, and review logic is required.

## Alternatives considered

- One vector index with only similarity ranking: rejected.
- One corpus with prompt-only authority instructions: rejected because domain
  integrity must not depend solely on model obedience.

## Supersedes / Superseded by

ADR-013 supersedes the use of the Ayin retrieval lane as ordinary 100-lesson
writer input. The separate-domain and specialist-retrieval decisions remain in
force.
