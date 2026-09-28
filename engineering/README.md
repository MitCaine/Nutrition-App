# Engineering workflow

> **Document role: Engineering Process.** This page owns how repository changes move from an idea
> to a reviewed commit and release. Application behavior and architecture remain owned by the
> [Documentation Index](../docs/README.md).

## Change lifecycle

1. **Start with authoritative state.** In an integrated zsh terminal, run
   `source ./scripts/start-work.zsh` from the repository root; it refreshes
   compatible updates and runs the session report. Then use
   [Project Onboarding](../docs/project/onboarding.md) to load only the context needed for the
   change.
2. **Establish task authority.** Follow the
   [current capsule/RI controller sequence](workflow/START_HERE.md) from a clean,
   synchronized trusted `main` checkout. Keep candidate work in a separate branch
   and checkout within the authorized capsule paths.
3. **Implement at the owning boundary.** Follow the
   [Development Guide](../docs/project/development-guide.md) and preserve the applicable
   invariants. Avoid opportunistic cleanup that expands review scope.
4. **Validate in layers.** Run focused checks while working, then the affected baseline and any
   specialized qualification selected by the [Testing Guide](../docs/operations/testing.md).
5. **Close the session.** Run `./scripts/session-end.sh`. A failure blocks completion; report
   opt-in suites as passed, failed, or not run.
6. **Review and integrate.** Present the exact committed candidate, required
   qualification and independent review through the trusted controller. A pull
   request is optional when the controller's guarded integration is used.
7. **Close out and release deliberately.** Complete the separate capsule HISTORY
   closeout before issue closure. Release from a clean, qualified `main` commit.


## Repository-owned task workflow

The [Workflow Foundation](workflow/README.md) defines
repository-owned [task states](workflow/STATES.md), the versioned
[capsule contract](workflow/TASK_CAPSULE.md), [routing](workflow/ROUTING.md),
[evidence](workflow/EVIDENCE.md), and the
[failure taxonomy](workflow/FAILURE_TAXONOMY.md).
Open the [bounded execution guide](workflow/EXECUTION.md),
[attached candidate evidence guide](workflow/CANDIDATE_EVIDENCE.md), and
[Repository Intelligence guide](tooling/RI.md) directly for the current
controller tools and their authority limits.

For new tasks, the capsule/RI path is normal. The full non-terminal execution contract remains
under `engineering/capsules/active/` through `REVIEWED` or the last
non-terminal state. Successful integration or cancellation writes the task's
unique terminal record to `engineering/capsules/HISTORY.md`, including the
historical full-capsule recovery locator and SHA-256, and removes the active
capsule. Do not retain new per-task terminal copies under a `completed/`
directory.

Capsules coordinate bounded execution but do not replace Roadmaps, Grills,
PRDs, Architecture Reviews, Implementation Backlogs, GitHub Issues, current
architecture, invariants, or operations guidance.

The owner's [2026-09-27 decision](https://github.com/MitCaine/Nutrition-App/issues/187#issuecomment-5859326452)
made the combined path normal for new tasks. In-flight unattached tasks and
explicit compatibility exceptions retain their existing controller path; see
the [workflow entrypoint](workflow/START_HERE.md) for current boundaries.

## Git conventions

Use short-lived, kebab-case branches with one of these prefixes:

- `feat/` for product capability;
- `fix/` for a defect;
- `docs/` for documentation-only work;
- `chore/` for repository, dependency, or tooling maintenance; and
- `release/` only when a stabilization branch is necessary.

Prefer commit subjects in this form:

```text
type(scope): imperative summary
```

Common types are `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, and `chore`.
Use a stable scope such as `backend`, `mobile`, `control`, `ops`, `docs`, or `tooling` when it adds
meaning. Keep the subject concise, put motivation and constraints in the body, and call out
breaking changes explicitly. Each commit should be understandable and mechanically valid on its
own.

## Review and merge

Pull requests should be small enough that a reviewer can identify the authority boundary and the
evidence supporting the change. The pull request must state:

- what changed and why;
- which areas are intentionally unchanged;
- focused and baseline validation performed;
- required infrastructure or native qualification status;
- migration, security, privacy, and recovery impact when applicable; and
- follow-up work that is deliberately outside scope.

Prefer squash merge for an ordinary pull request and use a convention-compliant pull request title
as the resulting commit subject. Preserve multiple commits only when their separation carries
lasting review or operational value. Do not merge with unresolved review conversations, failing
required checks, or an unexplained session-end warning.

## Release conventions

- Release from a clean commit on `main`; do not tag an uncommitted working tree.
- Use Semantic Versioning tags in the form `vMAJOR.MINOR.PATCH`, created as annotated tags.
- Treat release qualification as release-specific. Follow the current operations and release
  documents rather than assuming the Version 1.0 evidence gate applies unchanged to Version 1.1.
- Publish concise GitHub release notes that identify user-visible changes, migrations, known
  limitations, and the exact qualified commit.
- Update [Current State](../docs/project/current-state.md) when the active release line, migration
  heads, roadmap status, or supported deployment boundary changes.

## Repository automation

[GitHub Actions](../.github/workflows/ci.yml) owns the required portable baseline. The repository
session contract supplies deterministic local and CI-closeout checks; specialized PostgreSQL,
MinIO, Docker/provider, performance, and Apple-native qualification remains explicitly selected by
change risk.

Dependabot proposes grouped dependency updates without merging them automatically. Treat those
pull requests like any other change: review release notes, regenerate lock material through the
documented workflow when necessary, and run affected validation.

Use the [Script Index](../scripts/README.md) to choose an entry point. Stable operational scripts
must not be renamed or repurposed casually; add a new narrowly named entry point when a genuinely
different responsibility appears.
