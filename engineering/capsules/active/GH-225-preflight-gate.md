+++
schema_version = 1
capsule_revision = 3
id = "GH-225-preflight-gate"
title = "Bind reviewer preflight into the normal qualification workflow"
state = "READY"
task_type = "tooling"
risk = "medium"
created = "2026-09-27"
updated = "2026-09-27"
source_issue = "https://github.com/MitCaine/Nutrition-App/issues/225"
base_commit = "4a003454a66217b82d532f403cfc2beb419bc479"
branch = "task/GH-225-preflight-gate-r3"
controller = "Codex Nutrition controller"
executor = "Codex bounded implementor"
reviewer = "Fresh independent exact-candidate reviewer"
delegation = "none"
delegation_constraints = []
blocked = false
blocked_reason = ""
blocked_since = ""
dependencies = ["GH-224-retry-stop"]
planning_artifacts = ["AGENTS.md", "engineering/workflow/START_HERE.md", "engineering/workflow/CANDIDATE_EVIDENCE.md", "scripts/task.py"]
owned_paths = ["scripts/task.py", "scripts/tests/test_candidate_evidence.py", "scripts/lib/independent_review.py", "scripts/tests/test_independent_review.py", "engineering/workflow/START_HERE.md", "engineering/workflow/CANDIDATE_EVIDENCE.md", "docs/operations/testing.md", "scripts/README.md", "engineering/capsules/active/GH-225-preflight-gate.md"]
allowed_paths = []
forbidden_paths = []
specialized_qualification = ["profile:repository", "evidence:focused", "evidence:baseline"]
+++

# GH-225-preflight-gate — Bind reviewer selection before qualification

## Goal

Make pinned reviewer model preflight an enforceable step before expensive attached-candidate qualification and bind review to the selected runtime, model and effort.

## Outcome

The primary workflow orders attach, preflight, evidence, qualification, seal/verify and review. A genuine pre-review rejection may be followed by a new explicit preflight on unchanged C without another qualification. The reviewer can read digest-bound RI evidence even when the producer writes one long JSON line.

## Non-goals

No new gate for unattached compatibility or terminal closeout tasks, silent fallback, qualification rework, or verdict reuse.

## Background

Issue #225 records that #222's preflight is optional, its saved result is unused, and START_HERE qualifies before introducing the evidence lane.

## Authority and precedence

Issue #225, trusted owner authorization, this capsule and repository controller policy. RI is navigation evidence only.

## Dependencies and prerequisites

Integrated #224 base and a pinned qualified reviewer runtime.

## Owned surface

Task controller preflight binding, tests and operator documentation.

## Allowed changes

Authorized controller, tests, documentation and capsule paths only.

## Forbidden changes

No product source, broadened reviewer permissions, attached qualification bypass or terminal closeout regression.

## Acceptance criteria

- [ ] AC-1: Attached new-task C cannot begin hosted qualification without a valid candidate-bound pinned reviewer model/effort preflight; unattached compatibility and terminal tasks remain supported.
- [ ] AC-2: Review rejects runtime/model/effort mismatch and requires a fresh preflight after a genuine pre-review failure; the one unchanged-C retry need not requalify.
- [ ] AC-3: Primary and testing workflows order attach, preflight, required evidence, qualification, seal/verify and independent review without contradiction.
- [ ] AC-4: Focused controller tests and repository baseline pass, including bounded reads of a long RI evidence line.

## Required verification

```nutrition-evidence-v1
[
  {"id":"focused","kind":"focused","required":true,"argv":["{python}","-m","pytest","-q","scripts/tests/test_candidate_evidence.py","scripts/tests/test_independent_review.py","-p","no:cacheprovider"]},
  {"id":"baseline","kind":"baseline","required":true,"argv":["./scripts/session-end.sh"]}
]
```

```nutrition-ri-v1
{"schema_version":1,"scope":"changed-files-v1"}
```

### Focused

Exercise missing/mismatched preflight before qualification, review selection, retry reselection and unattached compatibility.

### Baseline

Run repository session-end checks and capsule validation.

### Specialized qualification

Dedicated App repository profile.

## Return evidence

Return exact B/P/C, frozen checks, App check, RI controller dispositions and independent review. Controller disposition rows are in `evidence.structural.controller_disposition.paths`, separately from reviewer path verdicts. For bounded raw checks use `nutrition_read_evidence` with `check: "focused"` or `"baseline"` and `artifact: "stdout.log"`/`"stderr.log"`; for RI use `check: "$structural"` and `artifact: "raw"`, `"comparison"`, `"compact"`, or `"packet"` as declared in the sealed packet. `check: "structural"` and artifact names `"focused"` or `"baseline"` are not declared callbacks. Request short ranges for large artifacts, including one virtual line at a time for long JSON; use returned `total_lines` and the concise `compact`/`packet` artifacts. An over-limit first read is not evidence absence; retry with a smaller range.

## Escalation conditions

Hosted dispatch without attached preflight, mismatched review selection, lost same-C retry or compatibility regression.

## Decisions and assumptions

The controller state is private trusted evidence; bind preflight to exact attached candidate and require an explicit model and effort.

## State history

| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| 2026-09-27 | — | DRAFT | controller | Re-audit #225. |
| 2026-09-27 | DRAFT | GRILLED | controller | Reviewed attached, retry and terminal compatibility paths. |
| 2026-09-27 | GRILLED | SPECIFIED | controller | Four acceptance criteria and controller tests. |
| 2026-09-27 | SPECIFIED | DECOMPOSED | controller | Gate, binding and docs bounded. |
| 2026-09-27 | DECOMPOSED | READY | controller | Revision-three owner authorization posted after retained reviewer STOP_REPLAN exposed unreadable single-line RI evidence. |

## Completion record

- **Reviewed commit:** Pending.
- **Merged commit:** Pending.
- **Review disposition:** Pending.
- **Verification summary:** Pending.
- **Specialized qualification:** Pending dedicated App repository check.
- **Known warnings:** None.
- **Deferred work/follow-up IDs:** #226.
- **Retrospective required:** yes — record normal operator ordering.
