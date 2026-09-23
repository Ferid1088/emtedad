# Phase 9 Localization Boundary Audit

Phase 9 stores four-language localization text for `fa`, `de`, `en`, and `ar`.
Each statement keeps publication-quality `display_text` separate from
pronunciation-prepared `voice_text`. The legacy physical `tts_text` column is
retained only for database compatibility and is not exposed as the domain
concept.

Semantic approval and voice readiness are distinct. `READY_FOR_VOICE` means
that text is ready to be sent to an external provider such as ElevenLabs; no
voice synthesis, audio generation, or audio-QA implementation exists here.

Implemented: versioned localization records, pronunciation lexicon entries,
Persian and Arabic preparation boundaries, claim-level semantic validation,
critical pronunciation validation, and provider-profile metadata.
