# Engineering workflow

> **Document role: Engineering Process.** This page owns how repository changes move from an idea
> to a reviewed commit and release. Application behavior and architecture remain owned by the
> [Documentation Index](../docs/README.md).

## Change lifecycle

1. **Start with authoritative state.** For source or documentation work whose dependency
   inputs stay unchanged, run `./scripts/session-start.sh` from the repository root. For an
   authorized dependency task, use `source ./scripts/start-work.zsh` and the
   [Development Guide](../docs/project/development-guide.md#configuration-and-startup). Then use
   [Project Onboarding](../docs/project/onboarding.md) to load only the context needed for the
   change.
2. **Establish task authority.** Follow the
   [current lightweight controller sequence](../docs/local_project_map.md) from a clean,
   synchronized trusted `main` checkout. Keep candidate work in a separate branch
   and checkout within the authorized task paths.
3. **Implement at the owning boundary.** Follow the
   [Development Guide](../docs/project/development-guide.md) and preserve the applicable
   invariants. Avoid opportunistic cleanup that expands review scope.
4. **Validate in layers.** Run focused checks while working, then the affected baseline and any
   specialized qualification selected by the [Testing Guide](../docs/operations/testing.md).
5. **Close the session.** Run `./scripts/session-end.sh`. A failure blocks completion; report
   opt-in suites as passed, failed, or not run.
6. **Review and integrate.** Present the exact committed candidate, required
   qualification and independent review through the trusted controller. For fresh lightweight
   `standard` tasks, obtain ordinary CI through a pull request from the published task branch to
   `main`, as required by the [Testing Guide](../docs/operations/testing.md#main-qualification-profiles).
   This ordinary-CI requirement is separate from the controller-owned guarded integration.
7. **Close out and release deliberately.** Freeze the tracked preparation/check ledger before
   candidate C is frozen for exact-candidate qualification and review. Label it historical and
   point current status to the live issue and existing external controller checkpoint. After C is
   frozen, record every later attempt, failure, rerun, qualification, review, integration, issue
   closure and cleanup in those existing operational records. Do not create another candidate
   solely to append completion evidence. A genuine later
   tracked-document correction requires affected checks, review and authorized publication.
   Existing capsule lifecycles additionally require their separate guarded capsule HISTORY closeout;
   do not create a capsule for an ordinary task. Release from a clean, qualified `main` commit.


## Repository-owned task workflow

Use [local project map](../docs/local_project_map.md), the sole current local map, and its complete
pinned [daily issue procedure](workflow/shared/start-an-issue.md) for controller intake. Workers read
Shared worker rules and their assigned unique level-two section of the pinned
[worker instructions](workflow/shared/worker-instructions.md#role-index) through the next level-two
heading or end of file. Initial builders receive original objective/base and requirements without
a future capsule; implementors and reviewers receive the accepted capsule.
The [adoption guide](workflow/shared/capsule-controller-workflow.md) is conditional. New work
uses bounded Markdown tasks under `engineering/tasks/`, ordinary source/diff/log review and the
trusted standard controller. The Work controller dispatches the builder and distinct independent
reviewer; the owner-designated Codex dispatcher authenticates the accepted implementation handoff,
launches one implementor and relays its terminal result to Work. RI-only SDK/report/structural
gates are retired. Protected main, authenticated owner authority, required profile checks,
domain/security contracts and independent review remain.

[AUTHORITY](workflow/AUTHORITY.md) owns project acceptance; [RI tooling](tooling/RI.md)
retains the compatible source-navigation runtime. The original #246/#256 capsule attempts remain
stopped under their original authority; the map distinguishes their attempt history from the
completed fresh #246 attempt and current live issue status. Historical capsule state/history and
C/R/T recovery remain in [capsules](capsules/README.md), without becoming prerequisites for new
tasks.

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
