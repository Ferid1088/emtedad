---
description: Run the full lesson production pipeline for one canonical lesson, with independent review and a hard owner-approval gate before packaging.
argument-hint: <lesson_id> e.g. 1.1
---

Orchestrate production of lesson `$ARGUMENTS` through the agent pipeline.
Read `AGENTS.md`, `docs/architecture/DOMAIN_RULES.md`, and
`docs/implementation/Channel_Memory_Spec_v2.md` first if you have not.

Artifacts for this run live under `tmp/lesson-pipeline/$ARGUMENTS/`.
Create it if needed.

## Pipeline

### 1. PRODUCER

Launch the `producer` subagent with lesson id `$ARGUMENTS` (or ask it to
select the next lesson if the argument is empty).

- Require a production brief with the real project_id and prerequisite
  status. If prerequisites are unmet or the DB is unreachable, STOP and
  report to the owner.

### 2. RESEARCHER

Launch the `researcher` subagent with the lesson_id, project_id, and any
owner focus.

- Require a research brief: research package id, semantic master id,
  per-evidence provenance and verification_status, counterevidence,
  unsupported areas.

### 3. SCRIPT-WRITER

Launch the `script-writer` subagent with ONLY:

- the Lesson Content Package (or `lessons package $ARGUMENTS` output),
- the research brief,
- owner persona/style constraints (owner_prompt, target minutes).

Never pass Channel Ledger prose, published scripts, or the external corpus
to the writer. The writer writes `tmp/lesson-pipeline/$ARGUMENTS/draft-v1.md`.

### 4. REVIEW (parallel)

Launch `ayin-guardian` and `fact-checker` in parallel on the draft. When
both return, launch `continuity-editor` on the same draft (continuity runs
after the initial draft exists — it needs ledger context, not writer
input).

### 5. REVISION LOOP (maximum 3 rounds)

- If ANY reviewer reports a BLOCKING finding: send the writer ONLY the
  findings and constraints needed for revision — never archived prose —
  and have it write `draft-v<N+1>.md`. Then re-run the relevant reviewers.
- After 3 rounds with remaining blockers, STOP and escalate to the owner.
- If no blocking findings remain: proceed to the owner gate.

### 6. OWNER APPROVAL — HARD STOP

STOP. Present the owner: the draft file path, word count, all reviewer
verdicts, every non-blocking finding, open questions, and continuity
constraints applied.

Do NOT proceed until the owner replies with explicit approval of this exact
draft version. None of the following count as approval: reviewers passing,
zero blocking findings, tests passing, silence. Only an explicit owner
approval message unblocks step 7.

### 7. PACKAGER

Only after explicit owner approval: launch the `packager` subagent with the
lesson_id, project_id, approved draft path, and the approval reference.

The packager registers the approved text via `lessons draft` (which runs the
deterministic review suite) and writes packaging artifacts under
`tmp/lesson-pipeline/$ARGUMENTS/packaging/`. Nothing is published, uploaded,
or sent to a TTS provider.

## Final report to the owner

Report: lesson id, project id, research package + semantic master ids,
revision rounds used, final reviewer verdicts, draft id registered, the
deterministic-review result, packaging artifact paths, and the next owner
action (review findings + approve the draft in the workspace UI).
