# ADR-003: One Semantic Master for Three Languages

- Status: Accepted
- Date: 2026-09-18

## Context

Independent Persian, English, and Arabic lecture generation would create claim,
terminology, evidence, and citation drift. The three channels need cultural and
linguistic localization without becoming three unrelated arguments.

## Decision

Create one versioned Semantic Master after research and validation. Derive all
Persian, English, and Arabic versions from that master while preserving concept
IDs, claim IDs, citations, uncertainty, and epistemic status. Store localized
enrichment separately from the shared evidence core.

## Consequences

- Cross-language meaning is testable.
- Citation and claim identity remain aligned.
- Localization requires terminology and fidelity validators.
- A Semantic Master change may mark all derived language versions stale.

## Alternatives considered

- Generate each language directly from retrieved sources: rejected because it
  prevents reliable semantic equivalence.
- Literal translation only: rejected because localization still needs cultural
  and rhetorical adaptation under controlled fidelity rules.
