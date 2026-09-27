+++
schema_version = 1
capsule_revision = 7
id = "GH-216-finalize-continuation"
title = "Repair guarded finalize continuation after terminal R/T preparation"
state = "READY"
task_type = "tooling"
risk = "medium"
created = "2026-09-27"
updated = "2026-09-27"
source_issue = "https://github.com/MitCaine/Nutrition-App/issues/216"
base_commit = "bcbaa35a91dd1c741bdd8dfa77820b9224fc90d4"
branch = "task/GH-216-finalize-continuation-r7"
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
owned_paths = ["scripts/lib/candidate_evidence.py", "scripts/task.py", "scripts/tests/test_candidate_evidence.py", "scripts/tests/test_task_closeout.py", "engineering/workflow/START_HERE.md", "engineering/workflow/PILOT_2026-09-26.md", "engineering/workflow/CHANGELOG.md", "engineering/capsules/active/GH-216-finalize-continuation.md"]
allowed_paths = []
forbidden_paths = []
specialized_qualification = ["profile:repository", "evidence:focused", "evidence:baseline"]
+++

# GH-216-finalize-continuation — Repair guarded finalize continuation

## Goal

Make the second guarded finalize stage accept only authenticated R/T lifecycle refs while retaining the sealed C source and index checks.

## Outcome

An implementation C can remain untouched in its original worktree while separately reviewed recovery R and terminal T are prepared in distinct worktrees. The resumed finalizer validates exact R/T authority, accepts only their expected refs and receipted main movement, and completes protected T without accepting unrelated drift.

## Non-goals

No default capsule/RI promotion, blanket ref exclusions, source/index reset, product behavior change, dependency update or CI ruleset mutation.

## Background

#215 reached integrated C, then its second guarded finalize call stopped at `ATTACHED_SOURCE_CHANGED` after C's index and shared refs changed during R/T preparation. Its separately qualified terminal controller completed T. #216 repairs the narrow continuation contract and uses its own Python change for a live guarded closeout proof.

## Authority and precedence

Issue #216, exact revision-7 external authorization, this frozen capsule, Nutrition workflow contract and protected-main ruleset. RI supplies source facts only.

## Dependencies and prerequisites

Exact authorized base above, pinned installed RI runtime, dedicated App qualification and a clean trusted controller. Planning P is a capsule-only direct child of base.

## Owned surface

Candidate evidence matching, guarded finalizer, focused tests, operator/proving docs and this capsule.

## Allowed changes

Bind terminal ref additions to authenticated R/T identities, handle an interrupted T push, preserve strict source/index checks, and document the tested worktree sequence.

## Forbidden changes

Do not weaken attached C source/index or unrelated-ref drift rejection, transfer prior App/review evidence to another SHA, change product/backend/mobile behavior, or promote the opt-in lane.

## Acceptance criteria

- [ ] AC-1: Post-C revalidation accepts only validated R/T ref additions and receipted main movement; C source, branch, index and unrelated refs remain sealed.
- [ ] AC-2: Pre-integration tests exercise second-stage resumption before and after T push with the same C/R/T intent and fresh check revalidation; the protected live run remains issue closeout proof after C integration.
- [ ] AC-3: Focused tests exercise expected C/T movement and hostile extra/wrong refs or index drift; docs give the separate-worktree sequence and preserve #215's failure record.
- [ ] AC-4: Frozen focused and repository commands and dedicated C App qualification pass; RI changed-path artifacts and complete controller dispositions are available for independent exact-C review. The reviewer's decision is the output of this stage.

## Required verification

```nutrition-evidence-v1
[
  {"id":"focused","kind":"focused","required":true,"argv":["{python}","-m","pytest","-q","scripts/tests/test_candidate_evidence.py","scripts/tests/test_task_closeout.py"]},
  {"id":"baseline","kind":"baseline","required":true,"argv":["./scripts/run-review.sh","--profile","repository","--no-package"]}
]
```

```nutrition-ri-v1
{"schema_version":1,"scope":"changed-files-v1"}
```

### Focused

Frozen candidate-evidence and terminal-closeout tests, plus exact source inspection.

### Baseline

Repository review, capsule validation and whitespace checks.

### Specialized qualification

At C: dedicated App repository profile. After C integration and approved C review: distinct repository profile for T. The T check cannot exist in the candidate packet and is required for final issue closeout, not for this candidate review.

## Return evidence

For independent C review: exact B/P/C, frozen commands, RI dispositions and C App check. After C integration and an approving C review, final issue closeout additionally requires R/T, T App check, independent T review, live two-stage finalize and protected main/HISTORY/issue observations. The independent C reviewer must request RI artifacts by declared keys `raw`, `comparison`, `membership`, `candidate-source-manifest` and `planning-source-manifest`, not by their filename suffixes; these are available through `nutrition_read_evidence` with check `$structural`.

## Escalation conditions

Moved base, changed issue authority, incomplete RI/command/reviewer evidence, changed C source/index, unexpected refs, failed App checks or ambiguous integration stops and preserves evidence.

## Decisions and assumptions

Use distinct R/T worktrees and leave the attached C checkout untouched. Combined capsule/RI remains opt-in; a successful repair does not decide #187 promotion.

## State history

| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| 2026-09-27 | — | DRAFT | controller | Scoped #216 and diagnosed #215. |
| 2026-09-27 | DRAFT | GRILLED | controller | Source/index/ref drift and interrupted T push examined. |
| 2026-09-27 | GRILLED | SPECIFIED | controller | Four bounded candidate criteria and frozen evidence selected. |
| 2026-09-27 | SPECIFIED | DECOMPOSED | controller | Evidence matcher, finalizer, tests and docs. |
| 2026-09-27 | DECOMPOSED | READY | controller | Exact revision-7 authorization and capsule-only planning overlay. |

## Completion record

- **Reviewed commit:**
- **Merged commit:**
- **Review disposition:**
- **Verification summary:**
- **Specialized qualification:**
- **Known warnings:**
- **Deferred work/follow-up IDs:** #187
- **Retrospective required:** yes — parent proving record.
