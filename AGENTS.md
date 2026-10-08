# AGENTS.md

## Purpose

This file is the repository-level operating contract for coding agents working in Nutrition App.

Use it as the entry point. Deeper operational authority remains in the linked repository guides, scripts, migrations, tests, task capsules, and phase documents. Do not duplicate or override those authorities here.

## Start and end every repository session

Run all commands from the repository root.

For source or documentation maintenance that leaves dependency inputs unchanged,
run the standalone session report from the repository root:

```bash
./scripts/session-start.sh
```

For a task authorized to change dependencies, source `./scripts/start-work.zsh` in
the integrated zsh terminal and follow the [dependency update guide](docs/project/development-guide.md#configuration-and-startup).
It refreshes compatible dependencies and then runs the session report; independent
updates continue after failures. A failed update is not passing qualification. Review
and preserve its exact partial output for the task workflow.

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

Use the canonical ordinary backend runner from the repository root:

```bash
./scripts/run-backend-baseline.sh
```

The [testing guide](docs/operations/testing.md#baseline-validation) owns its interpreter,
environment/configuration controls, marker exclusions and focused-test guidance. A focused
pytest selection diagnoses a specific change; it does not replace the canonical baseline.

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

## Task workflow

Start at [the local execution map](docs/local_project_map.md). The controller reads its complete
byte-pinned [daily issue procedure](engineering/workflow/shared/start-an-issue.md). Each worker
reads `Shared worker rules` and its assigned unique level-two section of the pinned
[worker instructions](engineering/workflow/shared/worker-instructions.md#role-index), through the next
level-two heading or end of file; links are navigation, not bounded reads. Builders receive
original objective/base/specifications without a future capsule; implementors and reviewers
receive the accepted capsule.
The [adoption guide](engineering/workflow/shared/capsule-controller-workflow.md) is conditional
on setup or replacement. New tasks use bounded Markdown records and the current standard
controller. The Work controller directly dispatches the capsule builder and distinct independent
reviewer. For implementation, the owner-designated Codex dispatcher authenticates the complete
accepted-capsule handoff and launches one implementor; the implementor returns there for relay to
Work. Workers do not recruit. Use blocking completion while an assignment is active unless its
exact idle-wake route is verified; consume a terminal result already delivered without requiring
idle-wake proof. The sequence is orient → capsule → implement → independent review → authorized
integration → verify closeout. RI pins record instruction/runtime provenance and do not create
permission. The trusted task controller owns authenticated external authorization, required
qualification and protected integration.
No RI SDK transport, mandatory declaration report, frozen launcher or timed model gateway applies.

Preserve existing active capsule contracts, state/history, branches, evidence, pending decisions,
C/R/T recovery and consumed allowances. The original #246 and #256 capsule attempts remain stopped
under their original authority; this does not set their current issue status. The local map
separates these attempts from completed fresh #246 work and points to live issue status. Preserve
historical readers as recovery tools; they are not current dispatch entrypoints.

For bounded work, use the task's focused tooling/document checks and independent review, and meet
its selected profile floors. Do not run the retired adoption lifecycle or unrelated broad/native
suites merely because historical RI instructions required them. Secret/permission controls and
protected Git acceptance still apply. Source/document maintenance with unchanged dependency inputs
uses the standalone session report above; dependency work follows the authorized update route in
the development guide.

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
