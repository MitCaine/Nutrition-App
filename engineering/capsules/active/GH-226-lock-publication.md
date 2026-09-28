+++
schema_version = 1
capsule_revision = 1
id = "GH-226-lock-publication"
title = "Guard dependency lock publication against checkout switches"
state = "IMPLEMENTED"
task_type = "tooling"
risk = "low"
created = "2026-09-27"
updated = "2026-09-27"
source_issue = "https://github.com/MitCaine/Nutrition-App/issues/226"
base_commit = "831260aaaf1db64e7077205805c6b68e89f13c2e"
branch = "task/GH-226-lock-publication"
controller = "Codex Nutrition controller"
executor = "Codex bounded implementor"
reviewer = "Fresh independent exact-candidate reviewer"
delegation = "none"
delegation_constraints = []
blocked = false
blocked_reason = ""
blocked_since = ""
dependencies = ["GH-225-preflight-gate"]
planning_artifacts = ["AGENTS.md", "scripts/update_dependencies.py", "scripts/lib/update_transaction.py", "scripts/tests/test_update_transaction.py"]
owned_paths = ["scripts/update_dependencies.py", "scripts/lib/update_transaction.py", "scripts/tests/test_update_transaction.py", "scripts/tests/test_update_dependencies.py", "scripts/README.md", "docs/operations/dependency-risk-management.md", "engineering/capsules/active/GH-226-lock-publication.md"]
allowed_paths = []
forbidden_paths = []
specialized_qualification = ["profile:repository", "evidence:focused", "evidence:baseline"]
+++

# GH-226-lock-publication — Guard dependency lock publication

## Goal

Keep a validated backend or mobile lock proposal from being silently written into a different checkout at the final publication boundary.

## Outcome

A short Git-compatible checkout guard covers the final single-file replacement. Identity is rechecked after publication, and a detected identity bypass either restores only updater-written bytes or leaves explicit recovery evidence without overwriting user edits. Normal single-file publication and transaction resume remain intact.

## Non-goals

No broad Git lock bypass, implicit checkout reset, package resolver changes or product source changes.

## Background

Issue #226 records a pre-write identity check followed by `os.replace` and a later transaction check. A checkout switch in that interval can affect a different branch's lockfile.

## Authority and precedence

Issue #226, trusted owner authorization, this capsule and repository controller policy. RI is navigation evidence only.

## Dependencies and prerequisites

Integrated #225 base and clean isolated worktree.

## Owned surface

Dependency updater publication and transaction guard, focused tests and operator documentation.

## Allowed changes

Authorized updater, transaction, tests, docs and capsule paths only.

## Forbidden changes

No package version churn, lockfile changes, product code or destructive rollback of user edits.

## Acceptance criteria

- [ ] AC-1: A deterministic checkout switch at the final write boundary cannot leave an unaccounted updater lockfile in the changed checkout.
- [ ] AC-2: Normal single-file backend/mobile publication and exact safe resume remain functional.
- [ ] AC-3: Recovery does not overwrite intervening user edits and retains actionable evidence when safe restoration is impossible.
- [ ] AC-4: Focused updater tests and repository baseline pass.

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

Exercise a real Git checkout switch attempt at publication, a forced ref identity bypass, safe rollback and unchanged resume.

### Baseline

Run repository session-end checks and capsule validation.

### Specialized qualification

Dedicated App repository profile.

## Return evidence

Return exact B/P/C, frozen checks, dedicated App check, RI path dispositions and independent review. Read declared check logs with `nutrition_read_evidence` using `check: "focused"`/`"baseline"` and `artifact: "stdout.log"`/`"stderr.log"`; RI artifacts use `check: "$structural"` with declared names. Use short bounded ranges for large artifacts.

## Escalation conditions

A checkout identity bypass leaves an unaccounted lockfile, a user edit is overwritten, or safe resume regresses.

## Decisions and assumptions

Use Git's short-lived index lock to serialize normal branch switches. Recheck identity after replacement for out-of-band ref movement and restore only bytes that still exactly match the updater proposal; otherwise retain explicit recovery evidence.

## State history

| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| 2026-09-27 | — | DRAFT | controller | Re-audit #226. |
| 2026-09-27 | DRAFT | GRILLED | controller | Examined transaction ledger, Git switch locking and rollback safety. |
| 2026-09-27 | GRILLED | SPECIFIED | controller | Four acceptance criteria and deterministic real-Git test. |
| 2026-09-27 | SPECIFIED | DECOMPOSED | controller | Updater, transaction guard, tests and docs bounded. |
| 2026-09-27 | DECOMPOSED | READY | controller | Revision-one owner authorization posted. |
| 2026-09-27 | READY | IN_PROGRESS | Codex controller | Exact planning and checkout boundary confirmed. |
| 2026-09-27 | IN_PROGRESS | IMPLEMENTED | Codex controller | Git index publication guard, post-write identity recovery, focused tests and operator note implemented. |

## Completion record

- **Reviewed commit:** Pending.
- **Merged commit:** Pending.
- **Review disposition:** Pending.
- **Verification summary:** Pending.
- **Specialized qualification:** Pending dedicated App repository check.
- **Known warnings:** None.
- **Deferred work/follow-up IDs:** None.
- **Retrospective required:** yes — record publication recovery behavior.
