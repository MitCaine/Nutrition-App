# Script index

> **Document role: Engineering Process.** This page is the discovery map for repository-level
> scripts. Exact operational authority remains in the linked guides and runbooks.

Run the commands below from the repository root. Each script resolves repository paths internally
and does not depend on the caller's shell configuration.

## Repository lifecycle and validation

| Entry point | Responsibility |
| --- | --- |
| `./scripts/session-start.sh` | Reports repository toolchain state plus authoritative Git, migration-head, phase-document, mobile-change, and opt-in-suite state before work starts. |
| `./scripts/session-end.sh` | Runs the required repository closeout checks and reports opt-in suites that were not run. |
| `./scripts/project-audit.sh` | Exposes the lower-level session, boundary, deterministic inventory, privilege-manifest, and pre-commit commands. |
| `python3 scripts/toolchain-report.py` | Reports the active Python and Node versions against `.python-version` and `.nvmrc`; use `--check node`, `--check python`, or `--check all` when a matching toolchain is required. |
| `python3 scripts/validate-docs.py` | Validates repository Markdown links, anchors, navigation reachability, executable references, and required current-state contracts. |
| `python3 scripts/validate-task-capsules.py --all` | Validates task-capsule schema, authority paths, state transitions, scope metadata, completion records, and execution prerequisites. |
| `python3 scripts/render-task-handoff.py engineering/capsules/active/TASK-ID.md` | Runs strict READY preflight and writes a deterministic executor handoff bundle outside the repository. |

The [Repository Session Contract](../docs/operations/session-contract.md) defines the meaning and
required use of these commands. Use the higher-level session scripts unless a guide explicitly
requires a lower-level audit subcommand.

## Local runtime

| Entry point | Responsibility |
| --- | --- |
| `./scripts/start-backend.sh` | Starts PostgreSQL and FastAPI only after verifying an existing runtime configuration and the exact `nutrition_runtime` database identity. It never runs migrations. |
| `./scripts/start-project.sh` | Starts the qualified backend path plus an iOS development build in a named simulator on macOS/Xcode. |
| `./scripts/stop-project.sh` | Stops processes recorded by `start-project.sh`, shuts down a simulator started by that script, and removes its local runtime state. |

Process records written by `start-project.sh` are versioned ownership records rather than bare PID files. Each record captures the launched PID, normalized process start identity, service command contract, and observed command. `stop-project.sh` revalidates start identity and command contract before TERM and again before any forced KILL; malformed, legacy, exited, or mismatched records never authorize a signal. Descendant shutdown likewise captures child start identity before signaling. The local project launcher is a macOS/Xcode workflow; its process identity contract uses the `ps` `lstart`, `ppid`, `stat`, and `command` fields, which are covered by disposable-process regression tests.

These scripts are not substitutes for initial environment setup or migration procedures. Ordinary
development setup is documented in the
[Development Guide](../docs/project/development-guide.md#configuration-and-startup). Target
activation and other high-risk migration work must use the applicable operations runbook.

## Review workflow

| Entry point | Responsibility |
| --- | --- |
| `Run Nutrition Review.command` | macOS Finder entry point. Runs the standard review workflow, creates the uploadable review bundle, reveals the finished ZIP in Finder, and leaves the Terminal window open until dismissed. |
| `./scripts/run-review.sh` | Authoritative review orchestrator. Runs the standard verification profile, captures complete and failure-only logs, validates repository state, creates the project snapshot, and assembles the final review bundle. |
| `./scripts/zip-project.sh` | Lower-level project packager used by `run-review.sh`. Creates a validated, secret-excluding repository snapshot and review manifest. Normally invoked indirectly through the review workflow rather than by hand. |

The review workflow records repository state before and after verification, detects repository
drift, packages only the verified source tree, and produces both human-readable and machine-readable
evidence suitable for implementation review.

## Baselines and specialist qualification

| Entry point | Responsibility |
| --- | --- |
| `./scripts/run-backend-baseline.sh` | Runs the canonical ordinary backend pytest selection while excluding explicitly opt-in PostgreSQL/concurrency, Phase 5C performance, MinIO, and Docker qualification markers. |
| `./scripts/run-e4-16-qualification.sh` | Retained Epic 4 release-parity qualifier covering the bounded E4-16 backend/mobile evidence contract. It is specialist regression tooling, not the ordinary development baseline. |
| `./scripts/run-issue17-phase5c-clone.sh` | Retained historical PostgreSQL clone/conversion qualification entry point used when the Phase 5C compatibility boundary itself must be exercised. |
| `./scripts/qualify-phase5c4-infrastructure.sh` | Runs destructive, disposable Phase 5C4 infrastructure qualification after an exact confirmation value is supplied. |

The specialist qualifiers remain deliberately separate from the ordinary baseline. Follow the
[Testing Guide](../docs/operations/testing.md) for their prerequisites and exact selection
contracts. The Phase 5C4 infrastructure qualifier is destructive and fail-closed.

## Retained backend operator tools

Backend operator implementations live under `apps/backend/scripts/` and normally run from
`apps/backend` with `.venv/bin/python`. They are not automatically obsolete when their originating
Epic or production-hardening stage is complete; several remain compatibility, transfer, or
operations authorities.

| Tool | Retained responsibility |
| --- | --- |
| `apps/backend/scripts/export_personal_transfer.py` | One-time E2-15 PostgreSQL-to-SQLite personal-transfer export retained for the compatibility boundary described in the [Repository Tour](../docs/project/repository-tour.md). |
| `apps/backend/scripts/manage_phase5c4_authorization.py` | Manages the schema-0020 Target Activation Authorization retained and consumed by the current [target-activation sequence](../docs/operations/runbooks/target-activation.md). |
| `apps/backend/scripts/qualify_immutable_provenance.py` | Independently qualifies the retained schema-0020 immutable-provenance boundary described by the [immutable-provenance runbook](../docs/operations/runbooks/immutable-provenance.md). |

These tools intentionally remain separate. In particular, purpose-specific authorization CLIs are
not combined merely because they share signing-envelope or control-database plumbing; their
authority, accepted inputs, side effects, and failure contracts remain distinct.

`scripts/project-audit.py` is likewise intentionally treated as the implementation behind the
stable `./scripts/project-audit.sh` entry point rather than as a second public repository command.

## GitHub planning automation

| Entry point | Responsibility |
| --- | --- |
| `python3 scripts/github/create_issues.py BACKLOG.md` | Reconciles labels, milestones, a GitHub Epic, child issues, generated progress metadata, and optional Project membership from a structured backlog. |

See the [GitHub backlog issue creator guide](github/README.md) for the required Markdown format,
authentication, dry-run behavior, state-file handling, and rerun guarantees.

## Placement rules

- Keep cross-repository lifecycle, validation, packaging, and orchestration entry points here.
- Keep backend domain and operator implementations under `apps/backend/scripts/` and expose them
  at the root only when a stable repository-wide entry point is justified.
- Prefer a thin shell wrapper around one authoritative implementation over duplicated logic.
- Preserve stable operational names. A compatibility period is required if an entry point must
  ever be replaced.
- Commands that can destroy or overwrite data must identify exact scope and require an explicit,
  narrow confirmation.
