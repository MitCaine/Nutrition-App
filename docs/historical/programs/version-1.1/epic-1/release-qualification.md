# Version 1.1 Epic 1 — End-to-End Release Qualification

## Decision

Epic 1 satisfies the automated and prerequisite evidence required by GitHub Issue
[E1-18](https://github.com/MitCaine/Nutrition-App/issues/22). No architecture-gate breach, new API
design, migration, or product-scope expansion was required.

This record qualifies the repository state based on `efb24f536e0a` plus the bounded test-lifecycle
correction described below. It is not a commit record; E1-18 explicitly left commit and push to the
owner.

## Authority and prerequisites

The qualification was evaluated against, in order:

1. [Feature PRD](feature-prd.md)
2. [Architecture Review](architecture-review.md)
3. [GitHub Issue E1-18](https://github.com/MitCaine/Nutrition-App/issues/22)
4. [Grill Record](grill.md)
5. [Implementation Backlog](implementation-backlog.md)

The following completed prerequisites were accepted from the owner-provided E1-18 baseline and
were not repeated or reimplemented here:

- E1-17 accessibility qualification is complete and verified, including the established
  physical-device workflow.
- The isolated Phase 5C conversion-clone workflow has traversed the real migration chain to
  `0024_recipe_log_current_provenance`.

E1-18 did not modify either prerequisite workflow or any Phase 5C migration, guard, role, fence,
control-plane, or bootstrap contract.

## Qualification defect and correction

The first integrated review found one failure after all 625 mobile assertions had passed:
`foodLogHandoff.integration.test.ts` retained mounted React test renderers, allowing a scheduled
accessibility focus request to reach React Native after Jest teardown.

Production focus requests were already cancellable, and the affected screen effects already
returned their cancellation callbacks. The integration harness now unmounts every renderer after
each test, exercising those real lifecycle callbacks. The correction does not suppress timers,
change focus timing, or weaken accessibility behavior.

The focused regression command then passed with 15 tests and no post-teardown exception:

```bash
cd apps/mobile
npm test -- --runInBand __tests__/foodLogHandoff.integration.test.ts
```

## Integrated automated result

The final authoritative command was:

```bash
NUTRITION_REVIEW_OUTPUT_DIR=/private/tmp/nutrition-app-e1-18-review-final \
  ./scripts/run-review.sh --profile cross-cutting --no-package --label e1-18-final
```

Results:

| Gate | Result |
| --- | --- |
| Backend Ruff | Passed |
| Backend compile | Passed |
| Backend pytest | 1,849 passed, 18 explicitly opt-in skips, 3 warnings |
| Mobile TypeScript | Passed |
| Mobile Expo configuration | Passed |
| Mobile Jest | 87 suites, 625 tests passed; process exited successfully |
| Documentation links | 74 files and 521 local links passed |
| Shell syntax | Passed |
| Docker Compose configuration | Passed |
| Git whitespace and repository drift | Passed |
| Repository session closeout | Passed; one existing phase-boundary warning |

The 18 backend skips were confined to the explicitly opt-in Issue-17 container workflow, real
MinIO/infrastructure integration, managed-role qualification, and full T0 performance scenario.
They are not reported as passes. The PostgreSQL log-concurrency, migration replay, immutable
provenance, historical bridge, resource-membership migration, recovery, and control qualification
tests selected by the ordinary backend run all executed successfully.

## Feature PRD success-criteria traceability

| Criterion | Release evidence |
| --- | --- |
| 1. Trustworthy date-only Daily Log | Backend authoritative-time-zone and target tests; mobile calendar model/settings, Daily Log, section-read-state, target-progress, and cache-isolation tests cover DST, midnight, stale/failure states, and cross-date retirement. |
| 2. Every acquisition source reaches explicit confirmation | Mobile Add Food navigator, search-mode, food-detail handoff, USDA import, Custom Food, Scan Label, and Log Food submission integrations converge on the shared confirmation. Platform gating keeps OCR absent on Android. |
| 3. Date, meal, source, and fields remain authoritative | Backend log contracts, source preconditions, calendar revision, idempotency, and PostgreSQL concurrency tests combine with mobile handoff, form, cancellation, and source-review tests. |
| 4. Repeat uses one eligible event without stale copies | Backend Recent Entries tests and mobile Add Food/Log Food integrations cover ordering, eligibility, current-source resolution, blank notes, explicit Copy notes, unsupported meals, and unavailable amounts. |
| 5. Edit, move, and permanent delete preserve history | Backend E1-13 editing, mutation replay, transaction rollback, immutable provenance, Recipe revision, deletion, and ownership suites cover metadata preservation, snapshot replacement, fixed source identity, moves, and permanent deletion. Mobile edit/delete flows cover confirmation and post-commit projection. |
| 6. Future mutation boundary and legacy cleanup | Backend authoritative-calendar and E1-15 cleanup tests cover future rejection, restricted moves, delete, owner isolation, and membership removal. Mobile legacy cleanup/move tests cover the bounded presentation and allowed actions. |
| 7. Independent reads and distinguishable mutation outcomes | Mobile section-read-state, mutation-projection, retry, recovery, and Daily Log tests cover partial failures and confirmed projections. Backend replay, status, rollback, precondition, and PostgreSQL race tests distinguish confirmed, non-commit, stale/conflict, and unresolved outcomes. |
| 8. One authoritative calendar across clients | Backend owner-scoped calendar, DST, stale-preview, rollover, active-context, and concurrent-client tests cover one shared zone and revision. Mobile settings-change and calendar API/model tests cover explicit review and retained workflow context. |
| 9. Equivalent accessible workflows | Completed E1-17 manual qualification is the authoritative device prerequisite. The full mobile suite additionally passed shared accessibility primitives, focus, announcements, modals, forms, Dynamic Type, recovery, destructive actions, iOS Scan Label, and Android platform-gating tests. |

## Architecture and scope audit

- Daily Log snapshot and Recipe publication immutability remain enforced by database, service, and
  PostgreSQL concurrency tests.
- Server-side ownership and cross-owner denial remain enforced.
- OCR correction provenance and immutable trace behavior remain unchanged.
- Confirmed versus uncertain mutation state remains explicit and replay-safe.
- Compatibility behavior remains limited to legacy future dates, unsupported meals, and overlength
  notes.
- No meal planning, scheduling, custom meals, inferred meals, consumption times, per-meal analytics,
  offline mutation queue, durable draft, bulk/Duplicate workflow, source replacement during Edit,
  undo/deleted-entry recovery, automatic historical recalculation, Android OCR, collaborative merge,
  rich text, attachments, analytics instrumentation, public behavior, or architectural rewrite was
  introduced.
- No elapsed-time or tap-count gate was added. Faster logging remains evidenced by direct handoffs,
  retained transient context, shared confirmation, and immediate confirmed projections.

## Residual warnings and manual work

The automated run reported two established warning families:

- Starlette's deprecated `HTTP_422_UNPROCESSABLE_ENTITY` alias in two tests.
- SQLAlchemy's warning that its metadata sorter cannot fully order the intentional cyclic Recipe
  relationship graph during the historical `0019` comparison.

Neither warning changed test results or E1-18 behavior. Native/device accessibility evidence was
accepted from completed E1-17 and was not regenerated. Because the only E1-18 source correction is
test-harness cleanup, no additional product-device scenario is required before owner review.
