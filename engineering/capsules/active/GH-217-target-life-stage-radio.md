+++
schema_version = 1
capsule_revision = 3
id = "GH-217-target-life-stage-radio"
title = "Make optional target life-stage selection use consistent radio semantics"
state = "IMPLEMENTED"
task_type = "product"
risk = "medium"
created = "2026-09-27"
updated = "2026-09-27"
source_issue = "https://github.com/MitCaine/Nutrition-App/issues/217"
base_commit = "ce8d044aa548f6b211ca1beb9255f53331600d1e"
branch = "task/GH-217-target-life-stage-radio-r3"
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
owned_paths = ["apps/mobile/src/features/targets/TargetSettingsScreen.tsx", "apps/mobile/__tests__/targetSettingsScreen.test.ts", "engineering/capsules/active/GH-217-target-life-stage-radio.md"]
allowed_paths = []
forbidden_paths = []
specialized_qualification = ["profile:repository", "profile:mobile", "evidence:focused", "evidence:baseline"]
+++

# GH-217-target-life-stage-radio — Consistent life-stage radio semantics

## Goal

Make the optional female target life-stage controls convey and implement the same single-selection contract.

## Outcome

The female-only group has visible None, Pregnant and Lactating radios. Exactly one is checked; pressing the selected choice is idempotent. Existing context values and save behavior remain intact.

## Non-goals

No backend/schema change, nutrition calculation change, unrelated screen redesign, native module change or default workflow promotion.

## Background

At base, Pregnant/Lactating are radios but pressing the selected option resets to a hidden `general_adult` state. The issue body specifies the resulting accessibility discrepancy and bounded correction.

## Authority and precedence

Issue #217, exact external revision-one authorization, this qualified capsule, current Nutrition domain/accessibility tests, and the trusted controller workflow. RI supplies source facts, not edit authority.

## Dependencies and prerequisites

Exact authorized base, pinned installed RI runtime, offline mobile npm cache and qualified Node host, dedicated App qualification, clean trusted controller, and separate candidate checkout.

## Owned surface

TargetSettingsScreen and its focused renderer test, plus this capsule's lifecycle.

## Allowed changes

Only the three authorized paths above, with lifecycle-only capsule transitions after READY.

## Forbidden changes

Do not alter domain values, API payload shape, backend, calculations, other screens, dependency manifests/locks, native code or repository workflow policy.

## Acceptance criteria

- [ ] AC-1: Female-only optional-condition group exposes exactly three radios and exactly one checked state for each supported context, including `general_adult`.
- [ ] AC-2: Reactivating the selected radio is idempotent; switching among None, Pregnant and Lactating updates checked states and saved context.
- [ ] AC-3: Changing equation sex to male still forces `general_adult`, removes the female-only group and preserves existing save payload behavior.
- [ ] AC-4: Frozen focused and repository/mobile commands, exact-C App qualification, and RI changed-path artifacts/controller dispositions are available for independent review. The reviewer's decision is the output of this stage; approval is required for later integration, not assumed in the candidate packet. Native profile remains subject to path triggers.

## Required verification

```nutrition-evidence-v1
[
  {"id":"focused","kind":"focused","required":true,"prepare":"mobile-npm-ci-offline-v1","argv":["npm","--prefix","apps/mobile","test","--","--runInBand","targetSettingsScreen.test.ts"]},
  {"id":"baseline","kind":"baseline","required":true,"prepare":"mobile-npm-ci-offline-v1","argv":["./scripts/run-review.sh","--profile","repository","--profile","mobile","--no-package"]}
]
```

```nutrition-ri-v1
{"schema_version":1,"scope":"changed-files-v1"}
```

### Focused

Frozen target-settings renderer test, including accessibility roles/check states and save payload transitions.

### Baseline

Frozen repository/mobile review bundle, typecheck and full Jest baseline.

### Specialized qualification

Dedicated App repository/mobile profiles; no native change is planned. Run native qualification if actual changed paths trigger it.

## Return evidence

For independent C review, request command artifacts with the declared `check` IDs `focused` or `baseline` and an exact artifact key listed under that command's `artifacts` map (for example `stdout.log`, or a baseline `bundle/runs/.../results.json` key). The check ID itself is never an artifact name. Request RI artifacts with `check: "$structural"` and the declared keys `raw`, `comparison`, `membership`, `candidate-source-manifest`, and `planning-source-manifest` as needed; do not guess filename suffixes or use `check: "structural"`. The independent reviewer assesses AC-1..AC-4 and every changed path against source, full diff, declared evidence and scope; controller expected labels are claims, not approval. The IMPLEMENTED capsule's Completion record is populated only after review in the separately recoverable R lifecycle, so blank review/merge fields at C are not missing candidate evidence. Preserve revision-one reviewer STOP_REPLAN and revision-two unsupported-model transport STOP_REPLAN; no verdict or check transfers to C3.

Return exact B/P/C, command and App outcomes, RI changed-path dispositions, independent exact-C review, failed-attempt history, human-active timing if supplied by owner, and separate R/T closeout evidence. Missing human timing is marked missing rather than inferred.

## Escalation conditions

Changed issue authority/base/scope, conflicting domain behavior, unavailable offline npm/RI, failed check, incomplete review, unexpected native trigger or unrelated drift stops and preserves evidence.

## Decisions and assumptions

#187 declared this opt-in lane before implementation. This trial does not authorize default promotion. The `None` label represents existing `general_adult` without changing its storage value.

## State history

| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| 2026-09-27 | — | DRAFT | controller | Bounded #217 product defect confirmed in source and issue. |
| 2026-09-27 | DRAFT | GRILLED | controller | Hidden third radio value, idempotence, male transition and payload boundaries examined. |
| 2026-09-27 | GRILLED | SPECIFIED | controller | Four observable criteria and frozen mobile evidence selected. |
| 2026-09-27 | SPECIFIED | DECOMPOSED | controller | Two product/test paths plus capsule lifecycle; no backend or native change. |
| 2026-09-27 | DECOMPOSED | READY | controller | Revision-three external authorization comment 5859199198, exact base and capsule-only planning overlay; earlier reviewer and transport STOP_REPLAN attempts are preserved outside this candidate. |
| 2026-09-27 | READY | IN_PROGRESS | Codex controller | Qualified revision-three P and generated bounded handoff; reapplying only the accepted product bytes. |
| 2026-09-27 | IN_PROGRESS | IMPLEMENTED | Codex controller | Bounded product/test change committed; revision-three exact-C checks and review remain pending. |

## Completion record

- **Reviewed commit:**
- **Merged commit:**
- **Review disposition:**
- **Verification summary:**
- **Specialized qualification:**
- **Known warnings:**
- **Deferred work/follow-up IDs:** #187
- **Retrospective required:** yes — measured #187 proving record.
