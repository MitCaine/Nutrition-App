+++
schema_version = 1
capsule_revision = 2
id = "GH-221-cleanup-checkpoint"
title = "Persist completed capsule cleanup after interrupted resume"
state = "READY"
task_type = "tooling"
risk = "medium"
created = "2026-09-27"
updated = "2026-09-27"
source_issue = "https://github.com/MitCaine/Nutrition-App/issues/221"
base_commit = "7f04a8aad7b879a4aec6f57e6d3c19df957425a7"
branch = "task/GH-221-cleanup-checkpoint-r2"
controller = "Codex Nutrition controller"
executor = "Codex bounded implementor"
reviewer = "Fresh independent exact-candidate reviewer"
delegation = "none"
delegation_constraints = []
blocked = false
blocked_reason = ""
blocked_since = ""
dependencies = ["GH-220-expo-holds"]
planning_artifacts = ["AGENTS.md", "engineering/workflow/START_HERE.md", "scripts/task.py", "scripts/tests/test_task_closeout.py"]
owned_paths = ["scripts/task.py", "scripts/tests/test_task_closeout.py", "engineering/capsules/active/GH-221-cleanup-checkpoint.md"]
allowed_paths = []
forbidden_paths = []
specialized_qualification = ["profile:repository", "evidence:focused", "evidence:baseline"]
+++

# GH-221-cleanup-checkpoint — Durable cleanup completion

## Goal

Make optional terminal checkout cleanup durably complete after successful worktree and branch removal, including interrupted resumes.

## Outcome

The final checkpoint records `COMPLETE` with the exact cleanup root and branch. A completed matching cleanup is idempotent before remote-main validation, while pending or mismatched targets retain the existing guards.

## Non-goals

No implementation/terminal integration gate change, force branch deletion, dirty-worktree deletion, cleanup of unrelated worktrees, or remote-main relaxation for pending cleanup.

## Background

Issue #221 and the supplied audit reproduced a resumed `finalize-cleanup` returning success while persisting `CLEANUP_PENDING`.

## Authority and precedence

Issue #221, trusted authorization comment 5860279908, this capsule and repository task-controller policy. RI supplies source evidence only.

## Dependencies and prerequisites

Exact integrated #220 base and disposable real-Git cleanup fixtures.

## Owned surface

Cleanup final checkpoint and focused task-closeout tests.

## Allowed changes

Authorized controller, test and capsule paths only.

## Forbidden changes

No protected-main integration change, branch force-delete, wrong-target cleanup, or arbitrary dirty-worktree removal.

## Acceptance criteria

- [ ] AC-1: A successful cleanup persists `COMPLETE` and the exact cleanup root/branch, both from fresh `COMPLETE` and resumed `CLEANUP_PENDING` entry.
- [ ] AC-2: Interruption after worktree removal, after branch deletion, and immediately before final checkpoint write can resume to durable `COMPLETE`.
- [ ] AC-3: Repeated matching completed cleanup remains idempotent after remote main advances; pending or wrong-target cleanup still fails closed, preserving exact target and clean-worktree guards.
- [ ] AC-4: Focused controller and repository checks pass, RI dispositions cover all changed paths, and an independent full-diff review approves without altering integration gates.

## Required verification

```nutrition-evidence-v1
[
  {"id":"focused","kind":"focused","required":true,"argv":["{python}","-m","pytest","-q","scripts/tests/test_task_closeout.py","-p","no:cacheprovider"]},
  {"id":"baseline","kind":"baseline","required":true,"argv":["./scripts/session-end.sh"]}
]
```

```nutrition-ri-v1
{"schema_version":1,"scope":"changed-files-v1"}
```

### Focused

Use disposable real Git worktrees and injected checkpoint interruptions; verify persistent JSON and later remote-main advancement.

### Baseline

Run repository session-end checks, including capsule validation.

### Specialized qualification

Dedicated App repository profile. No product or native source changes.

## Return evidence

Return exact B/P/C, frozen checks, App check, RI path dispositions and independent AC/path review. The sealed packet contains `evidence.structural.controller_disposition.paths` for every changed path; review those entries alongside the `record`. Read raw artifacts with `nutrition_read_evidence`, `check: "$structural"` and declared artifact names.

## Escalation conditions

Wrong root or branch, dirty checkout, moved pending main, changed terminal commit, incomplete interruption recovery, or failed evidence/review.

## Decisions and assumptions

Only the final checkpoint value changes in implementation; existing checks and operation order stay intact. Pending state is intentionally stricter than completed state.

## State history

| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| 2026-09-27 | — | DRAFT | controller | Audit F2 reproduced in source. |
| 2026-09-27 | DRAFT | GRILLED | controller | Resume cut points and completed idempotence boundaries examined. |
| 2026-09-27 | GRILLED | SPECIFIED | controller | Four candidate-reviewable criteria and real-Git tests selected. |
| 2026-09-27 | SPECIFIED | DECOMPOSED | controller | Final checkpoint and tests bounded; integration gates untouched. |
| 2026-09-27 | DECOMPOSED | READY | controller | Revision-two owner authorization comment 5860279908 follows a preserved reviewer STOP_REPLAN caused by overlooking present RI dispositions. |

Candidate review and terminal closeout occur after this implementation commit; Pending completion fields are lifecycle markers.

## Completion record

- **Reviewed commit:** Pending.
- **Merged commit:** Pending.
- **Review disposition:** Pending.
- **Verification summary:** Pending.
- **Specialized qualification:** Pending dedicated App repository check.
- **Known warnings:** Audit probe was narrow; interruption fixtures must exercise real Git state.
- **Deferred work/follow-up IDs:** #222.
- **Retrospective required:** yes — record recovered cleanup state.
