# Phase 12 — Emtedad topic strategy and editorial workspace

This checkpoint introduces a durable strategy layer above the existing
dynamic topic inbox. A strategy is versioned and grounded in the stored Ayin
concept/version records. Its hierarchy is root → concept branch → fixed topic;
the development corpus currently produces 10 branches and 100 fixed leaf
topics. Each leaf carries concept/version IDs, source passage ID, definition,
and an editorial rationale.

Fixed strategy records are separate from `ContentTopic` AI/user topics. An
approved strategy is immutable. Using a fixed topic creates an
`EditorialProject` and an immutable `TopicUseHistory` record, increments the
leaf's use count, and keeps the leaf selectable for another project.

The owner UI provides `/strategy`, grounded topic detail, `/studio`, and a
research workspace shell. The workspace explicitly distinguishes Ayin,
optional Manasek, local knowledge, explicit web research, and unsourced LLM
background.

## Final checkpoint: approved Persian multilingual production

An approved `PERSIAN_APPROVED` `PersianDraft` is the sole editorial source
for publication tracks. The `EditorialLanguageTrack` table pins every track
to that exact Persian draft and its Semantic Master. FA is copied byte-for-
byte; DE, EN, and AR are generated independently from FA (never chained).
Track provenance records the source draft, master, direct-source mode,
version, word count, and duration estimate. Later Persian revisions therefore
create a new source version rather than mutating existing tracks.

Voice preparation is text-only. `MultilingualEditorialService.prepare_voice`
uses the existing versioned pronunciation boundary and sets a track to
`READY_FOR_VOICE`; no ElevenLabs call, audio file, or synthesis is performed.
The standalone `/studio/voice` utility accepts arbitrary FA/DE/EN/AR text and
returns display and voice-ready text without a topic or research dependency.
Persian generation now bounds initial drafts to the configured spoken-word
range (the 15-minute profile is 99–121 words per minute); owner edits are
never rewritten and are recalculated instead.

The workspace exposes explicit translation and voice-preparation actions.
Translations are unavailable until Persian approval, and voice preparation
is a separate action. This checkpoint creates no German, English, or Arabic
text implicitly and does not produce audio, video, or publication output.
