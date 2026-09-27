+++
schema_version = 1
capsule_revision = 5
id = "GH-222-review-transport"
title = "Recover only pre-review transport failures without replanning unchanged candidates"
state = "READY"
task_type = "tooling"
risk = "medium"
created = "2026-09-27"
updated = "2026-09-27"
source_issue = "https://github.com/MitCaine/Nutrition-App/issues/222"
base_commit = "7a19f3137f545b4bb30a540a4f33641793242c9e"
branch = "task/GH-222-review-transport-r5"
controller = "Codex Nutrition controller"
executor = "Codex bounded implementor"
reviewer = "Fresh independent exact-candidate reviewer"
delegation = "none"
delegation_constraints = []
blocked = false
blocked_reason = ""
blocked_since = ""
dependencies = ["GH-221-cleanup-checkpoint"]
planning_artifacts = ["AGENTS.md", "engineering/workflow/CANDIDATE_EVIDENCE.md", "scripts/lib/independent_review.py", "scripts/task.py"]
owned_paths = ["scripts/lib/independent_review.py", "scripts/task.py", "scripts/tests/test_independent_review.py", "scripts/tests/test_candidate_evidence.py", "engineering/workflow/CANDIDATE_EVIDENCE.md", "scripts/README.md", "engineering/capsules/active/GH-222-review-transport.md"]
allowed_paths = []
forbidden_paths = []
specialized_qualification = ["profile:repository", "evidence:focused", "evidence:baseline"]
+++

# GH-222-review-transport — Bounded reviewer transport recovery

## Goal

Reject unsupported reviewer models before costly qualification and permit one fresh reviewer attempt after a narrowly authenticated pre-review transport failure on unchanged evidence.

## Outcome

The controller preserves the failed trace, rechecks live authority, source and evidence, and permits exactly one fresh attempt. Every other failure remains fail-closed.

## Non-goals

No silent model fallback, inherited verdict, source drift acceptance, protocol relaxation, or retry of substantive review findings.

## Background

Issue #217 had an unsupported selected model before a verdict and required replanning unchanged candidate evidence. Issue #222 records the bounded recovery requirement.

## Authority and precedence

Issue #222, owner authorization comment, this capsule and repository controller policy. RI is navigation evidence only.

## Dependencies and prerequisites

Exact integrated #221 base and pinned Codex reviewer runtime.

## Owned surface

Reviewer transport classification, controller retry gate, focused tests and user command documentation.

## Allowed changes

Authorized controller, transport, tests, docs and capsule paths only.

## Forbidden changes

No product source, qualification bypass, review verdict reuse or broad retry on ambiguous failure.

## Acceptance criteria

- [ ] AC-1: Known unsupported reviewer model is rejected before expensive qualification where practical.
- [ ] AC-2: One genuine pre-review transport failure permits a fresh independent review against unchanged candidate and evidence without republishing or requalifying; failed trace remains inspectable.
- [ ] AC-3: Source drift, protocol violation, ambiguous execution, substantive review findings and exhausted retry allowance remain fail-closed.
- [ ] AC-4: Focused transport and controller tests pass, including preflight, bounded retry and fail-closed cases.

## Required verification

```nutrition-evidence-v1
[
  {"id":"focused","kind":"focused","required":true,"argv":["{python}","-m","pytest","-q","scripts/tests/test_independent_review.py","scripts/tests/test_candidate_evidence.py","-p","no:cacheprovider"]},
  {"id":"baseline","kind":"baseline","required":true,"argv":["./scripts/session-end.sh"]}
]
```

```nutrition-ri-v1
{"schema_version":1,"scope":"changed-files-v1"}
```

### Focused

Exercise exact transport failure classification, model preflight and controller retry state transitions.

### Baseline

Run repository session-end checks and capsule validation.

### Specialized qualification

Dedicated App repository profile.

## Return evidence

Return exact B/P/C, checks, App check, RI path dispositions and independent review. The actual controller-owned RI disposition rows are in the sealed request packet at `evidence.structural.controller_disposition.paths` (seven rows), separately from the reviewer-produced `structural_review` verdict rows. Inspect both before claiming either is absent. Raw artifacts can be read using `check: "$structural"`.

## Escalation conditions

Ambiguous transport, reviewer activity, unsupported runtime, source drift, changed evidence or exhausted retry.

## Decisions and assumptions

Retry authority is limited to a typed, authenticated failure before any reviewer output or tool use. The model is always explicit; no fallback is selected.

## State history

| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| 2026-09-27 | — | DRAFT | controller | Audit issue #222. |
| 2026-09-27 | DRAFT | GRILLED | controller | Reviewed pre-review and ambiguous failure boundaries. |
| 2026-09-27 | GRILLED | SPECIFIED | controller | Four acceptance criteria selected. |
| 2026-09-27 | SPECIFIED | DECOMPOSED | controller | Transport, controller, tests and docs bounded. |
| 2026-09-27 | DECOMPOSED | READY | controller | Revision-five owner authorization posted after retained reviewer STOP_REPLAN on a circular review-proof AC. |

## Completion record

- **Reviewed commit:** Pending.
- **Merged commit:** Pending.
- **Review disposition:** Pending.
- **Verification summary:** Pending.
- **Specialized qualification:** Pending dedicated App repository check.
- **Known warnings:** None.
- **Deferred work/follow-up IDs:** None.
- **Retrospective required:** yes — record retry boundaries.
