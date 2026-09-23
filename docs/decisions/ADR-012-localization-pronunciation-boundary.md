# ADR-012: Separate Localization Semantics from Pronunciation Preparation

Status: Accepted
Date: 2026-09-23

## Decision

Phase 9 localizations target Persian (`fa`), German (`de`), English (`en`),
and Arabic (`ar`). Each localization statement stores publication-quality
`display_text` separately from provider-aware `tts_text`. Semantic approval
does not imply speech readiness.

Critical terminology is versioned in a pronunciation lexicon with language,
provider representation, transliteration/IPA/SSML fields, criticality, and
editorial status. Persian and Arabic have explicit preparation boundaries for
vowels/diacritics; German and English use language-specific lexicon profiles.
No audio is generated in this phase.

## Quality gates

Claim alignment, epistemic/citation preservation, terminology coverage, and
pronunciation coverage are deterministic validation dimensions. A localization
cannot become `READY_FOR_TTS` until critical pronunciation entries are
approved and validated. Future audio QA consumes the localization version and
provider output through a separate boundary.
