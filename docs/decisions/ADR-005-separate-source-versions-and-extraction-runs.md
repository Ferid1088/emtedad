# ADR-005: Separate Source Versions from Extraction Runs

- Status: Accepted
- Date: 2026-09-19

## Context

The same immutable Ayin PDF produced 1,019 passages with Poppler 26.08.0 and
1,018 passages with Poppler 25.03.0. Phase 2 included extractor identity in the
document-version key, which incorrectly represented tooling variance as two
intellectual/source versions.

## Decision

Represent four identities separately:

1. `canon_documents` identify the intellectual document.
2. `canon_versions` identify source/editorial versions using document, source
   SHA-256, corpus zone, and explicit semantic/source-version metadata.
3. `extraction_runs` identify reproducible transformations using source
   version, source asset, importer, extractor, normalization, segmentation, and
   configuration identities. Each run records its output hash and counts.
4. `canon_passages` belong to exactly one extraction run and retain their source
   version and asset pins.

Store the preferred run in a separate, one-row-per-source-version typed table.
Preference requires an explicit operator identity and reason; imports never
choose it automatically. Changing preference retains every run and passage.

Review items pin an extraction run and use a specific reason enum. Structured
editorial identities remain stable across reruns; a rerun does not reload the
reviewed seed when that source version already has structured data.

## Consequences

- Parser upgrades no longer create false Ayin source versions.
- Multiple passage sets can be compared and reproduced independently.
- Editorial evidence can trace the exact extraction passage and therefore its
  run, toolchain, configuration, and output hash.
- A source version can have no preferred run until deterministic/manual QA is
  complete.
- Downgrade to the old schema is refused once a source version has multiple
  runs because the old representation cannot retain them without data loss.
- Databases containing duplicate same-identity source versions must recreate
  their pre-production import; the migration refuses to guess a destructive
  merge.

## Alternatives considered

- Keep extractor version in `canon_versions`: rejected because tooling changes
  are not intellectual/source changes.
- Overwrite passages on re-extraction: rejected because it destroys
  reproducibility and review history.
- Automatically prefer the run with more passages: rejected because passage
  count does not establish extraction quality.
- Automatically merge duplicate historical source versions: rejected because
  competing editorial rows and evidence links cannot be reconciled safely
  without explicit review.
