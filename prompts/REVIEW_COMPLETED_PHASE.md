# Review a Completed Phase

```text
Review the most recently completed implementation phase without adding new
features.

Read AGENTS.md, MASTER_PLAN.md, the completed phase criteria from Git history or
the phase audit, relevant master-specification sections, ADRs, code, migrations,
and tests.

Check:
- every acceptance criterion against executable evidence;
- domain-boundary violations;
- Ayin or Manasek conceptual drift;
- provenance, versioning, and idempotency gaps;
- missing relational constraints and unsafe cascade behavior;
- duplicated modules or business logic in route handlers;
- hidden LLM calls or non-reproducible side effects;
- test realism and missing failure-path coverage;
- security, privacy, secrets, licensing, and operational risks;
- documentation and migration rollback quality.

Run relevant checks. Fix only defects within the completed phase. Do not start
the next phase. Report findings by severity, applied fixes, commands, results,
and any blocker that requires human review.
```
