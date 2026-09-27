+++
schema_version = 1
capsule_revision = 3
id = "GH-220-expo-holds"
title = "Correct Expo holds and bound dependency retry failures"
state = "READY"
task_type = "tooling"
risk = "high"
created = "2026-09-27"
updated = "2026-09-27"
source_issue = "https://github.com/MitCaine/Nutrition-App/issues/220"
base_commit = "519a543b632d9e1619ee08b8cc3fb36633f311d4"
branch = "task/GH-220-expo-holds-r3"
controller = "Codex Nutrition controller"
executor = "Codex bounded implementor"
reviewer = "Fresh independent exact-candidate reviewer"
delegation = "none"
delegation_constraints = []
blocked = false
blocked_reason = ""
blocked_since = ""
dependencies = ["GH-219-update-transaction"]
planning_artifacts = ["AGENTS.md", "engineering/workflow/START_HERE.md", "scripts/update_dependencies.py", "scripts/tests/test_update_dependencies.py"]
owned_paths = ["scripts/update_dependencies.py", "scripts/tests/test_update_dependencies.py", "engineering/capsules/active/GH-220-expo-holds.md"]
allowed_paths = []
forbidden_paths = []
specialized_qualification = ["profile:repository", "profile:mobile", "evidence:focused", "evidence:baseline"]
+++

# GH-220-expo-holds — Safe Expo holds and bounded retry

## Goal

Keep Expo-held dependency versions fixed while allowing other updates, and avoid per-package retry cascades for shared failures.

## Outcome

An all-held set runs no bare npm update. Any held package remains unchanged in every lock-entry field in the proposed lock after transitive resolution. Informational latest-version reporting cannot invalidate a separately validated proposal. Only a classified dependency conflict narrows to individual packages.

## Non-goals

No manifest/range, Expo policy, risk-register, major-version, protected-main, or native-code changes.

## Background

Issue #220 and the supplied audit reproduce bare npm update after an empty filtered set and cascade after informational or shared failures.

## Authority and precedence

Issue #220, trusted authorization comment 5860134971, this capsule, repository toolchain/qualification policy and current dependency declarations. RI supplies evidence only.

## Dependencies and prerequisites

Exact integrated #219 base, selected Python/Node toolchains, disposable resolver tests and dedicated repository/mobile qualification.

## Owned surface

Updater resolver/failure classification, focused tests and capsule lifecycle only.

## Allowed changes

Authorized source, test and capsule paths only.

## Forbidden changes

No lockfile/manifest publication in this candidate, silent hold relaxation, arbitrary dirty-checkout allowance or skipped compatibility check.

## Acceptance criteria

- [ ] AC-1: All Expo-managed packages held means no second npm update; retained lock is installed and Expo-checked. With remaining packages, npm update names only those packages.
- [ ] AC-2: A held direct or transitively moved package cannot change in the proposed lock, including through a nonheld update.
- [ ] AC-3: Informational npm outdated failures warn without losing a validated proposal; only a recognized dependency conflict triggers bounded direct-package retries, and shared infrastructure or contract/input failure does not cascade. Independent areas continue.
- [ ] AC-4: Focused tests and repository/mobile qualification pass with Expo, risk, major-version and protected-main checks intact; RI dispositions cover every changed path for subsequent independent full-diff review.

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

Use disposable lockfile fixtures with realistic bare npm update behavior, all/some held sets, indirect held movement, reporting failure and conflict versus infrastructure failures.

### Baseline

Run repository session-end checks.

### Specialized qualification

Dedicated App repository and mobile profiles. No native source changes.

## Return evidence

Return exact B/P/C, frozen commands, App checks, RI path dispositions, and independent AC/path review. Read structural raw evidence using `nutrition_read_evidence` with `check: "$structural"` and declared artifact names such as `raw` and `comparison`.

## Escalation conditions

Unclassified resolver failure, changed authority inputs, held version drift, Expo/risk/major violation, incomplete RI coverage or independent review failure.

## Decisions and assumptions

Resolver errors default to no retry; recognized conflicts alone justify per-package narrowing. Informational reporting is not a publication guard.

## State history

| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| 2026-09-27 | — | DRAFT | controller | Audit F3 verified in current source. |
| 2026-09-27 | DRAFT | GRILLED | controller | All-held and shared-failure retry boundaries examined. |
| 2026-09-27 | GRILLED | SPECIFIED | controller | Four candidate-reviewable criteria and focused tests selected. |
| 2026-09-27 | SPECIFIED | DECOMPOSED | controller | Source, tests and capsule bounded; adjacent issues separate. |
| 2026-09-27 | DECOMPOSED | READY | controller | Revision-three owner authorization comment 5860134971 follows the preserved revision-one review and revision-two invalid capsule-history baseline; full held-entry equality remains required. |

Candidate review and terminal closeout occur after this implementation commit. Pending completion fields are lifecycle markers, not claims of missing candidate checks or RI evidence.

## Completion record

- **Reviewed commit:** Pending.
- **Merged commit:** Pending.
- **Review disposition:** Pending.
- **Verification summary:** Pending.
- **Specialized qualification:** Pending dedicated App repository/mobile check.
- **Known warnings:** Isolated audit probes are narrower than live registry behavior.
- **Deferred work/follow-up IDs:** #221, #222.
- **Retrospective required:** yes — record the update failure classification used in practice.
