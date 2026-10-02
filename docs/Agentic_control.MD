You have completed a pronunciation-lexicon feature.

STOP.

Do NOT add any more pronunciation, voice, localization, web UI, ElevenLabs, lexicon, or unrelated functionality.

The lexicon changes may remain untouched for now.

Your NEXT task is the original task:

VERIFY AND REPAIR THE `Emtedad_App` CONTENT-PRODUCTION AGENT SYSTEM.

The relevant system is primarily:

`.claude/agents/`
`.claude/commands/produce-lesson.md`
`.claude/settings.json`
`CLAUDE.md`
`AGENTS.md`

The target workflow is:

OWNER
↓
PRODUCER
↓
RESEARCHER
↓
SCRIPT-WRITER
↓
AYIN-GUARDIAN + FACT-CHECKER
↓
CONTINUITY-EDITOR
↓
REVISION IF REQUIRED
↓
OWNER APPROVAL
↓
PACKAGER

Do NOT invent another feature.

Do NOT improve the web application.

Do NOT work on pronunciation.

Do NOT work on voice generation.

Do NOT work on UI.

Do NOT work on localization unless a content-agent reference is objectively broken because of it.

Do NOT refactor unrelated application code.

Your job now is AUDIT → REPAIR → VERIFY the agent-production architecture that is already present.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — PRESERVE CURRENT WORK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

First run:

`git status --short`

Do not delete or revert the existing pronunciation-lexicon work.

Do not commit it.

Do not modify those files further unless absolutely necessary for the content-agent task.

Treat the following current files as OUT OF SCOPE:

- `app/localization/lexicon.py`
- `app/content_strategy/multilingual_service.py`
- `app/web/routes.py`
- `app/web/templates/base.html`
- `app/web/templates/lexicon.html`
- `tests/integration/test_owner_lexicon.py`
- `tests/unit/test_pronunciation_lexicon.py`
- `.vscode/extensions.json`

Leave them alone.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — READ THE AGENT SYSTEM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Read completely:

`AGENTS.md`

`CLAUDE.md`

`.claude/settings.json`

`.claude/commands/produce-lesson.md`

and every file in:

`.claude/agents/`

At minimum there should be definitions corresponding to:

- producer
- source-ingestor
- researcher
- script-writer
- ayin-guardian
- fact-checker
- continuity-editor
- packager

Do not edit yet.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — CREATE AN AGENT CONTRACT TABLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For EACH agent determine:

1. What input does it receive?
2. What repository information may it read?
3. What repository information must it NOT read?
4. What tools does it have?
5. What does it output?
6. Who consumes that output?
7. Can it mutate anything?
8. Can it bypass owner approval?

Create an internal table:

| Agent | Input | Allowed reads | Forbidden reads | Output | Next consumer |

Do this from the ACTUAL files.

Do not infer desired behavior yet.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4 — VERIFY EVERY REFERENCED FILE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Extract EVERY repository path mentioned by:

- `CLAUDE.md`
- `.claude/agents/*.md`
- `.claude/commands/*.md`

Check each path on disk.

Examples likely include:

`resources/editorial/lesson_canon/lessons.json`

`resources/editorial/lesson_canon/lesson_relations.json`

`docs/architecture/DOMAIN_RULES.md`

`docs/implementation/AGENT_HANDOFF.md`

`docs/implementation/Channel_Memory_Spec_v2.md`

`docs/execution/CURRENT_PHASE.md`

Do NOT assume these examples are correct.

For every reference classify it:

EXISTS

WRONG PATH

OUTDATED

MISSING

If a path is wrong/outdated, search the repository for the real source.

Example:

wrong:
`docs/foo.md`

actual:
`docs/bar/foo.md`

Then update the agent instruction to the REAL path.

DO NOT create duplicate files merely to satisfy an obsolete Markdown reference.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 5 — VERIFY LESSON CANON
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Inspect:

`resources/editorial/lesson_canon/`

Determine the REAL schema.

Verify:

- lesson ID
- title
- chapter/ordering
- lesson canonical text/content
- prerequisites
- relationships
- conceptual boundaries if represented
- review/status metadata if represented

Then inspect:

`lesson_relations.json`

or its real equivalent.

Confirm that agents are using the actual schema.

Do not let prompts mention fields or structures that do not exist.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 6 — VERIFY DOMAIN RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Find the actual repository source of truth for:

- Ayin vs external knowledge
- Ayin vs Manasek
- external evidence rules
- Five Gates
- Seven Stages
- Return
- metaphor rules
- provenance
- epistemic status
- domain boundaries

Do not rewrite these rules from memory.

The repository's established architecture wins.

Then compare `ayin-guardian.md` with those actual rules.

Fix discrepancies.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 7 — VERIFY ALL CLI COMMANDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Run:

`.venv/bin/python -m app.cli --help`

or the repository's actual canonical equivalent.

Do NOT run destructive commands.

Inspect available command groups.

For every CLI command referenced by an agent, verify its syntax using `--help`.

Especially check references involving:

- knowledge ingestion
- pending resolution
- validation
- review items
- retrieval
- building chunks
- research

Create a table internally:

| Agent | Referenced command | Exists? | Actual syntax |

If the agent prompt references a nonexistent or obsolete command:

FIX THE AGENT PROMPT.

Do not build another CLI simply because Markdown documentation is wrong.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 8 — VERIFY PRODUCER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The producer must:

- select/inspect lessons
- respect prerequisites
- know production/publication status from a REAL repository source
- report blocked lessons
- never invent publication status
- never write lesson prose

Critical question:

WHERE DOES PUBLICATION STATUS ACTUALLY LIVE?

Find it.

Possibilities may include:

- PostgreSQL
- an existing service
- CLI output
- production tables
- owner workspace

Do NOT assume.

Do NOT create a second JSON status store.

If the producer currently references a nonexistent status source, repair the instruction to use the actual one.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 9 — VERIFY RESEARCHER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The researcher should receive a lesson identifier/package and produce a research brief.

Verify that it can actually use the existing research/retrieval architecture.

Research output must preserve provenance.

At minimum determine whether existing repository structures support:

- source ID
- URL/source reference
- transcript timestamp/page/location
- claim
- evidence
- counterevidence
- epistemic status
- typed relation to Ayin

REUSE existing schemas/services.

Do not invent parallel schemas unless absolutely necessary.

Researcher must NOT produce final script prose.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 10 — VERIFY SCRIPT-WRITER ISOLATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This is one of the most important checks.

The writer should receive only the content required to write the current lesson.

Target allowed information:

1. current Lesson Content Package
2. research brief
3. approved owner persona/style constraints

It should NOT receive:

- published script archive
- Channel Ledger prose
- arbitrary previous scripts
- the whole external corpus
- unrestricted unrelated Ayin material

Inspect the ACTUAL tool configuration.

Do not merely trust the words:

"Forbidden inputs."

Ask:

CAN THE AGENT TECHNICALLY READ THEM WITH ITS AVAILABLE TOOLS?

The current writer agent reportedly has tools such as:

`Read`
`Grep`
`Glob`

If those tools give unrestricted repository access, then a Markdown sentence saying:

"do not read published scripts"

is a behavioral rule, NOT actual isolation.

You must clearly report this distinction.

Do NOT claim hard technical sandboxing if only prompt-level separation exists.

If Claude Code supports a clean repository-native way of reducing access without breaking the workflow, use it.

Otherwise document:

`PROMPT-LEVEL INFORMATION BOUNDARY`

rather than falsely calling it enforced isolation.

This distinction is critical.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 11 — VERIFY AYIN-GUARDIAN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The guardian must check the draft against the CURRENT lesson canon.

Verify that it checks at least:

- canonical terminology
- definitions
- conceptual boundaries
- Ayin/external separation
- Ayin/Manasek separation
- Five Gates
- Seven Stages
- Return not becoming a sixth Gate
- metaphor vs factual ontology
- unsupported pseudoscientific claims
- religious/sectarian/authority framing where forbidden by domain rules

It must produce findings.

It must NOT silently rewrite canonical content.

Use severity:

BLOCKING

NON-BLOCKING

or the repository's equivalent.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 12 — VERIFY FACT-CHECKER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Verify the fact checker handles claims individually.

Expected categories should correspond to repository architecture, for example:

- confirmed
- single source
- disputed
- unsupported
- false

Do NOT force these labels if existing schemas already use another vocabulary.

Use the repository vocabulary.

Check:

- quotation verification
- numbers
- dates
- names
- causal claims
- provenance
- independent evidence

A source transcript must not automatically become independent confirmation of its own claim.

The fact checker reports problems.

It must not fabricate substitute evidence.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 13 — VERIFY CONTINUITY EDITOR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Continuity happens AFTER the initial draft.

Confirm actual workflow ordering.

Continuity should inspect available channel history to find things such as:

- previously explained concepts
- repeated examples
- repeated metaphors
- repeated hooks
- earlier lesson references
- outstanding promises
- publication state of referenced lessons

IMPORTANT:

The continuity editor should give constraints to the writer.

Example:

"Concept X was already explained extensively; only briefly re-anchor it."

It should NOT hand old script prose to the writer.

Find the actual Channel Ledger/archive implementation.

If one does not exist, report that honestly.

Do not fabricate it.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 14 — VERIFY OWNER APPROVAL GATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This is NON-NEGOTIABLE.

Inspect:

`.claude/commands/produce-lesson.md`

There must be an explicit stop after review/revision:

DRAFT
→ REVIEWS
→ REVISIONS
→ STOP
→ OWNER APPROVAL

Only AFTER explicit owner approval may the packaging stage run.

No agent may interpret:

- tests passing
- reviewers approving
- no blocking findings

as owner approval.

Owner approval must be a separate human event.

Fix wording if any ambiguity exists.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 15 — VERIFY PACKAGER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Packager may transform the approved script into things such as:

- title candidates
- description
- chapters
- source notes
- thumbnail brief
- tags
- summary
- AI disclosure
- voice-ready text if an EXISTING repository tool supports it

It must not:

- add new factual claims
- rewrite philosophical meaning
- publish
- upload to YouTube
- call external publishing automatically
- approve its own input

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 16 — VERIFY REVISION LOOP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Check orchestration carefully.

Desired behavior:

FIRST DRAFT

↓

AYIN-GUARDIAN
FACT-CHECKER
CONTINUITY-EDITOR

↓

COLLECT FINDINGS

↓

IF NO BLOCKERS:
STOP FOR OWNER

IF BLOCKERS:
SEND ONLY FINDINGS/CONSTRAINTS NEEDED FOR REVISION TO WRITER

↓

NEW DRAFT

↓

RE-RUN RELEVANT REVIEWERS

↓

MAXIMUM 3 REVISION ROUNDS

↓

STOP FOR OWNER / ESCALATE

Critical information-boundary rule:

Do NOT send archived script prose to the writer as part of continuity revision.

Send the finding, not source prose.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 17 — CHECK CLAUDE CONFIGURATION VALIDITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Verify actual syntax and capabilities of:

`.claude/settings.json`

`.claude/agents/*.md`

`.claude/commands/*.md`

`CLAUDE.md`

Check:

- YAML/frontmatter syntax
- tool names
- model names
- command syntax
- `$ARGUMENTS`
- `@AGENTS.md`
- deny/allow rules

Do not guess.

If current Claude Code documentation is needed and network access is available, verify against current official documentation.

Prefer official Anthropic/Claude Code documentation.

Do not modify syntax based on memory alone.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 18 — SECURITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Verify:

- agents are told not to expose secrets
- `.env` is protected where technically possible
- `.env.*` protection works as intended
- git push is prevented
- git commit is prevented
- no publishing action occurs
- no prompt prints credentials

IMPORTANT:

Again distinguish:

PROMPT RULE

from:

TECHNICALLY ENFORCED PERMISSION

Do not claim a restriction is technically enforced unless it really is.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 19 — DETERMINE WHAT ACTUALLY NEEDS FIXING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NOW create the defect list.

Use:

BLOCKER
IMPORTANT
OPTIONAL

Examples:

BLOCKER:
referenced file doesn't exist

BLOCKER:
referenced CLI doesn't exist

BLOCKER:
owner gate missing

BLOCKER:
packager can run automatically

BLOCKER:
writer receives published script prose

IMPORTANT:
ambiguous provenance contract

IMPORTANT:
review output lacks usable severity

OPTIONAL:
wording/style changes

Do not modify OPTIONAL items unless trivial and necessary.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 20 — SHOW YOUR PLAN BEFORE CHANGING FILES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

At this point print a concise checkpoint to me containing:

# Agent-system audit

## Verified working

...

## Defects found

...

## Files I need to change

...

## Files I will NOT touch

...

Then CONTINUE automatically.

Do not wait for my response unless there is a truly destructive ambiguity.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 21 — IMPLEMENT ONLY THE REQUIRED REPAIRS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Make minimal changes.

Likely scope should remain mainly within:

`.claude/`
`CLAUDE.md`
possibly `AGENTS.md`
possibly narrowly targeted tests/docs

Do not expand scope without evidence.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 22 — ADD CONTRACT TESTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Add a small test suite protecting critical static invariants.

Do NOT test exact prose.

Do test architecture.

Examples:

A. all required agent definitions exist

B. `/produce-lesson` exists

C. owner approval gate is present

D. packager occurs after owner approval

E. no automatic publication is configured

F. no automatic git commit/push is configured

G. critical canon paths referenced by agent definitions resolve

H. required agent names referenced by the orchestration command exist

I. writer contract forbids archive/channel-ledger prose as writing input

J. continuity runs after draft creation

Use a suitable location in the existing test structure.

Do not create brittle snapshot tests.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 23 — TEST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Run targeted tests.

Then run repository tests relevant to your modifications.

At minimum:

`.venv/bin/ruff check <touched files>`

`.venv/bin/ruff format --check <touched python files>`

`.venv/bin/mypy ...`

when relevant.

Run the new contract tests.

Then run as much of the existing test suite as reasonably necessary.

Do NOT claim full-suite success if you only ran unit tests.

State exact scope.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 24 — SAFE DRY RUN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Choose one REAL lesson ID from the lesson canon.

Do NOT publish.

Do NOT modify production records.

Trace:

lesson_id
→ producer prerequisite lookup
→ canonical lesson package
→ researcher's available retrieval interface
→ writer input contract
→ guardian input
→ fact-check input
→ continuity input
→ revision contract
→ owner stop
→ packager eligibility after approval

If you cannot actually launch Claude subagents:

DO NOT pretend.

Report:

`STATIC CONTRACT DRY RUN`

If you really run `/produce-lesson` successfully:

report:

`LIVE CLAUDE ORCHESTRATION`

These are different.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 25 — FINAL DIFF REVIEW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Run:

`git diff --check`

`git diff -- .claude CLAUDE.md AGENTS.md tests`

and:

`git status --short`

Make sure unrelated pronunciation work is not accidentally included in your agent-system analysis.

Do NOT commit.

Do NOT push.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 26 — FINAL RESPONSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Report exactly:

# Emtedad Agent-System Audit & Repair

## Verified architecture

## Defects found

| Severity | Defect | Evidence | Fix |

## Changes made

## Agent contracts

| Agent | Input | Output | Boundary |

## Repository paths verified

## CLI commands verified

## Owner approval gate

Explain exactly how it works.

## Information isolation

Separate explicitly:

### Technically enforced

and

### Prompt-level only

This is mandatory.

## Tests executed

Give exact commands and exact counts.

## Dry run

State lesson ID and whether this was:

STATIC CONTRACT

or

LIVE CLAUDE EXECUTION

## Existing unrelated working-tree changes

Explicitly mention the pronunciation lexicon changes already present.

Do not attribute them to this task.

## Remaining issues

## Git status

## Recommended next owner action

Do not commit or push.