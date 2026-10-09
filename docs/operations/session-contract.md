# Repository session and audit contract

> **Document role: Operational Reference.**

The repository provides deterministic mechanical checks for work that should not require repeated
agent interpretation. These tools do not replace architectural review. They establish repository
state, identify mechanical boundary violations, inventory the Phase 5C4 control plane, and compare
PostgreSQL privilege manifests.

For Markdown task intake, the controller authenticates the current remote main and live issue,
reads the selected normal capsule or maintenance handoff, and reconciles them with authenticated
external controller state through the [workflow entrypoint](../local_project_map.md). Before dispatch,
the controller runs `./scripts/task validate-record --task-record PATH` for normal or
`./scripts/task validate-record --task-record PATH --route maintenance` for a brief handoff.
This read-only command validates record structure and
recorded fields, not owner authorization or semantic eligibility. Read historical TOML capsules and
HISTORY only when the current attempt or a directed recovery dependency uses them.
Repository history-integrity validation remains required. The
[combined pilot record](../../engineering/workflow/PILOT_2026-09-26.md) describes
observed recovery cases; its old SHAs are evidence, not reusable authority.

## Repository session contract

For source or documentation maintenance that leaves dependency inputs unchanged,
run the standalone read-only session report from the checkout root:

```bash
./scripts/session-start.sh
```

Dependency startup follows the [scope rule below](#startup-update-scope), not a
blanket whole-project refresh. Successful updates still require task qualification.

Before claiming completion, run:

```bash
./scripts/session-end.sh
```

A nonzero session-end exit is blocking: the implementation must not be
described as complete. `WARN` findings are non-blocking unless configuration explicitly elevates
them; `ERROR` findings are blocking. Reports must include the final session-end result and accurately
identify opt-in infrastructure suites as passed, failed, or not run.

Agents must not bypass a failure by weakening a validator, adding a broad exclusion, or deleting an
incomplete test. Future prompts may invoke these requirements with: **“Follow the repository session
contract.”**

## Startup update scope

This is the canonical local startup scope rule. Ordinary source/document work uses
`./scripts/session-start.sh`; sourcing `./scripts/start-work.zsh` without arguments
also runs only that report, entering neither update module. No installation or
lock update is authorized by starting a session.

For an identified package, use the existing targeted route from the repository root:

```bash
./scripts/update-dependencies backend fastapi
./scripts/update-dependencies backend fastapi --apply
# Or: ./scripts/update-dependencies mobile @tanstack/react-query [--apply]
```

Choose only the authorized ecosystem/packages. The inspected backend resolver uses
`piptools compile --upgrade-package PACKAGE` against the existing lock; mobile
uses `npm update PACKAGE --package-lock-only --ignore-scripts` and validates the
candidate install/Expo/risk contracts. These routes resolve a full ecosystem lock,
not isolated bytes: necessary transitive changes can occur. Inspect every proposed
change before apply; unrelated direct refresh or wider impact requires a controller
scope decision. No backend/mobile/RI `all` refresh or Homebrew install/upgrade is
part of the selected package route. The updater may select an installed Node via
read-only Homebrew prefix queries. It may bootstrap pip-tools in scratch if absent;
when tools installation is outside authority, verify a compatible prepared compiler
first or hold that route. Preview does not imply no scratch/network activity.

Only expressly authorized whole-project toolchain/dependency refresh uses:

```zsh
source ./scripts/start-work.zsh --refresh-all
```

This preserves the toolchain module followed by `all --apply`, independent update
attempts and final session report even after failures. Retain exact partial output,
lock outputs and nonzero statuses; do not treat partial success as acceptance.
The invocation is a scope selection, not proof of owner permission.

`NUTRITION_START_WORK_PREVIEW=1 source ./scripts/start-work.zsh --refresh-all`
previews locks (`all` without `--apply`) but still runs the toolchain module first;
Homebrew updates/installations/upgrades remain possible. Adding
`NUTRITION_START_WORK_SKIP_TOOL_UPDATES=1` prevents those toolchain mutations but
still performs tool selection and resolver scratch work. For a package lock preview,
use the targeted command without `--apply`, with preverified authorized prerequisites.
No preview flag grants broader authority. Whole-project refresh retains existing
transaction/resolver behavior; repairs tracked separately are not part of this rule.

## Session start

The standalone read-only session report remains available from any directory
inside the checkout:

```bash
./scripts/session-start.sh
```

Session start, session end and direct audit wrappers bind `NUTRITION_DEPS_PYTHON`
(or PATH `python3` when unset) for the report, audit and its `sys.executable` child
checks. Every audit entrypoint enforces `toolchain-report.py --check python` before
dependent work, including JSON sessions; gate diagnostics use stderr so JSON stdout
remains machine-readable. Missing or unsuitable selected Python refuses that work.
The standalone toolchain report remains available for independent diagnostic use.
No wrapper installs or upgrades tools.

The human-readable preflight reports Python and Node versions against their separate
repository contracts. Eligibility is command-specific: a missing or mismatched tool blocks checks
that require that tool and version, while independent checks may continue only when their own
prerequisites are satisfied. Python tests, validators, and qualification checks require the matching
Python line. Documentation work that does not require Node still requires suitable Python for its
Python checks. Results from unsuitable tooling are diagnostic only and cannot qualify a candidate.
Mobile qualification and CI require the matching Node line.

The session report then includes the Git branch and dirty files when `.git` metadata is available,
application and control migration heads, the latest Production Hardening phase document, whether
mobile files changed, and explicitly gated pytest markers. Archive reviews degrade cleanly and
report that Git metadata is unavailable.

Machine-readable repository-state output remains available with:

```bash
./scripts/session-start.sh --json
```

The standalone toolchain report is available with:

```bash
python3 scripts/toolchain-report.py
python3 scripts/toolchain-report.py --json
python3 scripts/toolchain-report.py --check node
```

Use a `--check` mode when the task requires an exact repository toolchain; it exits nonzero on a
mismatch or unavailable command.

## Session end

```bash
./scripts/session-end.sh
```

Session end delegates to the authoritative pre-commit workflow:

```bash
./scripts/project-audit.sh pre-commit
```

That command prints session state, validates configured application and control migration heads,
checks repository boundaries and placeholders, rejects forbidden mobile changes, verifies the
control inventory, runs `git diff --check`, and runs the configured focused audit-tooling tests.
Independent checks continue after an earlier failure so the final summary is complete. Expensive
PostgreSQL, MinIO, Docker/provider, performance, and concurrency suites are not run automatically;
the report lists them as opt-in and not run.

The boundary validator currently checks:

- one application migration head;
- one control migration head;
- control revision identifier width;
- forbidden mobile changes when Git metadata is present;
- configured unfinished placeholders;
- configured domain-table tokens in operational migrations.

The documentation validator separately checks local links and anchors, referenced executable
script existence, canonical release-qualification flags and migration heads, direct
session-workflow links, and required operational/historical document reachability from repository
entry points.

Warnings require review but do not fail the command. Errors fail it.

## Control-plane inventory

```bash
./scripts/project-audit.sh inventory
./scripts/project-audit.sh inventory --output /tmp/control-plane-inventory.json
```

The inventory records migration heads, authorization purpose/version constants, Phase 5C4 roles,
SQL functions, SQL tables, state tokens, and a canonical SHA-256 digest. It is a committed,
deterministic artifact at `apps/backend/evidence/control-plane-inventory.json`, consistent with the
repository's reviewed evidence manifests. Pre-commit regenerates it. If a tracked copy is stale, the
first run corrects the file and fails so the drift cannot be missed; review and include the updated
artifact with the source change, then rerun. The inventory changes only when one of its inventoried
contracts changes. It remains a static inventory; PostgreSQL qualification is authoritative for the
installed catalog.

## PostgreSQL privilege manifest

Collect a baseline from a disposable qualified control database:

```bash
CONTROL_DATABASE_URL='postgresql://...' \
  ./scripts/project-audit.sh privileges \
  --write-expected apps/backend/evidence/control-plane-privileges.json
```

Compare a later database with that reviewed baseline:

```bash
CONTROL_DATABASE_URL='postgresql://...' \
  ./scripts/project-audit.sh privileges \
  --expected apps/backend/evidence/control-plane-privileges.json
```

The manifest includes `nutrition_*` role attributes and memberships plus Phase 5C4 function owners
and ACLs. Baseline creation is an explicit review action; do not automatically accept a changed
manifest in CI.

## Configuration

Mechanical policy is stored in `scripts/project-audit.json`. Keep it narrow. Add only rules that
have deterministic pass/fail semantics. The configuration fixes expected migration heads, focused
audit test paths, the committed inventory path, exact placeholder exclusions, warning policy, and
the opt-in suite report. Placeholder exclusions are exact repository-relative files; directory-wide
or wildcard exclusions are rejected. Authority necessity, transaction correctness, lock ordering,
and recovery design remain architecture-review responsibilities.
