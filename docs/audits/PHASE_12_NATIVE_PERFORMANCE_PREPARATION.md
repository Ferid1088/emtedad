# Phase 12 — Native performance preparation

This checkpoint adds the text-only boundary between editorial language and a
future external voice-generation request.  It does not call ElevenLabs and
does not create audio.

## Three representations

Each `EditorialLanguageTrack` keeps:

1. `display_text`: publication text with no provider markup;
2. `voice_ready_text`: the same text with selective pronunciation guidance;
3. `elevenlabs_performance_text`: an inspectable provider-input candidate,
   optionally containing sparse Eleven v3 audio tags.

The third value is never used as a substitute for either publication text or
voice-ready text.  A migration adds the nullable field without changing
existing tracks.

## Native-language boundary

`NativeLanguageReviewer` runs before performance direction and flags visible
research scaffolding, empty text, and obvious repetitive rhythm.  The
`NativeLanguageOptimizer` is an explicit identity-preserving boundary in this
checkpoint: any future model-backed rewrite must create a new translation
version and cannot overwrite owner text.  A final review is therefore required
before a provider script is accepted.

## Pronunciation and performance

Persian preparation selectively handles recurring Ayin terms and high-risk
Ezafe compounds (including `آیینِ امتداد` and `راهِ زندگی`).  Arabic uses
selective Tashkil for recurring terms.  `pronunciation_preserves_text` strips
only pronunciation marks and normalizes provider-added whitespace to verify
lexical identity.

`ElevenLabsCapabilityProfile.eleven_v3()` records the supported audio-tag
categories and explicitly disallows SSML breaks.  `PerformanceDirector` adds
no tags by default; callers must provide sparse paragraph cues.  The
`PerformanceQualityValidator` checks supported tags, SSML leakage, density,
repetition, and unchanged text content.

The workspace exposes an explicit “ElevenLabs-Text vorbereiten” action only
after semantic and voice-ready gates pass.  The action stores text and
provenance; it never contacts an external provider.
