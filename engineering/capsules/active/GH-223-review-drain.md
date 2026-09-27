+++
schema_version = 1
capsule_revision = 1
id = "GH-223-review-drain"
title = "Fail closed on reviewer activity discovered during terminal drain"
state = "IMPLEMENTED"
task_type = "tooling"
risk = "medium"
created = "2026-09-27"
updated = "2026-09-27"
source_issue = "https://github.com/MitCaine/Nutrition-App/issues/223"
base_commit = "9436e4b651ea2a7f54bc39c2e3d891fd6b6a261b"
branch = "task/GH-223-review-drain"
controller = "Codex Nutrition controller"
executor = "Codex bounded implementor"
reviewer = "Fresh independent exact-candidate reviewer"
delegation = "none"
delegation_constraints = []
blocked = false
blocked_reason = ""
blocked_since = ""
dependencies = ["GH-222-review-transport"]
planning_artifacts = ["AGENTS.md", "engineering/workflow/CANDIDATE_EVIDENCE.md", "scripts/lib/independent_review.py", "scripts/tests/test_independent_review.py"]
owned_paths = ["scripts/lib/independent_review.py", "scripts/tests/test_independent_review.py", "engineering/workflow/CANDIDATE_EVIDENCE.md", "engineering/capsules/active/GH-223-review-drain.md"]
allowed_paths = []
forbidden_paths = []
specialized_qualification = ["profile:repository", "evidence:focused", "evidence:baseline"]
+++

# GH-223-review-drain — Fail closed after complete reviewer drain

## Goal

Classify pre-review transport retry only after the entire reviewer terminal trace is observed.

## Outcome

An explicit model rejection with a clean drain permits the one existing retry. Late activity, protocol error, or failed drain stops replanning and retains both errors and the final trace.

## Non-goals

No extra retry, model fallback, verdict reuse, or qualification change.

## Background

Issue #223 documents a race where retryability is computed before `Rpc.close()` appends late events or raises a protocol error.

## Authority and precedence

Issue #223, trusted owner authorization, this capsule and repository controller policy. RI is navigation evidence only.

## Dependencies and prerequisites

Integrated #222 base and pinned reviewer runtime.

## Owned surface

Reviewer terminal classification, regression tests and reviewer workflow documentation.

## Allowed changes

Authorized transport, test, documentation and capsule paths only.

## Forbidden changes

No product source, broad retry classification or controller qualification bypass.

## Acceptance criteria

- [ ] AC-1: An explicit pre-review model rejection with clean terminal drain remains eligible for exactly one fresh same-candidate review.
- [ ] AC-2: Model rejection followed by late activity, a late server request or drain failure remains fail-closed, with no retry granted.
- [ ] AC-3: Diagnostics retain the original model rejection, any drain error and the complete observed trace.
- [ ] AC-4: Focused reviewer transport regression tests and repository baseline pass.

## Required verification

```nutrition-evidence-v1
[
  {"id":"focused","kind":"focused","required":true,"argv":["{python}","-m","pytest","-q","scripts/tests/test_independent_review.py","-p","no:cacheprovider"]},
  {"id":"baseline","kind":"baseline","required":true,"argv":["./scripts/session-end.sh"]}
]
```

```nutrition-ri-v1
{"schema_version":1,"scope":"changed-files-v1"}
```

### Focused

Inject a typed model rejection plus late activity and a drain error. Assert clean rejection alone retains retry eligibility.

### Baseline

Run repository session-end checks and capsule validation.

### Specialized qualification

Dedicated App repository profile.

## Return evidence

Return exact B/P/C, frozen checks, App check, RI controller dispositions and independent review. Controller disposition rows are in `evidence.structural.controller_disposition.paths`, separately from reviewer path verdicts.

## Escalation conditions

Any ambiguous trace, late request, failed drain, changed source or unsupported runtime.

## Decisions and assumptions

A late failure invalidates retryability even if an earlier model rejection was genuine. Preserve both errors for diagnosis.

## State history

| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| 2026-09-27 | — | DRAFT | controller | Re-audit #223. |
| 2026-09-27 | DRAFT | GRILLED | controller | Classified late drain and model rejection ordering. |
| 2026-09-27 | GRILLED | SPECIFIED | controller | Four non-circular acceptance criteria. |
| 2026-09-27 | SPECIFIED | DECOMPOSED | controller | Transport and tests bounded. |
| 2026-09-27 | DECOMPOSED | READY | controller | Owner authorization posted. |
| 2026-09-27 | READY | IN_PROGRESS | Codex controller | Exact plan and source boundary confirmed. |
| 2026-09-27 | IN_PROGRESS | IMPLEMENTED | Codex controller | Final-trace classification, dual-error diagnostics and combined regression implemented. |

## Completion record

- **Reviewed commit:** Pending.
- **Merged commit:** Pending.
- **Review disposition:** Pending.
- **Verification summary:** Pending.
- **Specialized qualification:** Pending dedicated App repository check.
- **Known warnings:** None.
- **Deferred work/follow-up IDs:** #224, #225, #226.
- **Retrospective required:** yes — record final trace classification.
