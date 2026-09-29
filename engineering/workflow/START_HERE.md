# Start here: Nutrition task controller

> **Document role: Engineering Process.** Operator entrypoint for current work.

Use `./scripts/task` from a clean, synchronized trusted `main` checkout. Read the
issue and current source before preparing authority. Candidate code lives in a separate
checkout and never supplies the trusted controller or qualification policy.
The `task` launcher accepts the selected Python line from the trusted checkout's
PATH. If it is missing, provision/select that host interpreter first; the launcher
does not probe virtual environments in candidate worktrees.

## Orient once

Record remote main, issue/task ID, external authorization comment/revision/digest,
active capsule (if any), planning/candidate SHA, last proved phase, blocker and next
allowed action. Read [HISTORY](../capsules/HISTORY.md) when prior completion matters.
A closed issue, process exit, old approval or remembered branch tip is not proof.
Preserve dirty or in-flight work; do not replace an active capsule to free the queue.

## Current operating sequence

1. In the working checkout, run `source ./scripts/start-work.zsh` in an
   integrated zsh terminal. It refreshes compatible dependencies and invokes the
   [session preflight](../../docs/operations/session-contract.md). Keep the
   trusted controller checkout clean and synchronized; use its standalone
   `./scripts/session-start.sh` when startup updates belong to a separate task.
   A nonzero update result must be reported and resolved in its own bounded task;
   it does not authorize changes outside the active capsule.
2. From trusted main, use `./scripts/task prepare ISSUE` with the exact base, task
   ID, bounded allowed/forbidden paths and qualification profiles; then `authorize`.
3. For a new task, create its bounded capsule, qualify the capsule-only planning
   overlay and render its handoff before implementing only the authorized scope in
   a separate task checkout. Use the pinned RI runtime for source navigation and
   changed-path evidence; supported structural results supplement full diff review,
   while unsupported files still require direct review. Keep the capsule lifecycle
   through terminal closeout. An in-flight unattached task or explicit compatibility
   exception may retain its existing path without inventing a capsule after the fact.
   `./scripts/task execution prepare` resolves the current owner authorization and
   controller-selected workflow mode, validates the evidence, review-obligation and
   selected RI blocks in-process, then renders the handoff. Available trusted issue text
   is used to check quoted outcomes; unavailable issue text is reported as unchecked and
   is never replaced with capsule-authored claims. The validator and renderer CLIs reject
   serialized planning context because it cannot authenticate mode or identity; offline
   validation is diagnostic only and cannot emit an executor handoff. Exact-C attachment
   repeats the checks and retains the live issue, reviewer-preflight, qualification,
   command-evidence and independent-review gates. Explicit compatibility work may omit
   attached-only blocks.
4. For a capsule-attached candidate, follow the [evidence sequence](CANDIDATE_EVIDENCE.md):
   attach exact C, preflight the pinned reviewer runtime/model/effort, and capture required
   command and RI evidence. From trusted main, then run `./scripts/task qualify ISSUE
   --candidate-root PATH` for the exact committed candidate through the dedicated-App boundary.
   The controller requires the candidate-bound preflight before dispatch for attached tasks.
   An unattached compatibility or terminal closeout task uses its existing qualification path.
5. For an attached candidate, seal qualification, record verification and run the independent
   reviewer with the same preflighted runtime/model/effort. A genuine pre-review failure
   requires another explicit preflight before the one fresh review attempt on unchanged C;
   qualification is retained. For compatibility tasks, record explicit verification and review for that same SHA with
   `./scripts/task verify` and `./scripts/task review`. Inspect the source and full
   diff against acceptance; tests never infer review approval.
6. With the owner's authorization, `./scripts/task integrate ISSUE --candidate-root
   PATH --human-owner-authorized` attempts the protected exact-SHA update. The flag
   records actual authorization, not permission to invent it. Existing explicit
   authorization need not be requested repeatedly.
7. For a capsule task using the guarded closeout, run `./scripts/task finalize ISSUE
   --candidate-root PATH --terminal-state-dir STATE --human-owner-authorized`.
   It durably records the implementation and resumes its guarded integration if needed.
   Prepare a distinct `TASK-ID-closeout` authorization at the integrated C, preserve
   the full REVIEWED capsule in reachable recovery commit R, and form direct-child T
   with only HISTORY plus active-capsule removal. Qualify, verify and independently
   review T with its own check. Rerun `finalize` with `--terminal-root PATH
   --recovery-sha R`; it validates the separate evidence, integrates T, verifies
   remote main and recovery, then closes the issue. Repeat the same command after an
   interruption; changed candidate or terminal intent stops. Preserve dirty or
   unrelated refs/checkouts, failed attempts and recovery evidence.
   Keep the attached C checkout on its original branch throughout R/T preparation:
   create R in a separate worktree on `evidence/GH-ISSUE-recovery` and T in a
   separate worktree on `task/GH-ISSUE-closeout`. Do not switch the attached C
   checkout to either branch and back; that can rewrite its sealed Git index.
   From a separate trusted checkout at C, the branch-creation shape is:

   ```bash
   git worktree add -b evidence/GH-ISSUE-recovery "$RECOVERY_ROOT" "$C"
   git worktree add -b task/GH-ISSUE-closeout "$TERMINAL_ROOT" "$C"
   ```

   Replace `ISSUE`, `RECOVERY_ROOT`, `TERMINAL_ROOT` and `C` with the exact task
   values. Commit the reviewed full capsule on R; commit only HISTORY and active
   capsule deletion on T. Validate R/T before the second `finalize` call.
   A resumed finalizer accepts only those two exact refs after validating R/T and
   their separate authority. It still rejects changed C source/index or any other
   ref change. If a prior attempt changed C's index, use the separately authorized
   terminal controller and preserve the failed guarded-finalize evidence; do not
   silently reattach C or reset its index to force a pass.
   The terminal authorization must name the exact active `engineering/capsules/active/TASK-ID.md`
   path; the task ID may include a bounded suffix after `GH-ISSUE`. A receipted advance of
   `origin/main` may also move its `origin/HEAD` alias, but any unrelated ref drift stops.
   Optional `task finalize-cleanup ISSUE --cleanup-root PATH --cleanup-branch NAME` removes
   only the exact clean terminal checkout/branch after remote T and issue closure;
   it refuses recovery, dirty, wrong-branch and moved-main targets.
   A cancelled capsule uses `task finalize-cancel ISSUE --terminal-state-dir STATE
   --terminal-root PATH --recovery-sha R --human-owner-authorized` with its own
   reviewed and qualified `CANCELLED` terminal commit; no implementation C is
   accepted or inferred.

The complete command options and trusted qualification transport remain in the
[testing guide](../../docs/operations/testing.md#trusted-task-controller-bootstrap).
The [authority contract](AUTHORITY.md) distinguishes current enforcement from
remaining migration work; it owns the binding design and compatibility inventory.

## Status and boundaries

The trusted task controller remains the accepted entrypoint. The owner's
[2026-09-27 decision](https://github.com/MitCaine/Nutrition-App/issues/187#issuecomment-5859326452)
makes capsule attachment and RI evidence normal for new tasks. The
[bounded execution/checkpoint command](EXECUTION.md) supplies an isolated macOS
local-command transport when selected. The [candidate evidence lane](CANDIDATE_EVIDENCE.md)
binds exact commands, qualification, structural path dispositions where supported,
and observed independent review. The [pinned RI navigation command](../tooling/RI.md)
supplies exact committed-source locations, never authority. The unattached controller
path and `scripts/capsule` remain for in-flight/explicit compatibility work; their
retirement requires a separate caller inventory and migration/recovery review.
The [pilot record](PILOT_2026-09-26.md) contains historical decisions and failures;
the [changelog](CHANGELOG.md) records the current decision and measurement limits.
Inspect current remote main and issue state first; historical SHAs are never a base
to reuse without revalidation.

Initial local controller qualification targets macOS. Nutrition's existing Linux
CI jobs remain qualification authorities; local SQLite, remote PostgreSQL, iOS
native and physical/manual checks prove different things. Choose required profiles
from task impact and repository minimums. Unavailable mandatory proof blocks the
candidate. No model, parser, query result or capsule can weaken product invariants,
external authorization, dedicated-App checks or branch protection.
