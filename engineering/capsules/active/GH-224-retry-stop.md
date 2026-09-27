+++
schema_version = 1
capsule_revision = 1
id = "GH-224-retry-stop"
title = "Stop direct dependency retry on shared failures after narrowing begins"
state = "READY"
task_type = "tooling"
risk = "medium"
created = "2026-09-27"
updated = "2026-09-27"
source_issue = "https://github.com/MitCaine/Nutrition-App/issues/224"
base_commit = "78b4d2c78062b04e34466bb3fdd0c9094a2661a7"
branch = "task/GH-224-retry-stop"
controller = "Codex Nutrition controller"
executor = "Codex bounded implementor"
reviewer = "Fresh independent exact-candidate reviewer"
delegation = "none"
delegation_constraints = []
blocked = false
blocked_reason = ""
blocked_since = ""
dependencies = ["GH-223-review-drain"]
planning_artifacts = ["AGENTS.md", "scripts/update_dependencies.py", "scripts/tests/test_update_dependencies.py", "scripts/README.md"]
owned_paths = ["scripts/update_dependencies.py", "scripts/tests/test_update_dependencies.py", "scripts/README.md", "engineering/capsules/active/GH-224-retry-stop.md"]
allowed_paths = []
forbidden_paths = []
specialized_qualification = ["profile:repository", "evidence:focused", "evidence:baseline"]
+++

# GH-224-retry-stop — Stop shared failure cascade

## Goal

After a bulk resolver conflict, stop direct-package narrowing on a shared infrastructure or input failure.

## Outcome

A direct package-local resolver conflict is recorded and narrowing can continue. Other errors stop remaining direct attempts while retaining validated prior proposals and allowing independent update areas to proceed.

## Non-goals

No version-range policy change, lost validated proposal, broad retry expansion, or unrelated package mutation.

## Background

Issue #224 records the remaining #220 gap: the direct retry loop currently catches the common error base and can fan out across all packages after an outage.

## Authority and precedence

Issue #224, trusted owner authorization, this capsule and repository controller policy. RI is navigation evidence only.

## Dependencies and prerequisites

Integrated #223 base and disposable dependency-update fixtures.

## Owned surface

Direct-package retry classifier, focused tests and updater command documentation.

## Allowed changes

Authorized updater, test, documentation and capsule paths only.

## Forbidden changes

No product source, direct lock edits, package-manager policy change or transaction bypass.

## Acceptance criteria

- [ ] AC-1: Bulk ResolutionConflict followed by direct shared failure stops before any second direct package attempt.
- [ ] AC-2: Package-local ResolutionConflict still permits bounded narrowing; already validated proposals survive a later shared failure.
- [ ] AC-3: Independent update areas still proceed, and the transaction records partial success and failure correctly.
- [ ] AC-4: Focused updater regression tests and repository baseline pass.

## Required verification

```nutrition-evidence-v1
[
  {"id":"focused","kind":"focused","required":true,"argv":["{python}","-m","pytest","-q","scripts/tests/test_update_dependencies.py","-p","no:cacheprovider"]},
  {"id":"baseline","kind":"baseline","required":true,"argv":["./scripts/session-end.sh"]}
]
```

```nutrition-ri-v1
{"schema_version":1,"scope":"changed-files-v1"}
```

### Focused

Inject a bulk conflict, one validated direct proposal, then ECONNRESET; assert no next package attempt, partial state retained and independent area proceeds.

### Baseline

Run repository session-end checks and capsule validation.

### Specialized qualification

Dedicated App repository profile.

## Return evidence

Return exact B/P/C, frozen checks, App check, RI controller dispositions and independent review. Controller disposition rows are in `evidence.structural.controller_disposition.paths`, separately from reviewer path verdicts.

## Escalation conditions

Shared failure incorrectly retried, validated proposal lost, later area blocked, or transaction state unbound.

## Decisions and assumptions

ResolutionConflict is the only retryable package-local error type. Other errors stop narrowing but do not erase already validated proposals.

## State history

| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| 2026-09-27 | — | DRAFT | controller | Re-audit #224. |
| 2026-09-27 | DRAFT | GRILLED | controller | Differentiated package-local conflict from shared failure. |
| 2026-09-27 | GRILLED | SPECIFIED | controller | Four acceptance criteria and partial proposal fixture. |
| 2026-09-27 | SPECIFIED | DECOMPOSED | controller | Retry loop and tests bounded. |
| 2026-09-27 | DECOMPOSED | READY | controller | Owner authorization posted. |

## Completion record

- **Reviewed commit:** Pending.
- **Merged commit:** Pending.
- **Review disposition:** Pending.
- **Verification summary:** Pending.
- **Specialized qualification:** Pending dedicated App repository check.
- **Known warnings:** None.
- **Deferred work/follow-up IDs:** #225, #226.
- **Retrospective required:** yes — record stopped cascade behavior.
