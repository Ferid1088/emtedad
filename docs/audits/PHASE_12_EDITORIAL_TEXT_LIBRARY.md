# Phase 12 — Editorial Text Library

The owner-facing `/texts` library is a view and lifecycle layer over the
existing `EditorialProject`, `PersianDraft`, and `EditorialLanguageTrack`
records.  It introduces no competing text table and therefore preserves all
existing provenance, version history, approval gates, and source links.

The library supports search, status/origin/language filters, sorting, stable
project URLs, archived/restore actions, and duplication into a new production
shell.  A detail view exposes FA/DE/EN/AR display text independently from
voice-ready and optional ElevenLabs-performance text.  Copy actions operate
on exactly one representation at a time, and export returns the same content
plus project, language, version, and provenance metadata as JSON.

Strategy-topic and dynamic-topic detail pages link their existing projects to
the library.  Studio remains the creation workspace; Texte is the durable
discovery, inspection, reuse, and export surface.
