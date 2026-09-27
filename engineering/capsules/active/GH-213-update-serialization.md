+++
schema_version = 1
capsule_revision = 3
id = "GH-213-update-serialization"
title = "Serialize dependency updater runs"
state = "IMPLEMENTED"
task_type = "tooling"
risk = "medium"
created = "2026-09-27"
updated = "2026-09-27"
source_issue = "https://github.com/MitCaine/Nutrition-App/issues/213"
base_commit = "8c103e87788a8abebf4e88d5cf5d665b2c4c071c"
branch = "task/GH-213-update-serialization-r3"
controller = "Codex Nutrition controller"
executor = "Codex bounded implementor"
reviewer = "Fresh independent exact-candidate reviewer"
delegation = "none"
delegation_constraints = []
blocked = false
blocked_reason = ""
blocked_since = ""
dependencies = []
planning_artifacts = ["AGENTS.md", "engineering/workflow/START_HERE.md", "engineering/workflow/CANDIDATE_EVIDENCE.md", "engineering/tooling/RI.md"]
owned_paths = ["scripts/update_dependencies.py", "scripts/tests/test_update_dependencies.py", "scripts/README.md", "engineering/capsules/active/GH-213-update-serialization.md"]
allowed_paths = []
forbidden_paths = []
specialized_qualification = ["profile:repository", "evidence:focused", "evidence:baseline"]
+++

# GH-213-update-serialization — Serialize dependency updater runs

## Goal

Prevent overlapping updater invocations from racing lock publication while preserving independent per-area updates.

## Outcome

One process owns updater preflight, resolution, and publication; a second fails promptly with a clear contention message. Backend, mobile, and RI area failures still remain independent within one invocation.

## Non-goals

No dependency version changes, CI policy changes, new global lock manager, or changes to the normal controller.

## Background

The updater checks a clean checkout and snapshots per-area inputs, but separate processes can race between those checks and publication. #187 selects this bounded Python opt-in combined-workflow proving sample.

## Authority and precedence

Issue #213, its exact external authorization, this frozen capsule, Nutrition workflow contract, and protected-main ruleset. RI supplies source facts only.

## Dependencies and prerequisites

Exact authorized base commit above, macOS controller, and pinned installed RI runtime. Planning P must be a capsule-only child of the base.

## Owned surface

Updater entrypoint, focused tests, command documentation, and this capsule.

## Allowed changes

Add a process-lifetime, crash-released exclusive updater lock and focused tests; explain contention in command documentation.

## Forbidden changes

Do not modify lockfiles, dependency constraints, backend/mobile application code, per-area failure continuation, controller authority, or private RI material.

## Acceptance criteria

- [ ] AC-1: A second updater process fails promptly before update work or lock publication, with an actionable contention message.
- [ ] AC-2: Ownership releases after normal completion or failure, including process death, so a later invocation can proceed.
- [ ] AC-3: A failed selected area does not prevent other selected areas from running in one owned invocation.
- [ ] AC-4: Exact planning-to-candidate RI changed-path evidence, frozen focused/baseline commands, and dedicated repository qualification pass and receive independent exact-SHA review.

## Required verification

```nutrition-evidence-v1
[
  {"id":"focused","kind":"focused","required":true,"argv":["{python}","-m","unittest","discover","-s","scripts/tests","-p","test_update_dependencies.py"]},
  {"id":"baseline","kind":"baseline","required":true,"argv":["./scripts/run-review.sh","--profile","repository","--no-package"]}
]
```

```nutrition-ri-v1
{"schema_version":1,"scope":"changed-files-v1"}
```

### Focused

Frozen updater unittest command above, exact diff inspection and RI structural path dispositions.

### Baseline

Frozen repository review command above, capsule validation and whitespace check.

### Specialized qualification

Dedicated App repository profile for C; separate repository profile for terminal T. No backend/mobile/native/profile substitution is inferred from this scripts-only change.

## Return evidence

Exact B/P/C/T identities, observed contention and release tests, per-area continuation test, RI comparison and path dispositions, command records, App check, independent review and terminal recovery locator.

## Escalation conditions

Moved base/main, altered scope or capsule semantics, unavailable mandatory RI/command/reviewer evidence, failed qualification or ambiguous integration stops for replan or correction.

## Decisions and assumptions

The lock is scoped to this updater and the working repository. The combined lane remains opt-in; this task does not promote it.

## State history

| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| 2026-09-27 | — | DRAFT | controller | Scoped issue #213. |
| 2026-09-27 | DRAFT | GRILLED | controller | Concurrent update race and crash recovery bounded. |
| 2026-09-27 | GRILLED | SPECIFIED | controller | Four observable criteria and frozen proof selected. |
| 2026-09-27 | SPECIFIED | DECOMPOSED | controller | One updater and test/documentation surface. |
| 2026-09-27 | DECOMPOSED | READY | controller | Revision-three authority and fresh capsule-only planning overlay; failed C1 and reviewer-runtime C2 evidence preserved. |
| 2026-09-27 | READY | IN_PROGRESS | Codex controller | Revision-three external authorization and unchanged bounded implementation |
| 2026-09-27 | IN_PROGRESS | IMPLEMENTED | Codex controller | Corrected updater implementation committed; independent review uses qualified explicit model |

## Completion record

- **Reviewed commit:**
- **Merged commit:**
- **Review disposition:**
- **Verification summary:**
- **Specialized qualification:**
- **Known warnings:**
- **Deferred work/follow-up IDs:** #187.
- **Retrospective required:** yes — #187 proving measurement.
