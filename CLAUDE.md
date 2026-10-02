# CLAUDE.md — Ayin-e Emtedad content production

This repository preserves Ayin-e Emtedad, models Manasek, researches external
knowledge, and produces evidence-grounded video scripts in Persian (with
German, English, and Arabic tracks).

`AGENTS.md` is the canonical repository contract. Read it before any task, plus:

1. `docs/execution/CURRENT_PHASE.md` — the only active scope.
2. `docs/architecture/DOMAIN_RULES.md` — binding domain invariants.
3. `docs/implementation/AGENT_HANDOFF.md` and
   `docs/implementation/Channel_Memory_Spec_v2.md` — the production-memory
   architecture.
4. Relevant accepted ADRs in `docs/decisions/` (notably ADR-012 and ADR-013).

## Content production workflow

`/produce-lesson <lesson_id>` orchestrates the agent pipeline:

```
OWNER -> producer -> researcher -> script-writer
      -> ayin-guardian + fact-checker + continuity-editor
      -> revision (max 3 rounds) -> OWNER APPROVAL STOP -> packager
```

Agent definitions live in `.claude/agents/`. The owner approval gate is a hard
stop: no reviewer outcome, test result, or "no blockers" state counts as owner
approval, and `packager` runs only after an explicit owner approval message.

## Canonical data sources

- Lesson canon (read-only): `resources/editorial/lesson_canon/lessons.json`,
  `lesson_relations.json`, `Ayin_Emtedad_100_Dars.md`. Field names are fixed
  (`lesson_id`, `chapter`, `title_fa`, `prerequisites`, `text_fa`,
  `relations_section_fa`, ...); never invent fields or provenance.
- Production status, drafts, language tracks, and the Channel Ledger live in
  PostgreSQL (`content` schema). Read them through:
  - `.venv/bin/python -m app.cli lessons status [lesson_id]`
  - `.venv/bin/python -m app.cli lessons package <lesson_id>`
  - `.venv/bin/python -m app.cli lessons ledger [lesson_id]`
  Never fabricate publication state; if the database is unreachable, report it.
- External knowledge: `.venv/bin/python -m app.cli knowledge ...` and
  `retrieval search --lane external ...`.

## Non-negotiable boundaries

- Ayin Canon/Working, Manasek Canon/Working, external primary/derived, and
  generated content stay separate. External material may dialogue with Ayin
  but never redefines it.
- Five gates, seven individual stages, plus Return. Return is not a gate.
- Writer context = Lesson Content Package + research brief + persona/style
  constraints only. Channel Ledger and published-script archive are
  post-draft review inputs, never generation input.
- No git commit, git push, publishing, audio generation, or secret access.
- `.env*` files and credentials are never read, printed, or embedded.
- Working artifacts go under `tmp/lesson-pipeline/<lesson_id>/` only.
