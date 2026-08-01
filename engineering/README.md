# Engineering workflow

> **Document role: Engineering Process.** This page owns how repository changes move from an idea
> to a reviewed commit and release. Application behavior and architecture remain owned by the
> [Documentation Index](../docs/README.md).

## Change lifecycle

1. **Start with authoritative state.** Run `./scripts/session-start.sh`, then use
   [Project Onboarding](../docs/project/onboarding.md) to load only the context needed for the
   change.
2. **Create a focused branch.** Branch from current `main`, use the naming convention below, and
   keep unrelated work out of the branch.
3. **Implement at the owning boundary.** Follow the
   [Development Guide](../docs/project/development-guide.md) and preserve the applicable
   invariants. Avoid opportunistic cleanup that expands review scope.
4. **Validate in layers.** Run focused checks while working, then the affected baseline and any
   specialized qualification selected by the [Testing Guide](../docs/operations/testing.md).
5. **Close the session.** Run `./scripts/session-end.sh`. A failure blocks completion; report
   opt-in suites as passed, failed, or not run.
6. **Open a reviewable pull request.** Explain the problem, bounded solution, risks, validation,
   and any intentionally deferred work. Use the repository pull request template.
7. **Merge and release deliberately.** Merge only reviewed, green work. Release from a clean,
   qualified `main` commit using the conventions below.

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

