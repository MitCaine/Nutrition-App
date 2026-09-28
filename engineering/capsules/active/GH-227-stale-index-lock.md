+++
schema_version = 1
capsule_revision = 1
id = "GH-227-stale-index-lock"
title = "Recover transaction-owned stale Git index locks"
state = "IMPLEMENTED"
task_type = "tooling"
risk = "low"
created = "2026-09-27"
updated = "2026-09-27"
source_issue = "https://github.com/MitCaine/Nutrition-App/issues/227"
base_commit = "f645c39b94722e06810b31da5caba6684500f349"
branch = "task/GH-227-stale-index-lock"
controller = "Codex Nutrition controller"
executor = "Codex bounded implementor"
reviewer = "Fresh independent exact-candidate reviewer"
delegation = "none"
delegation_constraints = []
blocked = false
blocked_reason = ""
blocked_since = ""
dependencies = ["GH-226-lock-publication"]
planning_artifacts = ["AGENTS.md", "scripts/lib/update_transaction.py", "scripts/update_dependencies.py", "scripts/tests/test_update_transaction.py"]
owned_paths = ["scripts/lib/update_transaction.py", "scripts/update_dependencies.py", "scripts/tests/test_update_transaction.py", "scripts/README.md", "engineering/capsules/active/GH-227-stale-index-lock.md"]
allowed_paths = []
forbidden_paths = []
specialized_qualification = ["profile:repository", "evidence:focused", "evidence:baseline"]
+++

# GH-227-stale-index-lock — Recover transaction-owned stale Git locks

## Goal

Eliminate manual Git index-lock cleanup after abrupt updater death without touching locks that may belong to Git or another process.

## Outcome

The updater's durable transaction records a random lock owner identity. Its Git index lock appears atomically with an exact transaction-bound ownership record. A later invocation that holds the updater's per-checkout process lock may remove only the matching stale lock, then reconcile exact lockfile bytes through the existing transaction ledger. Unknown or changed locks remain untouched.

## Non-goals

No generalized Git lock cleanup, stale-PID guess, checkout reset, package update, or weakening of #226 publication guards.

## Background

Issue #227 follows the post-#226 audit: `publication_guard()` uses `O_EXCL` and removes its Git lock only in `finally`, so abrupt process death leaves a permanent busy error.

## Authority and precedence

Issue #227, trusted owner authorization, this capsule and repository controller policy. RI is navigation evidence only.

## Dependencies and prerequisites

Integrated #226 base, clean isolated worktree, authenticated per-checkout transaction.

## Owned surface

Updater transaction owner token and recovery, focused real-Git tests, script index guidance.

## Allowed changes

Authorized updater, transaction, tests, docs and capsule paths only.

## Forbidden changes

No product code, package-lock changes, unknown Git-lock deletion or user-edit rollback.

## Acceptance criteria

- [ ] AC-1: Git index lock creation exposes only a complete transaction-bound owner record, including across a simulated crash boundary.
- [ ] AC-2: A later invocation holding the updater process lock recovers only the exact stale lock and reconciles before/after lock bytes through the existing transaction ledger.
- [ ] AC-3: Unknown, modified, mismatched-transaction and active Git locks remain untouched and fail closed.
- [ ] AC-4: Focused updater tests and repository baseline pass; operator guidance distinguishes automatic from manual recovery.

## Required verification

```nutrition-evidence-v1
[
  {"id":"focused","kind":"focused","required":true,"argv":["{python}","-m","pytest","-q","scripts/tests/test_update_transaction.py","scripts/tests/test_update_dependencies.py","-p","no:cacheprovider"]},
  {"id":"baseline","kind":"baseline","required":true,"argv":["./scripts/session-end.sh"]}
]
```

```nutrition-ri-v1
{"schema_version":1,"scope":"changed-files-v1"}
```

### Focused

Real-Git stale-lock crash simulation, exact owner recovery, unknown and mismatched lock refusals, published and unpublished transaction resume.

### Baseline

Repository session-end checks and capsule/document validation.

### Specialized qualification

Dedicated App repository profile.

## Return evidence

Return exact B/P/C, frozen checks, dedicated App check, RI path dispositions and independent review. Check logs use `nutrition_read_evidence` with `check: "focused"`/`"baseline"` and `artifact: "stdout.log"`/`"stderr.log"`; RI uses `check: "$structural"` and declared artifact names. Keep reads bounded.

## Escalation conditions

Any unknown Git lock is removed, a live updater lock is ignored, the transaction cannot resume, or staged/user bytes are overwritten.

## Decisions and assumptions

Ownership is a random transaction nonce bound to exact checkout identity and stored in the durable ledger. Atomic hard-link creation prevents a visible partial owner record. Recovery is only called from the updater path after its per-checkout process lock is acquired.

## State history

| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| 2026-09-27 | — | DRAFT | controller | Re-audit #227. |
| 2026-09-27 | DRAFT | GRILLED | controller | Examined crash interval, Git index lock ownership, process lock and transaction resume. |
| 2026-09-27 | GRILLED | SPECIFIED | controller | Four acceptance criteria and real-Git recovery tests. |
| 2026-09-27 | SPECIFIED | DECOMPOSED | controller | Transaction, updater caller, tests and operator guidance bounded. |
| 2026-09-27 | DECOMPOSED | READY | controller | Revision-one owner authorization posted by controller. |
| 2026-09-27 | READY | IN_PROGRESS | Codex controller | Exact planning and checkout boundary confirmed. |
| 2026-09-27 | IN_PROGRESS | IMPLEMENTED | Codex controller | Transaction-bound atomic Git lock ownership, exact stale recovery, crash tests and operator guidance implemented. |

## Completion record

- **Reviewed commit:** Pending.
- **Merged commit:** Pending.
- **Review disposition:** Pending.
- **Verification summary:** Pending.
- **Specialized qualification:** Pending dedicated App repository check.
- **Known warnings:** None.
- **Deferred work/follow-up IDs:** None.
- **Retrospective required:** yes — record crash-safe ownership behavior.
