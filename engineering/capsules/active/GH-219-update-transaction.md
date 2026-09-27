+++
schema_version = 1
capsule_revision = 5
id = "GH-219-update-transaction"
title = "Resume partial dependency updates and bind publication to checkout identity"
state = "IMPLEMENTED"
task_type = "tooling"
risk = "high"
created = "2026-09-27"
updated = "2026-09-27"
source_issue = "https://github.com/MitCaine/Nutrition-App/issues/219"
base_commit = "a5cba4331306d9dac8b3b33a5d9ea276540ee5f6"
branch = "task/GH-219-update-transaction-r5"
controller = "Codex Nutrition controller"
executor = "Codex bounded implementor"
reviewer = "Fresh independent exact-candidate reviewer"
delegation = "none"
delegation_constraints = []
blocked = false
blocked_reason = ""
blocked_since = ""
dependencies = []
planning_artifacts = ["AGENTS.md", "engineering/workflow/START_HERE.md", "docs/project/development-guide.md", "scripts/README.md"]
owned_paths = ["scripts/update_dependencies.py", "scripts/lib/update_transaction.py", "scripts/dependency-modules/dependencies.zsh", "scripts/tests/test_update_dependencies.py", "scripts/tests/test_update_transaction.py", "scripts/tests/test_start_work.py", "docs/project/development-guide.md", "scripts/README.md", "engineering/capsules/active/GH-219-update-transaction.md"]
allowed_paths = []
forbidden_paths = []
specialized_qualification = ["profile:repository", "evidence:focused", "evidence:baseline"]
+++

# GH-219-update-transaction — Resumable dependency updates

## Goal

Make partial dependency updates safely resumable and refuse publication into a changed checkout identity.

## Outcome

The updater records a durable per-checkout transaction, resumes only its exact retained output, and independently continues pending areas. Starting branch, HEAD and worktree identity remain fixed through publication.

## Non-goals

No automatic commit, reset or discard; no arbitrary dirty-checkout allowance, version-policy change, RI source-pin advance, qualification bypass or product change.

## Background

Issue #219 and the owner's audit identify the combined clean-start/partial-retention failure and branch-switch publication gap. The supplied isolated probes establish narrow preconditions, not a full live update.

## Authority and precedence

Issue #219, external revision-one authorization, this capsule, repository toolchain/qualification policy and current dependency declarations. RI supplies source evidence only.

## Dependencies and prerequisites

Clean exact base, selected Python/Node lines, scratch resolver isolation, a safe external transaction location, focused disposable Git tests, and dedicated App repository qualification.

## Owned surface

Updater transaction and publication seam, start-work wrapper, focused tests and command docs.

## Allowed changes

Only the authorized paths above; lifecycle-only capsule changes after READY.

## Forbidden changes

No manifest/range/lock changes, branch protection change, credential storage, product file change, or silent compatibility weakening.

## Acceptance criteria

- [ ] AC-1: A clean apply can retain backend output after mobile failure, then resume mobile on the same checkout while preserving backend; pending outcomes are durable across invocations.
- [ ] AC-2: Resume rejects an intervening user edit, changed transaction output, authority input, worktree, branch or HEAD; publication rechecks identity after resolution.
- [ ] AC-3: Startup attempts safe resume for transaction-owned dirt and reports unrelated dirt clearly; preview is never described as applied completion. Existing selected/all commands and independent-area continuation remain available.
- [ ] AC-4: Focused integration tests and repository baseline pass; RI dispositions cover all changed paths, including unsupported shell/Markdown, for independent full-diff review. Terminal recovery and review remain later gates.

## Required verification

```nutrition-evidence-v1
[
  {"id":"focused","kind":"focused","required":true,"argv":["{python}","-m","pytest","-q","scripts/tests/test_update_dependencies.py","scripts/tests/test_update_transaction.py","-p","no:cacheprovider"]},
  {"id":"baseline","kind":"baseline","required":true,"argv":["./scripts/session-end.sh"]}
]
```

```nutrition-ri-v1
{"schema_version":1,"scope":"changed-files-v1"}
```

### Focused

Use disposable real Git repositories for continuous partial failure/resume, altered output/user edit and branch/HEAD switch during publication. Test interrupted transaction state and wrapper behavior.

### Baseline

Run repository session-end checks.

### Specialized qualification

Dedicated App repository profile. No product dependency lock or native path is changed.

## Return evidence

Return exact B/P/C, frozen command results, App check, RI path dispositions, independent AC/path review using `nutrition_read_evidence` with `check: "$structural"` and declared artifact names such as `raw` and `comparison`, and later R/T closeout. Preserve failed and interrupted transaction state as evidence without treating it as approval.

## Escalation conditions

Source/branch/HEAD drift, arbitrary dirt, partial publication without exact recovery bytes, changed issue authority, failed tests, incomplete RI coverage or review stops without discarding evidence.

## Decisions and assumptions

The transaction state is external to the repository checkout and does not contain credentials. The updater lock serializes updater invocations, while identity checks detect other Git operations.

## State history

| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| 2026-09-27 | — | DRAFT | controller | Audit findings F1/F4 verified in current source. |
| 2026-09-27 | DRAFT | GRILLED | controller | Exact-output resume and branch/HEAD drift boundaries examined. |
| 2026-09-27 | GRILLED | SPECIFIED | controller | Four candidate-reviewable criteria and real-Git tests selected. |
| 2026-09-27 | SPECIFIED | DECOMPOSED | controller | Updater state, wrapper and docs bounded; other audit findings separate. |
| 2026-09-27 | DECOMPOSED | READY | controller | Revision-five authorization comment 5859907955 retains scope after failed prior review and planning attempts; evidence attachment proceeds directly from this capsule-only planning overlay. |
| 2026-09-27 | READY | IN_PROGRESS | Codex controller | Preserved implementation transferred onto exact revision-five planning overlay. |
| 2026-09-27 | IN_PROGRESS | IMPLEMENTED | Codex controller | Durable updater transaction, startup behavior, documentation and focused tests committed for fresh evidence gates. |

## Completion record

- **Reviewed commit:** Pending.
- **Merged commit:** Pending.
- **Review disposition:** Pending.
- **Verification summary:** Pending.
- **Specialized qualification:** Pending dedicated App repository check.
- **Known warnings:** Audit probes are narrow and not live qualification.
- **Deferred work/follow-up IDs:** #220, #221, #222.
- **Retrospective required:** yes — document actual interrupted-run behavior.
