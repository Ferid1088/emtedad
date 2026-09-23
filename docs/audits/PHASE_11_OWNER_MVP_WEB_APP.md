# Phase 11 — Owner MVP Web App

## Scope

Phase 11 adds the first owner-facing web application for source ingestion,
knowledge browsing, and topic discovery. It stops before Research Engine
execution, lecture generation, localization, and publication.

## UI architecture

The application uses the existing FastAPI process with Jinja2 templates,
server-rendered HTML, a small CSS file, and no second frontend framework.
Navigation is German-first: Dashboard, Quellen, Wissensbasis, Themen.

Routes cover the dashboard, source list/add/detail, knowledge tabs, topic
suggestions, manual topic analysis/save, and topic detail. Templates use
Jinja escaping; ingestion errors return a bounded user-facing message and
never a traceback.

## Source flow

`POST /sources` validates a YouTube locator with the existing adapter and
invokes `ExternalKnowledgeImporter` with the existing YouTube adapter and
structured extraction provider. No downloader, transcript, extraction, or
resolution pipeline was duplicated. Source detail exposes transcript
timestamps, claims, mentions, and review flags with their stored provenance.

## Knowledge base

`/knowledge` provides Sources, People, Works, Claims, References, and Review
views. Unknown or unresolved values remain visibly unresolved. The dashboard
uses live counts from the knowledge schema.

## Topic discovery

`TopicSuggestionService` builds a small grounded context from current Ayin
concept identities, knowledge counts, works, and existing Phase 10 topics.
Suggestions are structured and deterministic, with provenance labels and
overlap scores; they do not invent database identifiers or begin research.
`TopicAnalysisService` reports concept matches, available sources/claims,
works/people, similar topics, and warnings. Warnings are advisory: owners can
still save a topic.

Phase 10 `content.content_topics` is reused. A reversible `topic_origin`
column distinguishes `AI_SUGGESTED`, `USER_CREATED`, and legacy rows. Saving
sets a planned topic only; it creates no ResearchProject, ResearchPackage,
Semantic Master, localization, or publication artifact.

## Real MVP QA

Against the development database the dashboard reported 1 source, 1 YouTube
video, 2,151 transcript segments, 71 people, 17 works, 372 claims, 425 open
review items, and 3 existing topics. The source was opened successfully;
source detail and all knowledge tabs rendered. Five grounded suggestions were
returned, including pattern continuation, change and identity, and between
two people. Invalid YouTube input returned a friendly validation page. Manual
topic analysis rendered source/claim/overlap warnings and saving remains a
separate owner action.

No real new YouTube download was performed during QA, so the development
corpus was not modified by an external network acquisition.

## Verification and limitations

Changed-file Ruff and strict mypy pass; migration upgrade and Alembic drift
check pass with the configured development database. Unit web tests cover URL
validation, route registration, and overlap determinism. The full suite's
database integration tests require `EMTEDAD_DATABASE_URL` when run outside the
configured environment. Ingestion is synchronous in this MVP and therefore
reports completion after the existing importer returns; lightweight polling
can be added later if a job runner is introduced.

The suggestion service intentionally favors grounded, conservative structure
over autonomous topic invention. Research remains an explicit future action.
