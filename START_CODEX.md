# First Codex Task

Paste the prompt below into the Codex sidebar while the repository root is open
in VS Code.

```text
Execute Phase 0 as defined in docs/execution/CURRENT_PHASE.md.

First read AGENTS.md, the current phase, the master implementation
specification, architecture documents, accepted ADRs, and repository contents.

This repository may contain only the bootstrap package. Audit what actually
exists; do not pretend that application code already exists.

For Phase 0:

1. Inventory all files, source materials, tooling, code, tests, and data.
2. Verify the master specification against the execution plan and identify any
   unmapped or contradictory requirements.
3. Produce docs/audits/PHASE_0_REPOSITORY_AUDIT.md.
4. Refine docs/architecture/SYSTEM_ARCHITECTURE.md and DATA_MODEL.md only where
   the specification provides sufficient evidence.
5. Produce a concrete Phase 1 plan in docs/execution/CURRENT_PHASE.md, including
   deliverables, file boundaries, dependencies, risks, acceptance criteria, and
   commands that will verify completion.
6. Update docs/execution/MASTER_PLAN.md with verified Phase 0 evidence.

Do not implement Phase 1 application code during this task.
Do not redesign Ayin or Manasek.
Do not invent missing product decisions. Record them in the review queue.

Before finishing, review your changes for completeness and report changed
files, checks performed, findings, unresolved decisions, and the exact next
task.
```
