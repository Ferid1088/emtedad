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
background. It does not generate research packages, prose, translations,
voice, audio, video, or publishing output in this checkpoint.
