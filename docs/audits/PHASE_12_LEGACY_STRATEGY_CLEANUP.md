# Legacy Emtedad TopicStrategy Cleanup

## Scope

The former fixed strategy layer was removed before the replacement content
strategy is designed. The controlled operation targets only `TopicStrategy`,
`TopicStrategyNode`, and their tree-use records.

## Safety boundary

The reset command is available as:

```text
python -m app.cli strategy reset
python -m app.cli strategy reset --confirm
```

The first command is a read-only preview. The second performs the destructive
operation. Dynamic `ContentTopic` records, knowledge, research packages,
semantic masters, drafts, language tracks, and editorial projects are not
deleted.

Projects that referenced a fixed node are detached and retain a
`strategy_topic_snapshot` containing the historical strategy version, branch,
title, question, and capture time.

## Development database result

Preview before reset:

- strategies: 1
- nodes: 111
- roots: 1
- branches: 10
- fixed topics: 100
- usage records: 6
- historical projects: 6

After the confirmed reset:

- strategies: 0
- nodes: 0
- usage records: 0
- dynamic topics: 44
- editorial projects: 8
- research packages: 13
- semantic master versions: 10
- Persian drafts: 15
- multilingual tracks: 16
- knowledge sources: 75
- Ayin canon versions: 1
- Manasek source versions: 1
- historical project snapshots: 6

A second reset is a no-op preview with all strategy counts at zero.

## UI behavior

`/strategy` now renders an explicit empty state and never regenerates the
legacy tree automatically. The dynamic topic workspace, Studio, and text
library remain available and were checked with HTTP 200 responses after the
cleanup.

## Verification

Unit tests, Ruff, mypy, and Alembic checks pass. The isolated integration
regression is included in
`tests/integration/core/test_strategy_reset.py`; it requires the configured
`EMTEDAD_DATABASE_URL` test-database environment used by the repository's
other PostgreSQL integration tests.
