+++
schema_version = 1
capsule_revision = 1
id = "GH-215-saved-usda-accessibility"
title = "Align Saved Foods USDA result accessibility and importability"
state = "IN_PROGRESS"
task_type = "implementation"
risk = "medium"
created = "2026-09-27"
updated = "2026-09-27"
source_issue = "https://github.com/MitCaine/Nutrition-App/issues/215"
base_commit = "90d2f45fb02319013515479bb8b5c9ce149622a4"
branch = "task/GH-215-saved-usda-accessibility"
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
owned_paths = ["apps/mobile/src/features/foods/screens/SavedFoodsScreen.tsx", "apps/mobile/__tests__/foodDiscovery.test.ts", "engineering/capsules/active/GH-215-saved-usda-accessibility.md"]
allowed_paths = []
forbidden_paths = []
specialized_qualification = ["profile:repository", "profile:mobile", "evidence:focused", "evidence:baseline"]
+++

# GH-215-saved-usda-accessibility — Align Saved Foods USDA result accessibility and importability

## Goal

Make USDA reference rows in unified Saved Foods search expose the same usable identity and importability as the standalone USDA search.

## Outcome

Screen readers announce the result as a button with its USDA name/context, a preview handoff hint and disabled state when it cannot be imported. A non-importable row does not navigate; an importable row does once.

## Non-goals

No persisted Food/Recipe identity change, query ordering change, backend/import mutation, native module change or dependency update.

## Background

The unified Saved Foods screen uses a plain Pressable for USDA results, while standalone USDA search uses a shared accessible label/hint and prevents non-importable preview activation. #187 selects this bounded TSX opt-in combined-workflow proving sample.

## Authority and precedence

Issue #215, its exact external authorization, this frozen capsule, Nutrition workflow contract and protected-main ruleset. RI supplies source facts only.

## Dependencies and prerequisites

Exact authorized base above, pinned RI installation, offline npm cache and qualified Node toolchain. Planning P must be the capsule-only direct child of base.

## Owned surface

Saved Foods screen, its focused discovery renderer test and this capsule.

## Allowed changes

Reuse existing USDA accessibility label/hint behavior and disabled semantics in the unified result row, with focused tests.

## Forbidden changes

Do not modify persisted Food/Recipe identity treatment, visible description/meta/nutrients, search ordering, API contracts, native code, dependency files or controller mechanics.

## Acceptance criteria

- [ ] AC-1: USDA reference rows expose a meaningful button label and handoff hint without FDC IDs; visible identity content remains unchanged.
- [ ] AC-2: Non-importable rows are disabled and cannot open preview; importable rows open it once.
- [ ] AC-3: Focused renderer tests cover both cases and the existing persisted Food/Recipe identity treatment remains intact.
- [ ] AC-4: Exact P-to-C RI changed-path evidence, frozen focused/baseline commands and dedicated repository/mobile qualification pass and receive independent exact-SHA review.

## Required verification

```nutrition-evidence-v1
[
  {"id":"focused","kind":"focused","required":true,"prepare":"mobile-npm-ci-offline-v1","argv":["npm","--prefix","apps/mobile","test","--","--runInBand","foodDiscovery.test.ts"]},
  {"id":"baseline","kind":"baseline","required":true,"prepare":"mobile-npm-ci-offline-v1","argv":["./scripts/run-review.sh","--profile","repository","--profile","mobile","--no-package"]}
]
```

```nutrition-ri-v1
{"schema_version":1,"scope":"changed-files-v1"}
```

### Focused

Frozen food discovery renderer test and exact RI structural/diff review.

### Baseline

Frozen repository/mobile review bundle, mobile typecheck and full Jest baseline.

### Specialized qualification

Dedicated App repository/mobile profiles for C and distinct repository profile for T. These TSX-only paths do not trigger iOS-native; any unexpected native path stops for replan.

## Return evidence

Exact B/P/C/T, focused row semantics/activation result, complete RI path dispositions, frozen commands, App checks, independent review and reachable full-capsule recovery.

## Escalation conditions

Moved authority/main, incomplete RI mapping, failed mandatory npm/check/review, changed scope or unexpected native-affecting path stops and preserves evidence.

## Decisions and assumptions

Use the existing USDA result identity function rather than duplicate labeling logic. Combined capsule/RI remains opt-in pending #187 decision.

## State history

| Date | From | To | Actor | Reason/evidence |
| --- | --- | --- | --- | --- |
| 2026-09-27 | — | DRAFT | controller | Scoped issue #215. |
| 2026-09-27 | DRAFT | GRILLED | controller | Current duplicate USDA surfaces and importability behavior inspected. |
| 2026-09-27 | GRILLED | SPECIFIED | controller | Four observable criteria and frozen mobile evidence chosen. |
| 2026-09-27 | SPECIFIED | DECOMPOSED | controller | One TSX screen and focused test. |
| 2026-09-27 | DECOMPOSED | READY | controller | Exact authorization and capsule-only planning overlay. |
| 2026-09-27 | READY | IN_PROGRESS | Codex controller | External authorization and qualified planning overlay; bounded TSX implementation committed |

## Completion record

- **Reviewed commit:**
- **Merged commit:**
- **Review disposition:**
- **Verification summary:**
- **Specialized qualification:**
- **Known warnings:**
- **Deferred work/follow-up IDs:** #187.
- **Retrospective required:** yes — #187 proving period.
