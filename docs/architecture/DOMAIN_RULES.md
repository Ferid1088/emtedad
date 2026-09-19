# Domain Rules

These rules summarize implementation invariants. The approved source PDFs and
the master specification remain authoritative.

## Source-of-truth zones

Keep these zones explicit and separately queryable:

1. `AYIN_CANON`
2. `AYIN_WORKING`
3. `MANASEK_CANON`
4. `MANASEK_WORKING`
5. `EXTERNAL_PRIMARY`
6. `EXTERNAL_DERIVED`
7. `GENERATED_CONTENT`

Movement into a canonical zone requires editorial approval and a versioned
workflow.

## Ayin invariants

- Canonical passages must remain traceable to document, source/editorial
  version, extraction run, and location.
- Extraction tooling changes create reproducible extraction runs, not new
  intellectual/source versions.
- Concepts, distinctions, principles, open questions, and terminology are
  versioned rather than overwritten.
- Preserve discourse type instead of flattening philosophical, symbolic,
  practical, and other statements into one epistemic category.
- External agreement does not make an Ayin claim scientifically proven.
- External disagreement is stored as dialogue or conflict, not suppressed.
- Generated lectures and translations remain derived content.

## Conceptual order

Preserve the canonical conceptual relationships and do not improvise
translations. In particular, the project treats Emtedad, Bon, Jan, and Jan-e
Jan as controlled terms whose preferred translations and aliases require the
terminology registry and review process.

## Manasek invariants

- Manasek is the experiential and practical layer of Ayin.
- It is not evidence proving Ayin.
- Gate rituals, relational/between rituals, and life rituals remain typed.
- There are exactly five gates.
- There are seven individual stages.
- Each individual stage has a Return.
- Return is not a sixth gate.
- Five gates across seven stages produce 35 gate pieces.
- Seven Returns produce 42 individual pieces in total.
- Collective ritual architecture is separate from the individual architecture.
- Gates are symbolic attentional perspectives, not Bon or metaphysical
  elements.
- Ordered stages are sequences, not mandatory calendar days.
- Between and Life ritual identities may exist without fabricated ritual
  versions when the source does not define sufficient content.
- Ayin links pin real concept versions and source passages. Missing concepts
  remain typed proposals rather than being created as Canon automatically.

## Ritual safety

Every ritual remains optional and preserves:

- informed choice;
- consent;
- right to stop;
- right to leave;
- non-coercion;
- non-interpretation of participant experience;
- appropriate warnings, exclusions, and review requirements.

Safety policies must be machine-enforced and tested. A generation workflow
cannot bypass a failed or unresolved safety decision.

Approved rituals require a Canon source version, complete required safety-rule
bindings, a passing deterministic safety validation, and no open blocking
safety review. A localization must retain the exact safety bindings of its
parent ritual and cannot weaken stop, leave, consent, or optionality language.

## Lecture invariants

Every Ayin lecture:

- has a validated Ayin Spine;
- pins the Canon versions it uses;
- keeps Ayin as its conceptual center;
- distinguishes Ayin claims, external claims, criticism, and interpretation;
- preserves provenance and uncertainty;
- includes substantive limitations or counterevidence where appropriate;
- links to Manasek only when conceptually justified and safe;
- never treats ritual intensity as truth;
- binds citations at statement level;
- passes Ayin-fidelity, epistemic, and citation validation.

## Multilingual invariants

- Persian, English, and Arabic derive from one Semantic Master.
- Language versions preserve concept IDs, claim IDs, epistemic status, and
  citations.
- Localization must preserve uncertainty and optional metaphysical status.
- Local enrichment must be distinguished from the shared evidence core.
- Unsupported claims and silent terminology drift are prohibited.

## Ambiguity rule

When wording, meaning, terminology, translation, classification, or source
identity is unclear: preserve the ambiguity, create a review item, and do not
invent certainty.
# External knowledge rules

- External provider content is stored only as `EXTERNAL_PRIMARY` in Phase 4.
- Source identity, immutable source version, raw segment, extraction window,
  extraction run, mention, claim, and resolution candidate are distinct.
- Raw transcript text and timestamps are immutable; normalization is derived
  and separately stored.
- Extracted claims are attributed assertions, never automatic truth or Ayin
  principles. Resolution of a cited work does not verify a claim.
- Ambiguous external identities retain candidates and review state. Strong
  identifiers may deduplicate; uncertain names and titles must not auto-merge.
- External material does not create Ayin/Manasek Canon or cross-domain dialogue
  judgments. Those require later explicit editorial workflows.
