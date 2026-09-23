# ADR-013: Lesson Canon and Script-Generation Retrieval Boundary

Status: Accepted
Date: 2026-09-24

## Context

The approved 100-lesson canon already packages the Ayin-derived conceptual
content needed to produce each lesson. Retrieving the complete Ayin book again
for every ordinary script repeats the same foundational passages across many
lessons and encourages structural and linguistic convergence. Published script
prose creates a separate contamination risk when placed in a writer context.

The Ayin source corpus must remain available for provenance, audit, human
inspection, canon verification and revision, citations, and specialist research.
Removing it from ordinary generation is therefore a retrieval-boundary change,
not deletion or demotion of the intellectual source.

## Decision

Ordinary 100-lesson script generation uses four strictly distinct roles:

1. The directly loaded, content-hashed canonical `LessonContentPackage` is the
   Ayin core. Its canonical explanation is not recreated as a new AI-generated
   Ayin seed.
2. The Core Concept Registry supplies locked definitions selected directly from
   the lesson canon, without vector retrieval.
3. `EXTERNAL_KNOWLEDGE` is the only generative retrieval space. It may contribute
   attributed evidence, examples, perspectives, disagreement, historical
   context, alternatives, and counterarguments, but cannot redefine Ayin.
4. The Channel Ledger, Published Script Archive, and lesson-relation graph are
   post-draft review inputs. Published script prose is never writer context.

The complete Ayin corpus and its Ayin retrieval lane remain stored and usable
for provenance, audit, lesson-canon verification, canon revision, citations,
and explicit specialist research. They are not queried by the default lesson
research plan and raw Ayin passages are filtered out of the production writer
context.

Each generated draft pins the lesson ID, lesson-canon content hash, package
version, and provenance-completeness state. Supplied lesson-to-Ayin source
version, passage/page, concept, and distinction references are preserved. A
missing provenance mapping is an explicit review item and is never fabricated.

Generation and review are separate stages:

```text
GENERATION
Canonical Lesson Content + Core Concept Registry + External Research

REVIEW
Channel Ledger + Published Script Archive + Lesson Relations
```

## Consequences

- Repeated full-book retrieval can no longer homogenize the 100 production
  scripts.
- The writer cannot silently replace an approved lesson explanation with a new
  model-authored Ayin seed.
- Default lesson research retrieves external evidence and counterevidence only.
- Full-book search remains available outside the ordinary production path.
- Current lesson artifacts lack per-lesson Ayin source-version and passage/page
  mappings. Packages expose `MISSING_LESSON_AYIN_PROVENANCE` until an approved
  canon revision supplies them.
- Diversity remains an explicit production requirement across human questions,
  examples, sources, argument structures, openings, endings, and emotional
  movement.

## Alternatives considered

- Retrieve Ayin book chunks for every lesson: rejected because the approved
  lesson canon already contains the production meaning and repeated retrieval
  creates convergence.
- Generate a fresh Ayin seed from book retrieval: rejected because it adds an
  unnecessary model-authored authority layer over approved canon.
- Feed old scripts to the writer with instructions not to copy them: rejected
  because context exposure itself encourages paraphrase and repetition.
- Delete or stop indexing the Ayin corpus: rejected because provenance, audit,
  verification, revision, citations, and specialist research still require it.

## Supersedes / Superseded by

For ordinary 100-lesson script generation, this ADR supersedes the Ayin
retrieval and writer-input portions of ADR-002, ADR-010, and ADR-011. Their
versioning, provenance, epistemic separation, frozen external research, and
specialist-research decisions remain in force.
