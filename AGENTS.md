# AGENTS.md

## Purpose

This file is the repository-level operating contract for coding agents working in Nutrition App.

Use it as the entry point. Deeper operational authority remains in the linked repository guides, scripts, migrations, tests, task capsules, and phase documents. Do not duplicate or override those authorities here.

## Start and end every repository session

Run all commands from the repository root.

At the start of work:

```bash
./scripts/session-start.sh
```

Before presenting work as complete or asking for commit approval:

```bash
./scripts/session-end.sh
git diff --check
git status --short
```

Treat failures from these scripts as blocking unless the task explicitly concerns repairing the failing check.

## Repository authority

When instructions conflict, use this order:

1. Current migrations, database constraints, and executable tests
2. Current repository scripts and validation tooling
3. Active task capsule and current phase document
4. Current engineering guides and runbooks
5. Historical phase documents and archived material
6. This file
7. Agent assumptions

Do not infer authority from file modification time alone. Prefer current executable contracts over prose.

## Working rules

- Make bounded changes. Do not rewrite subsystems unless the active task explicitly requires it.
- Preserve established architecture and public contracts unless a demonstrated correctness defect requires change.
- Inspect actual code, migrations, tests, and repository state before proposing implementation.
- Do not silently weaken validation, remove checks, suppress warnings, or broaden exception handling to make tests pass.
- Do not add speculative abstractions, compatibility layers, or generalized infrastructure without a current requirement.
- Keep shared contracts, migrations, transaction semantics, lock ordering, and final integration with the parent agent rather than delegating them independently.
- Do not commit, push, merge, or modify repository settings unless explicitly requested.
- Never treat generated artifacts, logs, temporary files, local environments, or parked work as source authority.

## Core domain invariants

Preserve these unless the task explicitly changes the product contract and the resulting migration, API, and test consequences are reviewed:

- Daily Log nutrition history is immutable.
- Recipe publication revisions are immutable.
- Logging against Recipes resolves through immutable published revisions.
- Generated Recipe `FoodItem` rows are compatibility projections, not the historical authority.
- Historical nutrition must not change when mutable Foods, servings, Recipes, or projections change.
- OCR corrections retain immutable provenance.
- Ownership is enforced at the selected authority boundary; the remote runtime enforces ownership server-side and the local runtime preserves the repository's owner-scoping contracts in SQLite.
- Mutation idempotency and replay behavior must be deterministic.
- Concurrency correctness takes priority over optimistic behavior.
- Failure paths must preserve atomicity and rollback completeness.
- Dependency instability, retries, and conflict behavior must remain bounded and explicit.

## Database and concurrency rules

- Concurrency evidence follows the selected runtime authority. Native, file-backed SQLite is authoritative for local-runtime persistence and transaction behavior; PostgreSQL 16 is authoritative for preserved remote SQL locking and multi-session concurrency contracts.
- SQLite evidence does not substitute for PostgreSQL qualification when a change touches the preserved remote authority, and PostgreSQL evidence does not substitute for native/file-backed SQLite qualification when a change touches the local authority.
- Respect established lock ordering. Inspect existing repository and service methods before adding a new `FOR UPDATE`, shared lock, advisory lock, or retry loop.
- Keep lock scope as narrow as correctness permits.
- Different logical records should not block each other merely because they share immutable read authority.
- Same-record mutations must serialize and re-read the latest committed state.
- Publication, source mutation, activation, cutback, recovery, and related control-plane operations must preserve their documented mutual exclusion and authority chain.
- Database routines that mutate rows outside the ORM unit of work must reconcile loaded ORM state explicitly.
- Do not suppress SQLAlchemy row-count warnings when they reveal stale or duplicate ORM work.
- New migrations must preserve a single authoritative head for their migration domain and must pass repository migration-head validation.
- Do not edit applied migration history to change behavior; add a new migration unless the repository's migration policy explicitly says otherwise.

## Backend expectations

The backend is Python, FastAPI, SQLAlchemy, Alembic, and PostgreSQL.

Before changing backend behavior:

- Locate the service, repository, model, migration, API, and test contracts involved.
- Identify transaction ownership and commit/rollback responsibility.
- Identify every mutable row and authority row touched.
- Check ownership enforcement and cross-user behavior.
- Check idempotency and replay behavior.
- Check whether historical snapshots or immutable provenance are involved.
- Add or update focused regression tests for the defect or contract being changed.

Use the repository's locked dependency process. Do not convert lower-bound declarations into a substitute for updating and validating the actual resolved environment.

## Mobile expectations

The mobile app is React Native, Expo, and TypeScript.

- Preserve the selected runtime authority. Do not move ownership, historical-integrity, or concurrency guarantees into UI-only logic or create synchronization, dual-write, or hidden fallback between local and remote authorities.
- Keep platform behavior explicit when iOS and Android differ.
- Preserve accessibility contracts for VoiceOver and TalkBack.
- Treat Expo, React Native, TypeScript, Jest, Zod, storage, and native-module major upgrades as coordinated migration work, not routine grouped dependency bumps.
- Run type checking and tests after mobile changes.
- Native build or device validation is required when a change affects native modules, permissions, camera, OCR, storage, date/time behavior, or generated platform projects.

## Testing and validation

Run the smallest focused test first, then the broader authoritative suite.

Typical backend baseline:

```bash
cd apps/backend
ruff check .
python -m pytest -q --strict-markers \
  -m "not postgres_concurrency and \
      not phase5c_performance_t0 and \
      not phase5c4_control_postgres and \
      not phase5c4_minio and \
      not phase5c4_docker_integration"
```

PostgreSQL runtime contract selection:

```bash
cd apps/backend
REQUIRE_POSTGRES_TESTS=1 \
NUTRITION_TEST_POSTGRES_URL='postgresql+psycopg://nutrition_app:nutrition_app@localhost:5432/nutrition_app' \
python -m pytest -q --strict-markers \
  tests/test_postgres_test_support.py \
  tests/test_log_concurrency_postgres.py \
  tests/test_graph_restart_idempotency_postgres.py
```

Use repository scripts for other opt-in suites. Do not claim an opt-in suite was run when it was not.

For dependency-only pull requests:

- Review the exact changed files and versions.
- Distinguish lockfile-only security patches from platform migrations.
- Require green CI.
- Merge narrow security patches one at a time.
- Do not merge grouped major upgrades merely because Dependabot opened them.

## Task capsules and workflow

A task that already has an active capsule must follow the repository's
task-capsule process.

- Read the active capsule before implementation.
- Preserve its state, boundaries, acceptance criteria, and artifact requirements.
- Do not invent missing implementation-result artifacts or scripts.
- When a capsule is blocked, revised, or returned to an earlier state, do not
  silently resume or broaden it.
- Update capsule state only through the repository's documented workflow.
- Keep the full capsule under `engineering/capsules/active/` through
  `REVIEWED` or the last non-terminal state.
- Record `MERGED`, `CANCELLED`, and `RETROSPECTED` outcomes in
  `engineering/capsules/HISTORY.md`; terminal closeout removes the active
  capsule rather than retaining a per-task completed copy.
- Do not infer that every repository change must create a capsule while
  Workflow v3 remains experimental; capsule adoption follows the current
  workflow policy and explicit task setup.
## Documentation

- Update documentation when behavior, authority, commands, migration heads, or operational procedures change.
- Do not copy operational authority into multiple files when a link is sufficient.
- Historical documents are evidence, not current instruction.
- Referenced scripts and paths must exist.
- Keep deterministic inventories and generated evidence current through repository-owned tooling.

## Security

- Never commit credentials, tokens, private keys, production connection strings, or real user data.
- Treat secret scanning and push protection failures as blocking.
- Preserve server-side ownership checks and least-privilege role boundaries.
- Security-related dependency updates still require review and green CI.
- Do not enable automatic merging for dependency or security pull requests.

## Completion report

When finishing implementation or review, report:

1. What changed
2. Why it was necessary
3. Architectural or data-integrity implications
4. Tests and validation actually run, with results
5. Opt-in suites not run
6. Remaining warnings or risks
7. Whether the work is ready for the next lifecycle gate, needs bounded
   correction, or should stop

Do not describe work as terminally complete while an active capsule still
requires verification, review, integration, or history closeout. Do not claim
completion when the working tree contains unexplained changes or repository
closeout fails.
