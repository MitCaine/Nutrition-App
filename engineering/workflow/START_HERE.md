# Start here: Nutrition task controller

> **Document role: Engineering Process.** Operator entrypoint for current work.

Use `./scripts/task` from a clean, synchronized trusted `main` checkout. Read the
issue and current source before preparing authority. Candidate code lives in a separate
checkout and never supplies the trusted controller or qualification policy.

## Orient once

Record remote main, issue/task ID, external authorization comment/revision/digest,
active capsule (if any), planning/candidate SHA, last proved phase, blocker and next
allowed action. Read [HISTORY](../capsules/HISTORY.md) when prior completion matters.
A closed issue, process exit, old approval or remembered branch tip is not proof.
Preserve dirty or in-flight work; do not replace an active capsule to free the queue.

## Current operating sequence

1. Run the [session preflight](../../docs/operations/session-contract.md).
2. From trusted main, use `./scripts/task prepare ISSUE` with the exact base, task
   ID, bounded allowed/forbidden paths and qualification profiles; then `authorize`.
3. Implement only that authorized scope in a separate task checkout. If this task
   explicitly uses a capsule, qualify its capsule-only planning overlay and render
   its handoff before implementation; keep its lifecycle through terminal closeout.
4. From trusted main, `./scripts/task qualify ISSUE --candidate-root PATH` qualifies
   the exact committed candidate through the existing dedicated-App boundary.
5. Record explicit verification and independent review for that same SHA with
   `./scripts/task verify` and `./scripts/task review`. Inspect the source and full
   diff against acceptance; tests never infer review approval.
6. With the owner's authorization, `./scripts/task integrate ISSUE --candidate-root
   PATH --human-owner-authorized` attempts the protected exact-SHA update. The flag
   records actual authorization, not permission to invent it. Existing explicit
   authorization need not be requested repeatedly.
7. Verify remote success. An active capsule still needs its separately authorized,
   qualified HISTORY/deletion closeout. Only then reconcile the issue and clean
   exact disposable refs/checkouts. Preserve recoverable work on failure.

The complete command options and trusted qualification transport remain in the
[testing guide](../../docs/operations/testing.md#trusted-task-controller-bootstrap).
The [authority contract](AUTHORITY.md) distinguishes current enforcement from the
capsule/RI migration target; it owns the binding design and compatibility inventory.

## Status and boundaries

The trusted task controller is the accepted normal entrypoint. Legacy Workflow v3's
capsule-wide promotion remains experimental. Issues #188–#194 explicitly authorize
bounded migration trials, not a default cutover. Later execution/checkpoint, richer
review and RI features must pass their own acceptance gates before use.

Initial local controller qualification targets macOS. Nutrition's existing Linux
CI jobs remain qualification authorities; local SQLite, remote PostgreSQL, iOS
native and physical/manual checks prove different things. Choose required profiles
from task impact and repository minimums. Unavailable mandatory proof blocks the
candidate. No model, parser, query result or capsule can weaken product invariants,
external authorization, dedicated-App checks or branch protection.
