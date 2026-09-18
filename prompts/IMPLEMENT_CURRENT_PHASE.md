# Implement the Current Phase

Use this prompt after Phase 0 has prepared the active phase document.

```text
Implement only the phase defined in docs/execution/CURRENT_PHASE.md.

Read AGENTS.md first. Then read the current phase, the relevant sections of the
master specification, applicable architecture documents, accepted ADRs, and
the affected existing code and tests.

Before editing, confirm:
- current scope and explicit exclusions;
- affected modules and data boundaries;
- acceptance criteria;
- verification commands;
- unresolved decisions that would make implementation unsafe.

During implementation:
- reuse existing code where appropriate;
- keep business logic out of API routes;
- add database constraints and migrations deliberately;
- add focused tests with behavior changes;
- preserve provenance, versioning, idempotency, and domain boundaries;
- do not modify unrelated files or begin later phases.

Before finishing:
1. Run formatting, linting, type checks, migration checks, focused tests, and
   the full available test suite.
2. Fix failures caused by this phase.
3. Review the complete diff for duplication, hidden side effects, and
   architectural or domain drift.
4. Verify each acceptance criterion with evidence.
5. Update MASTER_PLAN.md.
6. Prepare CURRENT_PHASE.md for the next phase, but do not implement it.
7. Report changed files, migrations, commands, test results, review items,
   remaining risks, and the proposed next task.
```
