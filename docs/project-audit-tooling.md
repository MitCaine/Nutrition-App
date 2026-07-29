# Project Audit Tooling

The repository provides deterministic mechanical checks for work that should not require repeated
agent interpretation. These tools do not replace architectural review. They establish repository
state, identify mechanical boundary violations, inventory the Phase 5C4 control plane, and compare
PostgreSQL privilege manifests.

## Repository session contract

Every implementation session must run:

```bash
./scripts/session-start.sh
```

before implementation, and:

```bash
./scripts/session-end.sh
```

before claiming completion. A nonzero session-end exit is blocking: the implementation must not be
described as complete. `WARN` findings are non-blocking unless configuration explicitly elevates
them; `ERROR` findings are blocking. Reports must include the final session-end result and accurately
identify opt-in infrastructure suites as passed, failed, or not run.

Agents must not bypass a failure by weakening a validator, adding a broad exclusion, or deleting an
incomplete test. Future prompts may invoke these requirements with: **“Follow the repository session
contract.”**

## Session start

Run from any directory inside the checkout:

```bash
./scripts/session-start.sh
```

The report includes the Git branch and dirty files when `.git` metadata is available, application
and control migration heads, the latest Production Hardening phase document, whether mobile files
changed, and explicitly gated pytest markers. Archive reviews degrade cleanly and report that Git
metadata is unavailable.

Machine-readable output is available with:

```bash
./scripts/session-start.sh --json
```

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
