# Repository Instructions

## Mission

Build a production-quality, versioned platform for preserving Ayin-e Emtedad,
modeling Manasek, researching external knowledge, and generating
evidence-grounded lectures in Persian, English, and Arabic.

## Read before working

For every task, read:

1. `docs/execution/CURRENT_PHASE.md`
2. the relevant sections of `docs/specification/MASTER_IMPLEMENTATION.md`
3. `docs/architecture/DOMAIN_RULES.md`
4. relevant accepted ADRs in `docs/decisions/`

Read the source PDFs when a task depends on canonical wording, conceptual
meaning, Manasek structure, or import validation.

## Scope control

- Implement only the active phase in `CURRENT_PHASE.md`.
- Do not begin a later phase to make the current phase appear complete.
- Inspect existing code before creating new modules.
- Reuse or refactor equivalent code; do not duplicate it.
- Do not change canonical meaning, terminology, or ritual structure.
- Preserve ambiguity and create a review item when the sources are unclear.
- Never invent certainty, citations, translations, or source evidence.

## Non-negotiable domain boundaries

- Ayin Canon, Ayin Working, Manasek Canon, Manasek Working, external primary
  material, external derived material, and generated content are distinct.
- External knowledge may enter into dialogue with Ayin but cannot redefine it.
- Manasek is an experiential layer, not evidence proving Ayin.
- Generated lectures never become Canon automatically.
- Every lecture requires a pinned canonical Ayin Spine.
- Every language version derives from the same Semantic Master.
- Preserve statement-level citations, uncertainty, epistemic status, and
  counterevidence.
- There are five gates and seven individual stages plus Return.
- Return is not a sixth gate.
- Collective ritual architecture remains separate.
- Ritual safety, consent, optionality, right to stop, and right to leave must be
  machine-enforced.

## Target architecture

- Python 3.11 or newer
- FastAPI
- PostgreSQL 17 with pgvector and PostgreSQL full-text search
- SQLAlchemy 2
- Alembic
- Pydantic schemas at system boundaries
- Docker Compose for local infrastructure
- LangGraph only where stateful orchestration is justified
- Structured logging, explicit exceptions, transactions, and idempotent jobs
- Immutable raw provenance and versioned derived artifacts

Business logic must not live in route handlers. Prefer focused domain,
repository, service, and workflow boundaries without premature microservices.

## Coding style

- Use Python type hints.
- Add concise docstrings and short comments for important or non-obvious logic.
- Keep functions and classes focused.
- Avoid magic strings for critical statuses.
- Avoid hidden LLM side effects.
- Do not swallow exceptions.
- Never add fake tests or weaken tests merely to make them pass.
- Do not commit secrets, generated media, local databases, or `.env` files.

## Database rules

- Use foreign keys, unique constraints, check constraints, and explicit cascade
  behavior.
- Preserve immutable approved versions and historical reproducibility.
- Justify and document GIN, GiST, HNSW, and IVFFlat indexes.
- Avoid unconstrained generic owner IDs.
- Use typed relation tables for important domain relationships.

## Verification

During implementation, run the smallest relevant tests first. Before completing
a phase, run all configured formatting, linting, type checking, migration, and
test commands. Never hide failures.

## Phase completion

Before marking a phase complete:

1. Verify every acceptance criterion with executable evidence.
2. Review the full diff for duplication and architectural drift.
3. Update `docs/execution/MASTER_PLAN.md`.
4. Write the next phase into `docs/execution/CURRENT_PHASE.md`.
5. Report changed files, migrations, commands, test results, unresolved risks,
   review items, and the proposed next phase.

Do not make Git commits unless the user explicitly asks Codex to commit.
