# Script index

> **Document role: Engineering Process.** This page is the discovery map for repository-level
> scripts. Exact operational authority remains in the linked guides and runbooks.

Run the commands below from the repository root. Each script resolves repository paths internally
and does not depend on the caller's shell configuration.

## Repository lifecycle and validation

| Entry point | Responsibility |
| --- | --- |
| `./scripts/session-start.sh` | Reports authoritative Git, migration-head, phase-document, mobile-change, and opt-in-suite state before work starts. |
| `./scripts/session-end.sh` | Runs the required repository closeout checks and reports opt-in suites that were not run. |
| `./scripts/project-audit.sh` | Exposes the lower-level session, boundary, deterministic inventory, privilege-manifest, and pre-commit commands. |
| `python3 scripts/validate-docs.py` | Validates repository Markdown links, anchors, navigation reachability, executable references, and required current-state contracts. |

The [Repository Session Contract](../docs/operations/session-contract.md) defines the meaning and
required use of these commands. Use the higher-level session scripts unless a guide explicitly
requires a lower-level audit subcommand.

## Local runtime

| Entry point | Responsibility |
| --- | --- |
| `./scripts/start-backend.sh` | Starts PostgreSQL and FastAPI only after verifying an existing runtime configuration and the exact `nutrition_runtime` database identity. It never runs migrations. |
| `./scripts/start-project.sh` | Starts the qualified backend path plus an iOS development build in a named simulator on macOS/Xcode. |
| `./scripts/stop-project.sh` | Stops processes recorded by `start-project.sh`, shuts down a simulator started by that script, and removes its local runtime state. |

These scripts are not substitutes for initial environment setup or migration procedures. Ordinary
development setup is documented in the
[Development Guide](../docs/project/development-guide.md#configuration-and-startup). Target
activation and other high-risk migration work must use the applicable operations runbook.

## Qualification and review packaging

| Entry point | Responsibility |
| --- | --- |
| `./scripts/qualify-phase5c4-infrastructure.sh` | Runs destructive, disposable Phase 5C4 infrastructure qualification after an exact confirmation value is supplied. |
| `./scripts/zip-project.sh` | Builds and verifies a secret-excluding review archive with a repository manifest. |

The infrastructure qualifier is intentionally specialized and fail-closed. Follow the
[Testing Guide](../docs/operations/testing.md#phase-5c48-bounded-recovery-qualification) rather than
discovering its environment contract by trial and error.

## Placement rules

- Keep cross-repository lifecycle, validation, packaging, and orchestration entry points here.
- Keep backend domain and operator implementations under `apps/backend/scripts/` and expose them
  at the root only when a stable repository-wide entry point is justified.
- Prefer a thin shell wrapper around one authoritative implementation over duplicated logic.
- Preserve stable operational names. A compatibility period is required if an entry point must
  ever be replaced.
- Commands that can destroy or overwrite data must identify exact scope and require an explicit,
  narrow confirmation.
