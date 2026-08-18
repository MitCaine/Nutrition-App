# Version 1.2 Epic 4 — GitHub Implementation Backlog

> **Document role: Implementation Backlog.** This decomposes the approved [Feature PRD](feature-prd.md) and [Data and Runtime Contracts](data-contracts.md) into bounded implementation work. No issue in this backlog authorizes code changes until the planning package passes documentation validation and project audit.

## Backlog status

Architecture review: **Approved subject to repository validation/audit gate.**

Epic 4 scope is frozen. New product ideas discovered during implementation go to the future-product register unless required to satisfy an accepted invariant or acceptance criterion.

Implementation must stop and return to architecture review if a task would require synchronization, mixed application-data authority, historical target reconstruction, weakening immutable Daily Log nutrition, non-atomic Complete invalidation, or an unbounded History/reporting API.

---

# Milestone 1 — Complete-state authority and persistence

## E4-01 — Add date-owned Complete persistence for local and remote authorities

### Purpose

Introduce durable positive day-level Complete state without backfilling or modifying historical nutrition.

### Acceptance criteria

- Complete is persisted as date-owned state, not redundantly on individual Log entries.
- Remote persistence remains owner-scoped.
- Local persistence follows existing local authority ownership conventions.
- At most one active Complete assertion exists per authoritative date.
- Empty dates cannot acquire Complete state.
- Migration performs no historical backfill.
- Existing Daily Log nutrient snapshots are unchanged by the migration.
- Internal persistence retains `completed_at`-equivalent evidence.
- Local schema upgrade and remote migration replay/rollback follow existing repository migration rules.

### Out of scope

- Complete UI.
- Automatic invalidation from Log mutations.
- Manual un-completion.
- History range reads.

### Dependencies

- None.

### Backend/remote work

- Add owner/date-scoped day-completion persistence.
- Add model/repository operations for reading and asserting Complete.
- Add remote migration after the current application head without rewriting existing history.

### Local/mobile runtime work

- Add equivalent local SQLite schema/storage operations.
- Preserve exact date semantics and migration determinism.

### Testing requirements

- Fresh database migration.
- Upgrade with existing Logs.
- No-backfill assertion.
- Duplicate-date uniqueness.
- Empty-date rejection at the service boundary.
- Cross-owner isolation remotely.
- Migration replay/rollback where repository policy requires it.

### Estimated implementation size

L

---

## E4-02 — Make Complete assertion deterministic and mutation-recoverable

### Purpose

Expose a reliable mark-Complete mutation using existing Daily Log mutation/reconciliation semantics.

### Acceptance criteria

- Mark Complete is allowed only for Today/past dates with at least one Log.
- Successful UI state is based on confirmed authoritative persistence.
- Remote indeterminate responses can be reconciled using existing mutation identity/status patterns.
- Same-intent replay cannot create duplicate state.
- Changed-payload/reused-intent conflicts are rejected consistently with existing mutation policy.
- Complete state is unavailable for assertion while a nutrition-changing mutation for the same date remains unresolved in the client workflow.
- No manual clear/un-complete mutation is required for initial Epic 4.

### Dependencies

- E4-01.

### Backend/remote work

- Add authenticated mark-Complete mutation and deterministic reconciliation/status behavior.
- Reuse existing Daily Log mutation receipts/patterns rather than inventing a separate consistency model.

### Local/mobile runtime work

- Add local equivalent mutation operation.
- Add runtime contract/parity fixture.

### Testing requirements

- Local success/failure.
- Remote same-intent replay.
- Indeterminate-response reconciliation.
- Empty-date rejection.
- Future-date rejection.
- Cross-owner isolation.

### Estimated implementation size

M

---

## E4-03 — Atomically invalidate Complete on nutrition-changing Log mutations

### Purpose

Guarantee that a Complete assertion never remains authoritative after the date's logged nutrition changes.

### Acceptance criteria

- Create on a Complete date clears Complete atomically with the Log creation.
- Nutrition-changing edit clears Complete atomically with the edit.
- Delete clears Complete atomically with deletion.
- Move clears Complete for both source and destination dates atomically with the move.
- Deleting the final entry leaves the date empty and not Complete.
- Note-only edits preserve Complete.
- Meal-label-only edits preserve Complete.
- Serving/amount edits that produce an exactly unchanged nutrient snapshot preserve Complete.
- Serving/amount edits that change any stored nutrient snapshot clear Complete.
- Later source Food/Recipe edits do not clear historical Complete.
- Target changes do not clear Complete.
- No successful nutrition mutation may leave Complete stale because a second cleanup write failed.

### Dependencies

- E4-01.
- Existing Daily Log mutation contracts.

### Backend/remote work

- Integrate Complete invalidation into authoritative Log mutation transactions.
- Preserve idempotent/reconciliation behavior.

### Local/mobile runtime work

- Integrate equivalent invalidation into local exclusive mutation transactions.

### Testing requirements

- Create/edit/delete/move matrix.
- Same-snapshot equivalent serving edit.
- Changed-snapshot serving edit.
- Note/meal preservation.
- Source Food/Recipe edit isolation.
- Target change isolation.
- Failure injection proving mutation + invalidation atomicity.

### Estimated implementation size

L

---

# Milestone 2 — Bounded History evidence and shared projections

## E4-04 — Add the bounded Daily Logs History range contract

### Purpose

Provide one authority-scoped read that returns equivalent daily evidence for a 7-day or 30-day History window.

### Acceptance criteria

- `DailyLogsRuntime` gains one bounded range operation; no ninth runtime capability is added.
- Request uses inclusive LocalDate start/end values.
- Requests over 30 calendar dates are rejected.
- Initial History rejects endpoints after yesterday.
- Response contains one record for every date in the requested range, including no-Log dates.
- Response includes all canonical nutrient aggregates needed for overview, Nutrition Details, and focused History.
- Response preserves known, estimated, explicit zero, unknown, and no-Log distinctions.
- Response includes Complete state.
- Response exposes `firstLoggedDate`-equivalent metadata, including `null` when no Logs exist.
- Remote authority uses one bounded HTTP request rather than N per-date requests.
- Local and remote implementations expose equivalent semantics.
- No fallback or mixed-authority construction occurs.

### Dependencies

- E4-01.
- Existing Daily Log daily aggregate behavior.

### Backend/remote work

- Add bounded remote read endpoint/service projection.
- Preserve owner isolation and canonical units/exact values.

### Local/mobile runtime work

- Add direct bounded SQLite range read.
- Extend Daily Logs runtime types/adapters.

### API work

- Add stable request/response contract and error classification for invalid/oversized ranges.

### Testing requirements

- 1, 7, 30, and 31-date requests.
- End-after-yesterday rejection.
- No-history and earliest-history bounds.
- Missing dates within ranges.
- Full canonical nutrient payload parity.
- Local/remote fixture equality.

### Estimated implementation size

L

---

## E4-05 — Implement one shared History calculation/projection layer

### Purpose

Calculate all History statistics from equivalent per-date evidence using one semantic implementation.

### Acceptance criteria

- Complete-day average uses only Complete dates with usable numeric evidence for the selected nutrient.
- Logged-day average uses only logged dates with usable numeric evidence for the selected nutrient.
- Estimated numeric amounts participate while retaining estimated provenance.
- Unknown-only nutrient dates do not enter numeric denominators.
- Explicit zero remains a usable zero value.
- No-Log dates remain gaps and do not enter averages.
- Exact daily values are summed before final display rounding.
- Canonical units remain stable across the range.
- Parent nutrients are not manufactured from incomplete child nutrients.
- Coverage counts, usable-day counts, chart points, gaps, and grouped rows derive from the same evidence.
- Local and remote History produce the same projected result for the parity fixture.

### Dependencies

- E4-04.
- Existing exact-value codecs/contracts.

### Shared/mobile work

- Add shared projection types and pure calculation helpers.
- Reuse canonical nutrient ordering/grouping.
- Keep target/reference context outside historical evidence calculations.

### Testing requirements

- Known/estimated/zero/unknown-only/no-Log matrix.
- One-day denominator.
- Mixed Complete/unconfirmed range.
- Nutrient-specific usable-day counts.
- Exact-decimal/rounding boundaries.
- Parent/child non-derivation.
- Stable-unit tests.

### Estimated implementation size

L

---

## E4-06 — Add History query identity, cache invalidation, and stale-response protection

### Purpose

Make range navigation reliable under local refresh, remote latency, cache reuse, and Log mutations.

### Acceptance criteria

- Range cache identity includes selected authority + exact start/end dates.
- Complete/Logged mode does not create another authoritative range cache entry.
- Range changes retire prior-range analytical content before the new range is presented as loaded.
- Same-range cached values may remain after refresh failure only with compact stale/retry indication.
- Different-range cached values never appear under the requested range label.
- Late responses for superseded requests cannot overwrite the newest range.
- Log/Complete mutations invalidate only cached ranges containing affected dates.
- Move invalidates ranges containing source or destination dates.
- Target changes do not invalidate historical intake evidence.
- Remote failure without valid same-range remote cache shows Retry/error and does not fall back to local authority.

### Dependencies

- E4-04.
- E4-05.

### Frontend/runtime work

- Add React Query keys and overlap invalidation helpers.
- Add latest-request-wins/identity checks as required by the navigation stack.
- Add exact-range stale/retry presentation state.

### Testing requirements

- Rapid multi-page navigation with out-of-order responses.
- Same-range refresh failure with cache.
- Different-range failure.
- Authority switching/configuration isolation.
- Overlap-specific invalidation.
- Target-only refresh behavior.

### Estimated implementation size

M

---

# Milestone 3 — Logging-first Daily Log and Daily Nutrition

## E4-07 — Reorder Daily Log around logging and add Complete control

### Purpose

Restore the Daily Log as the fastest place to log meals while exposing History and Complete without adding another tab.

### Acceptance criteria

- Sticky header contains labeled Complete control plus Settings.
- Complete is disabled/unavailable for empty dates and while relevant nutrition mutation is unresolved.
- Checked state appears only after authoritative success.
- Failed assertion remains unchecked with compact retry/error behavior.
- Date navigation shows Previous Day, centered History, and Next Day.
- Compact nutrition summary contains fixed Calories, Protein, Carbohydrate, and Fat only.
- Summary uses consumed/target where meaningful and consumed-only for amount-only state.
- Summary does not use progress bars or percentages.
- `View Nutrition` sits with the compact summary.
- Meal sections and Add Food actions appear before the full nutrient catalog.
- Existing full Target Progress/Totals blocks no longer bury meal logging.
- Empty Daily Log may show `0 logged` for the compact four without changing History's no-Log semantics.

### Dependencies

- E4-02.
- E4-03.

### Frontend work

- Extend sticky header action area in a bounded way.
- Add Complete read/mutation state.
- Reorder Daily Log content.
- Add centered History navigation.
- Add compact four-row nutrition component.

### Testing requirements

- Empty/non-empty date Complete availability.
- Authoritative success/failure UI state.
- Unresolved mutation gating.
- Date navigation and selected-date preservation.
- Logging-first ordering regression tests.

### Estimated implementation size

L

---

## E4-08 — Consolidate Daily Nutrition into one exhaustive one-day surface

### Purpose

Replace overlapping Target Progress and Totals blocks with one deliberate one-day analysis route.

### Acceptance criteria

- Daily Nutrition is opened from `View Nutrition` for the selected Daily Log date.
- Selected date is visible and inherited from Daily Log.
- Back returns to the same Daily Log date.
- No separate Previous/Next Day controls are added.
- Canonical nutrient grouping/hierarchy is preserved.
- Sections start expanded and are collapsible.
- Collapse state persists during the navigation/session context and resets on fresh launch.
- Recommended/custom target rows show consumed/target and percentage where useful.
- Limits remain direction-aware without success/failure framing.
- Amount-only rows show amount only.
- Ignored nutrients are omitted.
- Unknown contributors do not produce routine warning/count suffixes.
- Fully unavailable nutrient rows use neutral `—`.
- `Nutrition targets` becomes a secondary action on this surface rather than the primary Daily Log.

### Dependencies

- E4-07.
- Existing Target/nutrient formatting contracts.

### Frontend work

- Add route/screen and shared nutrient-row presentation.
- Retire duplicate full-catalog Daily Log blocks.
- Preserve existing target authority labels/semantics.

### Testing requirements

- Target directions/modes.
- Ignored/amount-only/unavailable states.
- Unknown contributors remain quiet without semantic loss.
- Date/back state.
- Section state behavior.

### Estimated implementation size

L

---

# Milestone 4 — Nutrition History UI

## E4-09 — Build History route, range controls, paging, and coverage mode

### Purpose

Create the dedicated History route and stable period/navigation model before chart/detail complexity.

### Acceptance criteria

- History is owned by the Daily Log tab and does not add a fourth bottom tab.
- Supports 7 Days and 30 Days only.
- Fresh launch opens latest range ending yesterday.
- Preferred 7/30 mode may persist across launches.
- Today is never included.
- Previous/Next pages by exactly the selected range length.
- Next never goes past yesterday.
- Earliest partial range remains reachable.
- Backward paging stops before entirely pre-history windows using first-logged-date metadata.
- No-history authority shows a dedicated empty state and disables backward paging.
- If no Complete dates exist, display Logged-day mode without a disabled Complete selector.
- If Complete dates exist, default to Complete-day mode and allow switching globally to Logged days.
- Denominator toggle recalculates from loaded evidence without another range read.
- Navigation state is preserved through History drill-down/back.

### Dependencies

- E4-04.
- E4-05.
- E4-06.
- E4-07.

### Frontend work

- Add History route and range/session state.
- Add paging controls and empty/loading/error states.
- Add Complete/Logged denominator control.

### Testing requirements

- Latest range on launch.
- 7/30 paging across month/year/DST boundaries.
- earliest partial/no-history states.
- denominator mode availability/defaults.
- state restoration after route round-trips.

### Estimated implementation size

L

---

## E4-10 — Add the four-card History overview and daily mini charts

### Purpose

Provide the compact multi-day overview for Calories, Protein, Carbohydrate, and Fat.

### Acceptance criteria

- Four stable cards are shown whenever the range contains Logs.
- Cards are Calories, Protein, Carbohydrate, and Fat only.
- Each card shows selected-denominator statistic and usable-day count/context.
- Current target/reference context may be shown numerically where meaningful.
- Mini charts use discrete daily bars with gaps for no-Log dates.
- Mini charts contain no target/reference line.
- Missing or unusable nutrient data does not remove/reflow the card; neutral `—` is used.
- Strong red/green pass/fail styling is not used.
- Selecting a bar reveals/highlights exact date/value without navigating away immediately.
- `Show more nutrition` is provided.

### Dependencies

- E4-09.
- Existing `react-native-svg` dependency.

### Frontend work

- Add reusable bounded daily-bar primitive.
- Add four overview cards and selected-bar state.

### Testing requirements

- 7-day and 30-day chart points/gaps.
- no usable nutrient value.
- exact-zero bar semantics.
- selected-bar exact value.
- current target numeric context.

### Estimated implementation size

M

---

## E4-11 — Add Nutrition Details sheet and grouped nutrient browsing

### Purpose

Expose all canonical nutrients without duplicating the four macro overview on the same visible surface.

### Acceptance criteria

- `Show more nutrition` opens a distinct detail surface; the four overview charts are not simultaneously visible.
- iPhone presentation may use an effectively full-height sheet/card with own header, Close control, and scrolling.
- Nutrition Facts starts expanded.
- Vitamins, Minerals, and Fatty Acids start collapsed.
- Familiar Nutrition Facts hierarchy/order is used without imitating a physical label.
- Groups are expandable accordions/cards, not swipe-only pages.
- Expanded state and scroll position survive focused nutrient drill-down/back.
- Every canonical nutrient row remains structurally present.
- No-usable-value rows show neutral `—`.
- Rows remain compact and do not each embed a chart.
- Period value and current reference context are shown where meaningful.
- Tapping a row opens focused History for that nutrient.
- Period paging remains available and preserves detail context.

### Dependencies

- E4-09.
- E4-10.

### Frontend work

- Add sheet/detail navigation state.
- Reuse canonical nutrient grouping/hierarchy.
- Add compact grouped row component.

### Testing requirements

- default expanded/collapsed state.
- state restoration after nutrient drill-down.
- no-data rows remain present.
- paging while detail is open.

### Estimated implementation size

M

---

## E4-12 — Add focused nutrient History and exact daily rows

### Purpose

Allow deep inspection of one nutrient across the selected 7/30-day calendar range.

### Acceptance criteria

- Focused view shows nutrient name and stable canonical unit.
- Shows selected-denominator average and actual usable-day count.
- Shows current target/reference context when meaningful.
- Uses one daily bar per calendar date with true zero baseline.
- Focused chart may show explicitly labeled current reference line.
- Axis is not truncated merely to exaggerate differences.
- Estimated state may be represented subtly.
- Missing dates are gaps.
- Bar selection reveals/highlights exact date/value.
- 7-day Daily values starts expanded with seven rows.
- 30-day Daily values starts collapsed with thirty rows available.
- No-Log rows remain visible as neutral `No logs`/unavailable state.
- Complete dates may use a subtle non-reward checkmark.
- Daily row navigates to the exact Daily Log date.
- Back restores Nutrition Details context.
- Period paging stays on the same nutrient.
- No swipe-left/right nutrient switching is added.

### Dependencies

- E4-11.

### Frontend work

- Add focused chart/detail screen state.
- Add exact daily rows and Daily Log date navigation.
- Integrate selected-date chart/list state.

### Testing requirements

- true-zero baseline/scaling.
- reference-line bounds.
- 7/30 row behavior.
- no-Log/unknown-only/explicit-zero rows.
- back/navigation state.
- paging on same nutrient.

### Estimated implementation size

L

---

# Milestone 5 — Food authoring density refinement

## E4-13 — Restrict default Food form to conventional Nutrition Facts fields

### Purpose

Keep ordinary manual Food entry familiar and bounded as the canonical nutrient catalog grows.

### Acceptance criteria

- New Food default nutrient fields follow conventional Nutrition Facts ordering: Calories; Total Fat; Saturated Fat; Trans Fat; Cholesterol; Sodium; Total Carbohydrate; Dietary Fiber; Total Sugars; Added Sugars; Protein; Vitamin D; Calcium; Iron; Potassium.
- Serving information remains before nutrient entry.
- Extended catalog fields are not all rendered by default.
- Absence/blank remains unknown rather than zero.
- Explicit typed `0` retains zero semantics.
- A `not a significant source` statement is not automatically translated to exact zero.
- Existing saved Foods with populated extended nutrients do not lose or hide those values on edit.

### Dependencies

- Existing nutrient entry/status model.

### Frontend work

- Adjust default visible nutrient set/order.
- Preserve existing nutrient-state controls and validation.

### Testing requirements

- New Food default set/order.
- blank/zero transitions.
- existing Food extended data preservation.
- regression across OCR/import-derived Foods where manual edit is supported.

### Estimated implementation size

M

---

## E4-14 — Add grouped `More nutrients` authoring for extended catalog fields

### Purpose

Keep the full canonical catalog available without a giant flat manual form.

### Acceptance criteria

- `More nutrients` exposes Vitamins, Minerals, and Fatty Acids groups.
- Create and edit use the same grouped nutrient discovery model.
- Adding a nutrient initializes the field as unknown.
- User may enter explicit zero or a numeric known/estimated value according to existing entry semantics.
- Existing populated extended nutrients remain visible without requiring re-addition.
- The canonical nutrient catalog/IDs are unchanged.
- No `Show All` giant-form mode is required.

### Dependencies

- E4-13.

### Frontend work

- Add grouped picker/disclosure.
- Integrate selected extended nutrients into the Food form.

### Testing requirements

- add/cancel/reopen behavior.
- unknown initialization.
- duplicate prevention.
- edit/create consistency.
- Vitamins/Minerals/Fatty Acids ordering.

### Estimated implementation size

M

---

# Milestone 6 — Durability, parity, physical qualification, and closure

## E4-15 — Extend backup/restore and one-time transfer for Complete state

### Purpose

Preserve Complete as authoritative Daily Log metadata across supported durability/migration workflows.

### Acceptance criteria

- Local backup export includes Complete state as part of the coherent SQLite snapshot.
- Restore validation/staging accepts and preserves valid Complete state.
- Older backups without Complete state remain valid where schema migration policy supports them and map to not-confirmed-complete.
- One-time remote-to-local transfer carries Complete state for matching Daily Log dates.
- Transfer does not create synchronization, background replication, or merge semantics.
- Transfer of source data with no Complete state does not infer Complete.
- Backup/restore/transfer do not rewrite historical nutrient snapshots.

### Dependencies

- E4-01.
- Existing backup/restore and transfer infrastructure.

### Testing requirements

- backup/restore round trip with Complete and unconfirmed dates.
- old-schema backup upgrade path as applicable.
- transfer parity with mixed Complete/unconfirmed dates.
- failure/rollback preservation.

### Estimated implementation size

M

---

## E4-16 — Qualify History parity, failure behavior, and physical chart usability

### Purpose

Provide release evidence that the accepted product/data semantics survive difficult states on both authorities and the target iPhone.

### Acceptance criteria

Automated qualification deliberately covers:

- no-history authority;
- first logged date and earliest partial period;
- no-Log dates inside a populated range;
- known values;
- estimated values;
- explicit zero;
- numeric + unknown contributors;
- unknown-only selected nutrient;
- Complete and unconfirmed dates;
- one usable Complete day;
- Complete day with selected nutrient unknown-only;
- Complete/Logged mode switching;
- exact-decimal calculations/rounding;
- 7/30 range boundaries and oversized rejection;
- Today exclusion;
- DST/month/year date boundaries;
- target changes without history evidence invalidation;
- source Food/Recipe edits without historical rewrite;
- atomic Complete invalidation;
- same-snapshot serving-equivalent Complete preservation;
- move source/destination invalidation;
- stale/late response suppression;
- same-range cached refresh failure;
- remote failure without fallback;
- backup/restore;
- one-time transfer; and
- local/remote evidence + projection parity.

Physical iPhone qualification proves:

- four-card overview is readable and navigable;
- 7-day chart points are selectable;
- 30-day chart preserves one daily observation per date;
- static 30-bar chart is used if meaningfully readable/selectable;
- if static 30-bar qualification fails, horizontal scrolling is introduced and requalified without weekly aggregation or dropped observations;
- Nutrition Details sheet is usable with long groups;
- focused nutrient chart/list interaction is usable; and
- Daily Log remains logging-first after the hierarchy change.

### Dependencies

- E4-03 through E4-15.

### Backend work

- Add parity/contract fixtures and remote tests.

### Frontend/mobile work

- Add calculation/navigation/cache tests.
- Add physical-device qualification harness/checklist where automation cannot prove interaction/readability.

### Documentation work

- Record qualification evidence and any evidence-driven 30-day chart adaptation.
- Update current feature/architecture/testing guides only after behavior is implemented and proven.

### Estimated implementation size

L

---

## E4-17 — Reconcile current documentation and close Epic 4

### Purpose

Promote implemented Epic 4 behavior from versioned planning into current canonical project, feature, architecture, and testing guides.

### Acceptance criteria

- Current State marks Epic 4 complete only after implementation/qualification is complete.
- Product Roadmap status is updated from implementation to Complete.
- Recipes/Logging feature guide accurately distinguishes immutable history substrate from the now-implemented History/Trends surface.
- Foods/Nutrition guide reflects the new manual Food form organization.
- Architecture overview/decision index reflect Complete persistence and bounded History read only after implementation exists.
- Testing guide references the qualification suite/evidence.
- Versioned Epic 4 PRD, architecture, data contracts, backlog, and qualification evidence remain reachable historical planning/closure records.
- Documentation validation and project audit pass.

### Dependencies

- E4-16.

### Estimated implementation size

M

---

# Dependency summary

```text
E4-01 Complete persistence
├── E4-02 Complete mutation/recovery
├── E4-03 atomic invalidation
├── E4-04 History range evidence
└── E4-15 backup/restore/transfer

E4-04
└── E4-05 shared projections
    └── E4-06 cache/failure model
        └── E4-09 History route/ranges
            └── E4-10 overview charts
                └── E4-11 Nutrition Details
                    └── E4-12 focused nutrient History

E4-02 + E4-03
└── E4-07 Daily Log hierarchy/Complete
    └── E4-08 Daily Nutrition

E4-13 default Food form
└── E4-14 More nutrients

E4-03 through E4-15
└── E4-16 qualification
    └── E4-17 documentation/closure
```

## Parallelism guidance

After E4-01 establishes persistence shape:

- E4-02/E4-03 can proceed alongside E4-04;
- E4-13/E4-14 can proceed independently from History data work;
- E4-07 can begin after Complete mutation semantics are stable;
- E4-09 should wait for the range/projection/cache contracts rather than mocking a second semantics path; and
- E4-15 can proceed once Complete storage is stable, but final transfer qualification belongs with E4-16.

## GitHub issue creation rule

Do not create implementation issues from this backlog until:

1. `python scripts/validate-docs.py` passes for the finalized planning package; and
2. `scripts/project-audit.sh pre-commit` passes (directly or through the repository CI/session contract).

After that gate, issues should be created from these E4 task boundaries rather than re-Grilling product scope during implementation.
