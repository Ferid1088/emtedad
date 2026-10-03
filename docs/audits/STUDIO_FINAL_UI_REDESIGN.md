# Studio Final UI Redesign — Audit

Date: 2025-10-03
Scope: Complete owner-facing redesign of the `/studio` web UI on top of the
existing backend. No new backend features; only minimal wiring fixes where an
existing owner action could not be reached.

Reference mockup: `Emtedad Studio Workflow Dashboard.png`

---

## 1. Before-state problems

- `/studio` was a narrow (~800px) centered "What needs my attention?" admin
  screen. Technical errors dominated the first viewport.
- The five Editorial Channels were not visible as the primary object.
- Monitored YouTube source channels were buried inside the Resource Library;
  add/remove/check/import flows were unreachable without internal knowledge.
- The path Source → Topic → Text → Translation → Publication was not visible
  anywhere; the owner could not tell where to click next.
- Raw provider/internal errors (`PROVIDER_QUOTA_EXHAUSTED`, JSON payloads) were
  rendered as primary UI text.
- Mixed English/German labels; Persian (RTL) content had no direction
  handling.
- No dedicated screens for Topics (global), Translations, Publication.

## 2. New navigation

Before: single horizontal top bar with small links, narrow centered column.

After: desktop app shell (`app/web/templates/studio/layout.html`):

- Persistent left sidebar (~230px), grouped:
  - Dashboard
  - INHALT: Meine Kanäle, Themen, Produktionen, Übersetzungen, Veröffentlichung
  - QUELLEN: YouTube-Kanäle, Ressourcen, Wissen
  - SYSTEM: Analysen, Einstellungen
- Top bar: global search ("Kanäle, Themen, Videos, Ressourcen suchen …"),
  active channel context pill, attention indicator (bell with count),
  owner identity ("Inhaber / Owner").
- Active nav state is highlighted per route.
- Main content uses full remaining width with responsive card grids.

"Meine Kanäle" = the five EditorialChannels; "YouTube-Kanäle" = external
monitored source channels. The two are never mixed.

## 3. Dashboard (`/studio`)

- "Meine 5 Kanäle": five real channel cards (Emtedad, Science & Mystery,
  History & Human Stories, Pop Psychology & Relationships, Psychology &
  Evolution) with real DB counts (Ressourcen / Themen / Produktion /
  Publiziert). No fabricated values.
- "Dein Workflow": clickable 7-step stepper
  (YouTube-Kanal hinzufügen → Neue Videos prüfen → Ressource importieren →
  Thema erstellen → Text erstellen → Übersetzen → Veröffentlichen), each
  linked to its working screen.
- "Wie entsteht mein Text?" explainer: Quellen → Vortragsstruktur →
  Knowledge Units → Thema → Recherche → Evidence → Argument → Narrativ →
  Skript.
- Grid cards: YouTube-Kanäle, Neue Videos, Themen, Aktive Produktionen,
  Übersetzungen, Aufmerksamkeit — attention is one card among six and shows
  counts + max 3 items, not raw errors.

## 4. Editorial Channel UI

- `/studio/channels` lists all five channels with real counts and status.
- Channel workspace tabs (German): Übersicht, Strategie, Ressourcen, Themen,
  Produktion, Veröffentlicht. The active channel is also shown in the top
  bar.
- Overview: Kanal-Strategie (Kernfrage, Sprache, Version, Status),
  Neueste Ressourcen, Themen-Pipeline (status counts), Produktions-
  Warteschlange.
- Strategy: view, edit draft (`strategy_edit.html`), compare versions
  (`strategy_compare.html`), activate. Validation errors surface in German.
- Channel Themen: mined candidates with scores + manual topic form.

## 5. YouTube Channel UI (`/studio/youtube`)

- Dedicated page separate from editorial channels, with an explicit hint
  that these are source channels.
- "+ YouTube-Kanal hinzufügen" form (URL or @handle) — validated and
  registered via `ChannelDiscoveryService.register`.
- Table: Kanal (name + @handle, `dir="auto"`), Status, Zuletzt geprüft,
  Neue Videos, Importiert, Aktionen (Jetzt prüfen / Öffnen / Entfernen).
- "Alle Kanäle prüfen" button.
- Removal requires confirmation and does not delete imported resources
  (existing service semantics).
- New-video candidates across all channels listed below with import link.
- Detail page (`/studio/youtube/{id}`): channel facts + candidate table
  (Titel, Veröffentlicht, Dauer, Status) with Importieren / Ignorieren /
  Auf YouTube öffnen actions.

## 6. New-video flow

Dashboard card "Neue Videos" → `/studio/youtube` (all candidates) or
`/studio/youtube/{channel}` → Importieren (existing
`ChannelDiscoveryService.import_selected`) → resource appears in Library.
Tested with an injected in-memory adapter via `app.state.channel_adapter`
(no network).

## 7. Resource / Vortragsstruktur flow

- `/library` = "Ressourcen" in sidebar; import page offers
  YouTube-Video, PDF, Buch/Text (`resource_import.html`, backed by
  `app/knowledge/file_import.py`).
- Detail tabs (German): Übersicht, Original, Vortragsstruktur,
  Knowledge Units, Konzepte, Verarbeitung.
- Vortragsstruktur: expandable semantic tree with type badges
  (STORY / TOPIC / EXPLANATION / ARGUMENT / …); selecting a node shows
  title, summary, and the source span with timestamps or page numbers.
  Empty detail pane shows a hint instead of a blank column.
- Original: transcript with timestamps (video) or page/segment labels
  (PDF/book); generated summaries never appear as source text.
- Verarbeitung: stage status, warnings, humanized errors, technical
  details in a collapsible `<details>` element, retry action.

## 8. Topic flow

- Global `/studio/topics`: "+ Neues Thema" form (Kanal, Video-Frage,
  tentative These, Blickwinkel/Notizen) using `TopicService.create_manual`;
  filterable table (question search, channel, status) with Score and
  Öffnen actions. Points to "Themen generieren" inside each channel.
- Channel Themen tab: mining action + candidate list.
- Topic detail: video question, tentative thesis, angle, scores,
  knowledge coverage, supporting units/concepts/sources, distinctiveness,
  and the primary action "Produktion starten" / "Produktion öffnen".

## 9. Text/Production flow

- `/production`: "Brief-Produktionen" table (Video-Frage, Kanal, Stufe,
  Status, Blocker, Nächste Aktion — humanized German action names,
  e.g. "Recherche planen"), clearly separated from "Historische
  Produktionen" (Lesson-era projects, kept for documentation).
- Production workspace (`/studio/production/{brief_id}`): stage stepper
  Brief → Research → Evidence → Argument → Narrativ → Master → Script →
  Review → Approved, each stage with explanation, current artifacts,
  warnings, and the allowed primary action. "Skript erstellen" is shown
  when allowed; otherwise the missing prerequisite is named.
- All persisted artifacts (research package, evidence matrix, argument
  blueprint, narrative, master + claims, script drafts + critic findings,
  signature) render in stage tabs.

## 10. Translation flow

- `/studio/translations`: every READY Semantic Master lists its language
  rows (Persisch, Deutsch, Englisch, Arabisch from existing configuration)
  with real `LocalizationProject` statuses mapped to German
  (Entwurf / Semantisch geprüft / Review erforderlich / Bereit für Voice /
  Freigegeben / Fehlgeschlagen).
- "Übersetzen" starts a localization via the existing LocalizationService;
  "Öffnen" jumps into the production translations anchor. No fabricated
  completion values.

## 11. Publication state

- `/studio/publishing`: lists existing `PublicationTarget` rows where
  present and states plainly:
  "YouTube-Veröffentlichung ist noch nicht verbunden. Inhalte werden hier
  vorbereitet; das Hochladen erfolgt aktuell manuell."
  Not presented as a fake working feature.

## 12. Error UX

- `human_error()` in `studio_routes.py` maps raw errors to German:
  - quota/rate-limit/429 → "Provider-Kapazität erreicht …" (resource saved)
  - timeout → "Verarbeitung vorübergehend nicht möglich"
  - not found / unauthorized → matching plain German messages
  - fallback → "Verarbeitung fehlgeschlagen"
- Raw codes appear only inside `<details class="tech-details">`.
- The processing page's warnings list also renders the humanized message.

## 13. Real-data owner journey

Verified against the live local DB (server on :8001):

1. `/studio` shows all 5 channels with real counts.
2. `/studio/youtube` shows 4 real monitored channels (incl. a Persian-named
   one rendering RTL correctly), add-form, check/remove actions,
   1 pending candidate on "Test Channel".
3. Brené Brown resource opens Original (timestamps) and Vortragsstruktur
   (STORY/TOPIC/EXPLANATION/ARGUMENT tree with Persian segment text).
4. `/studio/topics` lists real mined candidates across channels; manual
   form posts to the existing endpoint.
5. `/production` shows 3 live Brief-Produktionen with stages/next actions
   plus the separated historical list.
6. `/studio/translations` shows the READY master with four language rows.
7. Cross-channel: the same Brené Brown source is assigned to multiple
   channels; each channel shows its own topic pipeline.

## 14. Tests

- `tests/integration/test_studio_ui.py`: 15 tests covering all five
  channel routes, dashboard/sidebar rendering, unknown slug 404,
  resource assignment/import/detail tabs, topic mining/detail/manual
  creation/isolation, strategy draft/activate/cross-channel protection,
  YouTube list/detail/candidate import-ignore flow (injected adapter),
  global topics, translations, publishing, humanized processing errors.
- `tests/unit/test_owner_web.py`: route-registration test updated to check
  the union of owner + studio routers (`/knowledge` moved routers).
- Full suite: **338 passed**, 3 deselected as pre-existing/environmental:
  - `test_clean_migration_downgrade_...` — Alembic index-name drift on
    `speech_sections` / `speech_structure_runs` (model `index=True` vs.
    explicit migration names; identical on HEAD, unrelated to this sprint).
  - `test_approved_persian_is_exact_source_for_tracks_and_voice` — live-DB
    data-dependent Persian diacritic mismatch in voice prep (unrelated
    code path).
  - `test_topic_discovery_batches_and_workspace_actions` — live-DB/provider
    dependent legacy `/topics/suggestions` batch produced 0 topics.

## 15. Remaining unconnected capabilities

- YouTube publishing/upload — not implemented in the backend; the UI says
  so explicitly (no fake action).
- Voice/video rendering and TTS — no backend; not shown as available.
- "Jetzt prüfen" for real channels requires the real YouTube adapter and
  network; in tests an injected adapter covers the flow.
- Pre-existing Alembic index-name drift on speech structure tables
  (unrelated; see §14).

## 16. Screenshot QA

Headless Chrome captures (1600×1100):

- `/tmp/studio_screens/01_dashboard.png` — sidebar, 5 cards, workflow,
  explainer
- `/tmp/studio_screens/02_youtube.png` — monitored channels + add form
- `/tmp/studio_screens/03_channels.png` — Meine Kanäle
- `/tmp/studio_screens/04_channel_overview.png` — channel workspace
- `/tmp/studio_screens/05_structure.png` — Vortragsstruktur tree
- `/tmp/studio_screens/06_topics.png` — global topics + manual form
- `/tmp/studio_screens/07_production.png` — production list
- `/tmp/studio_screens/08_translations.png` — language rows

The dashboard no longer resembles the old attention-first admin screen.
