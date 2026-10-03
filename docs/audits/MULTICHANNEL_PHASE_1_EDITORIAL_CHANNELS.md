# Multichannel Migration — Phase 1: Editorial Channel Domain

Date: 2026-10-03

## Scope

Create the five editorial verticals (`Emtedad`, `Science & Mystery`,
`History & Human Stories`, `Pop Psychology & Relationships`,
`Psychology & Evolution`), versioned channel strategies, and shared-resource
assignment — as specified in
`docs/EMTEDAD_CODING_AGENT_MASTER_IMPLEMENTATION_PROMPT.md` Phase 1.

## Files changed

- `app/editorial_channels/__init__.py` — new package
- `app/editorial_channels/domain.py` — status/role enums and the five channel
  seed definitions (domains, angles, special agent roles, channel-specific
  policy overrides)
- `app/editorial_channels/models.py` — `EditorialChannel`,
  `ChannelStrategyVersion`, `EditorialChannelResource` in the `content` schema
- `app/editorial_channels/schemas.py` — read-boundary schemas incl.
  `ChannelSummary`
- `app/editorial_channels/service.py` — `EditorialChannelService` with
  `seed_channels`, `list_channels`, `get_channel`, `get_active_strategy`,
  `list_strategies`, `create_strategy_draft`, `activate_strategy`,
  `assign_resource`, `unassign_resource`, `list_channel_resources`,
  `channel_summaries`
- `alembic/versions/d4e5f6a7b8c9_add_editorial_channels.py` — forward
  migration
- `tests/integration/test_editorial_channels.py` — new
- `docs/decisions/ADR-014-*`, `docs/decisions/README.md` — from Phase 0

## Migration

`d4e5f6a7b8c9` (revises `c7d8e9f0a1b2`): three tables and three enum types in
`content`. One-active-strategy enforced by partial unique index
`uq_channel_strategy_one_active`; `unique(editorial_channel_id,
version_number)`; `editorial_channel_resources` composite PK
`(editorial_channel_id, source_id)` references `knowledge.sources` with
`RESTRICT` so a Source can never be silently deleted while assigned.

## Behavior

- `seed_channels()` is idempotent: five channels, one ACTIVE v1 strategy each.
- `create_strategy_draft` increments `version_number` and clones the active
  policy payload; `activate_strategy` archives the previous ACTIVE version in
  the same transaction (partial index is a second line of defense).
- `assign_resource` links an existing `knowledge.sources` row; upsert updates
  relevance/role; `unassign_resource` removes only the link row.

## Tests run

- `uv run ruff check app/ tests/` — pass
- `uv run ruff format` on new files — applied
- `uv run mypy --strict app` — pass (158 files)
- `uv run pytest tests/unit -q` — 232 passed
- `EMTEDAD_DATABASE_URL=... uv run pytest tests/integration/test_editorial_channels.py` — 5 passed:
  seeding/idempotency, multi-channel assignment without source duplication,
  single-active strategy + version increments, unassign keeps source,
  unknown slug raises `ChannelNotFoundError` (404).
- `alembic upgrade head` applied on the dev database.

## Known limitations

- `ChannelSummary` topic/production/published counts are real `0`s pending
  the channel-scoped topic and production tables of later phases; they are
  populated by queries, not constants, as those tables land.
- No UI yet — Phase 2 adds the Studio shell.

## Next phase

Phase 2 — Working Studio UI shell (`/studio`, channel workspaces, resource
library routes, `studio.css`).
