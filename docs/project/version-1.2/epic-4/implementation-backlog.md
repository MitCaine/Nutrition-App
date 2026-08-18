# Version 1.2 Epic 4 — GitHub Implementation Backlog

> **Document role: Implementation Backlog.** This decomposes the approved [Feature PRD](feature-prd.md) and [Data and Runtime Contracts](data-contracts.md) into bounded implementation work. No issue in this backlog authorizes code changes until the planning package passes documentation validation, project audit, and the repository issue-creator dry run.

## Backlog status

Architecture review: **Approved subject to repository validation/audit and issue-creator gates.**

Epic 4 scope is frozen. New product ideas discovered during implementation go to the future-product register unless required to satisfy an accepted invariant or acceptance criterion.

Implementation must stop and return to architecture review if a task would require synchronization, mixed application-data authority, historical target reconstruction, weakening immutable Daily Log nutrition, non-atomic Complete invalidation, or an unbounded History/reporting API.

The finalized planning package passed `python3 scripts/validate-docs.py` and `scripts/project-audit.sh pre-commit` at commit `7017e3d`. This issue-template normalization is formatting/decomposition only and must pass those gates again, plus `create_issues.py --dry-run`, before GitHub issues are created.

---

# Milestone 1 — Complete-state authority and persistence

## E4-01 — Add date-owned Complete persistence for local and remote authorities

### Purpose

Introduce durable positive day-level Complete state without backfilling or modifying historical nutrition.

### Background

Epic 4 distinguishes user-confirmed logging coverage from nutrient-data completeness. Complete belongs to an authoritative Daily Log calendar date, not to individual Log entries, and must exist equivalently in local SQLite and preserved remote PostgreSQL authority.

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

### Backend work

- Add owner/date-scoped day-completion persistence to the remote authority.
- Add model/repository operations for reading and asserting Complete.
- Preserve owner isolation and existing Daily Log snapshot ownership.

### Frontend work

- Add equivalent local SQLite schema/storage operations within the Daily Logs runtime implementation.
- Preserve authoritative LocalDate semantics and deterministic local migration behavior.

### API work

- No public mutation endpoint is required in this task; E4-02 owns mark-Complete API behavior.
- Ensure persistence types can support the later shared runtime/API contract without adding a new runtime capability.

### Migration work

- Add the remote application migration after the current application head.
- Add the corresponding local SQLite schema migration/version step.
- Perform no historical Complete backfill and no nutrient-snapshot rewrite.

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

### Background

A visible Complete state is an authoritative assertion, so the app must not claim success until the selected authority confirms persistence. The remote path already has deterministic Daily Log mutation identity and reconciliation patterns that should be extended rather than replaced.

### Acceptance criteria

- Mark Complete is allowed only for Today/past dates with at least one Log.
- Successful UI state is based on confirmed authoritative persistence.
- Remote indeterminate responses can be reconciled using existing mutation identity/status patterns.
- Same-intent replay cannot create duplicate state.
- Changed-payload/reused-intent conflicts are rejected consistently with existing mutation policy.
- Complete state is unavailable for assertion while a nutrition-changing mutation for the same date remains unresolved in the client workflow.
- No manual clear/un-complete mutation is required for initial Epic 4.

### Out of scope

- Manual un-completion.
- Automatic Complete invalidation from subsequent Log mutations.
- History range reads or History UI.
- New synchronization or offline mutation queues.

### Dependencies

- E4-01.

### Backend work

- Add authenticated mark-Complete service behavior.
- Reuse existing Daily Log mutation receipts/reconciliation semantics for deterministic replay and indeterminate outcomes.
- Enforce date and non-empty-day eligibility authoritatively.

### Frontend work

- Add the local equivalent mutation operation to the Daily Logs runtime.
- Add shared runtime typing and recovery state needed by the later UI.
- Gate assertion while a conflicting nutrition mutation is unresolved.

### API work

- Add the bounded mark-Complete remote operation and mutation-status/reconciliation behavior required for the existing deterministic mutation model.
- Preserve stable conflict/non-commit/unresolved classifications.

### Migration work

- No additional persistence migration is expected beyond E4-01; reuse existing mutation-receipt infrastructure unless implementation evidence proves a bounded additive change is necessary.

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

### Background

Complete describes logging coverage for a specific authoritative Daily Log state. Any successful mutation that changes stored historical nutrition invalidates that assertion. Invalidation must occur in the same authoritative transaction as the nutrition mutation so partial success cannot leave stale Complete metadata.

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

### Out of scope

- User-initiated manual un-completion.
- Source Food/Recipe changes rewriting historical Daily Log snapshots.
- Target changes affecting Complete.
- History presentation.

### Dependencies

- E4-01.
- Existing Daily Log mutation contracts.

### Backend work

- Integrate Complete invalidation into authoritative remote create/edit/delete/move transactions.
- Preserve idempotent and reconciliation behavior for the combined mutation result.
- Detect exactly unchanged resulting nutrient snapshots where required by the accepted preservation rule.

### Frontend work

- Integrate equivalent invalidation into local exclusive Daily Log mutation transactions.
- Ensure local mutation results expose enough state for cache invalidation without a second cleanup write.

### API work

- Preserve existing Daily Log mutation API boundaries and deterministic status semantics.
- No separate Complete-clear API call may be required for automatic invalidation.

### Migration work

- None beyond E4-01 persistence.

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

### Background

History is a read projection over the existing Daily Logs capability, not a new authority. A bounded range read avoids 7 or 30 per-date remote requests and gives local/remote implementations one semantic contract for missing dates, Complete state, and exact nutrient evidence.

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

### Out of scope

- 90-day or custom ranges.
- Historical target reconstruction.
- Per-entry Food graph payloads.
- Synchronization, fallback, dual reads, or mixed-authority range assembly.

### Dependencies

- E4-01.
- Existing Daily Log daily aggregate behavior.

### Backend work

- Add the bounded remote range service projection.
- Preserve owner isolation, canonical units, exact values, missing-date evidence, and Complete state.
- Return first-logged-date bounds metadata without probing earlier periods.

### Frontend work

- Add the direct bounded SQLite range read.
- Extend Daily Logs runtime types and local/remote adapters with one equivalent operation.

### API work

- Add one bounded remote request/response contract.
- Add stable error classification for invalid dates and ranges larger than 30 calendar dates.

### Migration work

- None beyond E4-01 Complete persistence.

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

### Background

Local SQLite and remote FastAPI/PostgreSQL should supply equivalent daily evidence, while one shared calculation layer owns denominator selection, usable-day counts, exact-decimal averaging, gaps, and grouped History presentation semantics. This prevents the two authorities from independently redefining averages.

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

### Out of scope

- Fetching authoritative range evidence.
- Current target/reference persistence or historical target versioning.
- Coaching, trend judgments, or prior-period comparisons.

### Dependencies

- E4-04.
- Existing exact-value codecs/contracts.

### Backend work

- No independent backend calculation path; the remote authority must return the evidence contract from E4-04 rather than a divergent aggregate interpretation.

### Frontend work

- Add shared projection types and pure calculation helpers consumed by History UI.
- Reuse canonical nutrient ordering/grouping and exact-value codecs.
- Keep target/reference context outside historical evidence calculations.

### API work

- No new API operation; consume the E4-04 evidence contract without adding server-specific average semantics.

### Migration work

- None.

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

### Background

History may page quickly between bounded ranges while React Query retains cached data and remote responses arrive out of order. Cache identity and invalidation must preserve the selected authority/date range and must never display another period's evidence under the current period label.

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

### Out of scope

- Changing History evidence semantics from E4-04/E4-05.
- Cross-authority cache reuse or fallback.
- Persistent background synchronization.

### Dependencies

- E4-04.
- E4-05.

### Backend work

- None expected; retain the bounded E4-04 remote range contract and normal request identity semantics.

### Frontend work

- Add authority/start/end React Query keys and overlap invalidation helpers.
- Add latest-request-wins/identity protection for rapid paging.
- Add exact-range stale/retry presentation state.
- Recalculate denominator modes from the same cached evidence.

### API work

- No new endpoint; preserve remote failure classification so the client can distinguish retryable range failure without authority fallback.

### Migration work

- None.

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

### Background

The current full Target Progress and Totals blocks push meal logging too far down the screen. Epic 4 keeps analysis one interaction away: the Daily Log gets compact nutrition, Complete, History, and View Nutrition while meals/Add Food regain primary position.

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

### Out of scope

- Daily Nutrition full-catalog implementation.
- History charts or nutrient drill-down.
- Fourth bottom-navigation tab.
- Manual un-completion.

### Dependencies

- E4-02.
- E4-03.

### Backend work

- No new backend behavior beyond the Complete and Daily Log mutation contracts established by E4-02/E4-03.

### Frontend work

- Extend sticky-header action space in a bounded way.
- Add Complete read/mutation state.
- Reorder Daily Log content around logging.
- Add centered History navigation and compact four-row nutrition summary.
- Move target configuration entry away from the primary Daily Log as required by E4-08.

### API work

- Consume existing Daily Log summary/target reads and E4-02 Complete mutation contracts; no additional endpoint is expected.

### Migration work

- None.

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

### Background

Daily Nutrition owns exhaustive analysis for the date selected in Daily Log. It should combine amount and target/reference context in one nutrient row instead of rendering separate full-catalog Totals and Target Progress lists.

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

### Out of scope

- Multi-day History calculations or charts.
- Independent date navigation inside Daily Nutrition.
- Redesign of Target authority/tracking semantics.
- Dedicated data-quality diagnostics.

### Dependencies

- E4-07.
- Existing Target/nutrient formatting contracts.

### Backend work

- None expected; use existing authoritative daily summary and target/reference contracts.

### Frontend work

- Add the Daily Nutrition route/screen and shared nutrient-row presentation.
- Consolidate current target-progress and total information into one grouped hierarchy.
- Retire duplicate full-catalog Daily Log blocks.
- Preserve target authority labels and direction semantics.

### API work

- No new endpoint is expected; compose existing selected-date nutrient and target/reference reads.

### Migration work

- None.

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

### Background

History is owned by Daily Log but needs a dedicated route. Initial scope is intentionally bounded to 7-day and 30-day calendar windows ending yesterday, with explicit Complete-day versus Logged-day denominator behavior derived from one loaded range.

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

### Out of scope

- 90-day/custom ranges.
- Including Today.
- Overview/detail chart implementation beyond the route shell.
- Editing Daily Logs or Complete state from History.

### Dependencies

- E4-04.
- E4-05.
- E4-06.
- E4-07.

### Backend work

- None beyond the E4-04 bounded range evidence contract.

### Frontend work

- Add History route and range/session state.
- Add paging controls and empty/loading/error states.
- Add Complete/Logged denominator control using E4-05 projections.
- Preserve range/mode/navigation context through drill-down/back.

### API work

- Consume the E4-04 bounded range operation; no new endpoint is expected.

### Migration work

- None.

### Testing requirements

- Latest range on launch.
- 7/30 paging across month/year/DST boundaries.
- Earliest partial/no-history states.
- Denominator mode availability/defaults.
- State restoration after route round-trips.

### Estimated implementation size

L

---

## E4-10 — Add the four-card History overview and daily mini charts

### Purpose

Provide the compact multi-day overview for Calories, Protein, Carbohydrate, and Fat.

### Background

The overview intentionally stays fixed and sparse. Four macro cards give immediate period context while additional nutrients remain one interaction away, preventing the History landing surface from becoming another exhaustive catalog.

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

### Out of scope

- Full nutrient catalog on the overview.
- Target/reference lines on mini charts.
- Automatic trend judgments, comparison percentages, or coaching.
- Weekly aggregation of 30-day observations.

### Dependencies

- E4-09.
- Existing `react-native-svg` dependency.

### Backend work

- None; overview derives from E4-04 evidence and E4-05 projections.

### Frontend work

- Add a reusable bounded daily-bar primitive.
- Add the four overview cards, exact selected-bar callout, and `Show more nutrition` entry.
- Preserve no-Log gaps and stable card structure.

### API work

- No new endpoint; use the already loaded History range payload.

### Migration work

- None.

### Testing requirements

- 7-day and 30-day chart points/gaps.
- No usable nutrient value.
- Exact-zero bar semantics.
- Selected-bar exact value.
- Current target numeric context.

### Estimated implementation size

M

---

## E4-11 — Add Nutrition Details sheet and grouped nutrient browsing

### Purpose

Expose all canonical nutrients without duplicating the four macro overview on the same visible surface.

### Background

The Grill rejected simultaneous visible duplication of the macro overview and the detailed Nutrition Facts hierarchy. `Show more nutrition` therefore opens a distinct detail surface that can preserve a complete familiar hierarchy without competing with the overview.

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

### Out of scope

- Focused nutrient chart implementation itself.
- Horizontal category swipe pages.
- Simultaneous display of the four macro overview charts behind/beside the detail content.
- Nutrient pinning or dashboard customization.

### Dependencies

- E4-09.
- E4-10.

### Backend work

- None; the detail surface uses the all-canonical-nutrient range payload from E4-04.

### Frontend work

- Add sheet/detail navigation state.
- Reuse canonical nutrient grouping and hierarchy.
- Add compact grouped nutrient rows.
- Preserve accordion/scroll/range context through drill-down and paging.

### API work

- No new endpoint or range read when the detail surface opens.

### Migration work

- None.

### Testing requirements

- Default expanded/collapsed state.
- State restoration after nutrient drill-down.
- No-data rows remain present.
- Paging while detail is open.

### Estimated implementation size

M

---

## E4-12 — Add focused nutrient History and exact daily rows

### Purpose

Allow deep inspection of one nutrient across the selected 7/30-day calendar range.

### Background

Focused nutrient History provides the detailed chart and exact daily evidence that the compact overview and grouped detail rows intentionally omit. The chart is supplementary to exact date/value rows and uses the current target/reference only as an explicitly current lens.

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

### Out of scope

- Swipe navigation between adjacent nutrients.
- Historical target reconstruction.
- Editing food/log data directly from focused History.
- Automatic good/bad, improving/worsening, or adherence judgments.

### Dependencies

- E4-11.

### Backend work

- None; focused History uses the same bounded range evidence already loaded.

### Frontend work

- Add focused chart/detail screen state.
- Add exact daily rows and explicit Daily Log date navigation.
- Integrate chart/list selection state, current-reference line labeling, and same-nutrient period paging.
- Preserve Nutrition Details context on Back.

### API work

- No new endpoint; do not refetch merely because one nutrient is focused.

### Migration work

- None.

### Testing requirements

- True-zero baseline/scaling.
- Reference-line bounds.
- 7/30 row behavior.
- No-Log/unknown-only/explicit-zero rows.
- Back/navigation state.
- Paging on same nutrient.

### Estimated implementation size

L

---

# Milestone 5 — Food authoring density refinement

## E4-13 — Restrict default Food form to conventional Nutrition Facts fields

### Purpose

Keep ordinary manual Food entry familiar and bounded as the canonical nutrient catalog grows.

### Background

The current New Food form exposes the growing canonical nutrient catalog too aggressively. Epic 4 keeps the standard conventional Nutrition Facts set immediately visible while preserving exact unknown-versus-zero semantics and all existing extended nutrient data.

### Acceptance criteria

- New Food default nutrient fields follow conventional Nutrition Facts ordering: Calories; Total Fat; Saturated Fat; Trans Fat; Cholesterol; Sodium; Total Carbohydrate; Dietary Fiber; Total Sugars; Added Sugars; Protein; Vitamin D; Calcium; Iron; Potassium.
- Serving information remains before nutrient entry.
- Extended catalog fields are not all rendered by default.
- Absence/blank remains unknown rather than zero.
- Explicit typed `0` retains zero semantics.
- A `not a significant source` statement is not automatically translated to exact zero.
- Existing saved Foods with populated extended nutrients do not lose or hide those values on edit.

### Out of scope

- Changing canonical nutrient IDs/catalog semantics.
- Regulatory label authoring/certification.
- OCR parser or USDA mapping redesign.
- Treating absent nutrients as zero.

### Dependencies

- Existing nutrient entry/status model.

### Backend work

- None expected; preserve existing Food nutrient persistence and status semantics.

### Frontend work

- Adjust the default visible nutrient set and ordering for New Food.
- Preserve existing populated extended nutrients on edit.
- Preserve nutrient-state controls and validation.

### API work

- No contract change expected; continue sending explicit nutrient/status values through existing Food operations.

### Migration work

- None.

### Testing requirements

- New Food default set/order.
- Blank/zero transitions.
- Existing Food extended data preservation.
- Regression across OCR/import-derived Foods where manual edit is supported.

### Estimated implementation size

M

---

## E4-14 — Add grouped `More nutrients` authoring for extended catalog fields

### Purpose

Keep the full canonical catalog available without a giant flat manual form.

### Background

Restricting the default Food form must not make extended nutrient authoring inaccessible. The accepted discovery model uses the same broad Vitamins, Minerals, and Fatty Acids grouping used elsewhere in the app.

### Acceptance criteria

- `More nutrients` exposes Vitamins, Minerals, and Fatty Acids groups.
- Create and edit use the same grouped nutrient discovery model.
- Adding a nutrient initializes the field as unknown.
- User may enter explicit zero or a numeric known/estimated value according to existing entry semantics.
- Existing populated extended nutrients remain visible without requiring re-addition.
- The canonical nutrient catalog/IDs are unchanged.
- No `Show All` giant-form mode is required.

### Out of scope

- A giant `Show All` form.
- Canonical nutrient catalog changes.
- Automatic zero inference.
- Separate create/edit nutrient-discovery models.

### Dependencies

- E4-13.

### Backend work

- None expected; reuse existing Food nutrient persistence/status contracts.

### Frontend work

- Add grouped nutrient picker/disclosure for Vitamins, Minerals, and Fatty Acids.
- Integrate selected extended nutrients into create/edit forms.
- Prevent duplicate additions and initialize newly selected nutrients as unknown.

### API work

- No new endpoint expected; use existing Food create/update nutrient contracts.

### Migration work

- None.

### Testing requirements

- Add/cancel/reopen behavior.
- Unknown initialization.
- Duplicate prevention.
- Edit/create consistency.
- Vitamins/Minerals/Fatty Acids ordering.

### Estimated implementation size

M

---

# Milestone 6 — Durability, parity, physical qualification, and closure

## E4-15 — Extend backup/restore and one-time transfer for Complete state

### Purpose

Preserve Complete as authoritative Daily Log metadata across supported durability/migration workflows.

### Background

Complete is durable Daily Log metadata, so supported backup/restore and the existing one-time remote-to-local transfer must preserve it. These workflows remain replacement/transfer mechanisms, never synchronization or a second live authority.

### Acceptance criteria

- Local backup export includes Complete state as part of the coherent SQLite snapshot.
- Restore validation/staging accepts and preserves valid Complete state.
- Older backups without Complete state remain valid where schema migration policy supports them and map to not-confirmed-complete.
- One-time remote-to-local transfer carries Complete state for matching Daily Log dates.
- Transfer does not create synchronization, background replication, or merge semantics.
- Transfer of source data with no Complete state does not infer Complete.
- Backup/restore/transfer do not rewrite historical nutrient snapshots.

### Out of scope

- Cloud backup.
- Multi-device synchronization.
- Continuous remote/local replication or merge semantics.
- Inferring Complete from existing Logs.

### Dependencies

- E4-01.
- Existing backup/restore and transfer infrastructure.

### Backend work

- Extend the preserved remote transfer/export evidence needed to carry owner/date Complete state.
- Preserve owner isolation and immutable nutrient snapshots.

### Frontend work

- Ensure local SQLite backup export/restore validation and staged activation preserve the E4-01 Complete table/state.
- Extend local transfer import handling for Complete metadata.

### API work

- Extend the existing one-time transfer contract only as required to carry Complete state; do not add a synchronization API.

### Migration work

- No new application schema beyond E4-01 is expected.
- Qualify older local backup schema upgrade behavior according to existing restore/migration policy.

### Testing requirements

- Backup/restore round trip with Complete and unconfirmed dates.
- Old-schema backup upgrade path as applicable.
- Transfer parity with mixed Complete/unconfirmed dates.
- Failure/rollback preservation.

### Estimated implementation size

M

---

## E4-16 — Qualify History parity, failure behavior, and physical chart usability

### Purpose

Provide release evidence that the accepted product/data semantics survive difficult states on both authorities and the target iPhone.

### Background

Epic 4 combines new persistence, range evidence, exact-value projections, navigation/cache behavior, and physical chart interaction. Closure requires an explicit parity fixture and physical-device qualification rather than assuming ordinary populated-day tests cover the difficult states.

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

### Out of scope

- Dedicated accessibility-specific chart qualification deferred by the Grill.
- 90-day/custom History.
- Prior-period trend judgments, coaching, or adherence scoring.
- New product scope discovered during qualification unless required to satisfy an accepted invariant.

### Dependencies

- E4-03 through E4-15.

### Backend work

- Add remote range/Complete parity fixtures and contract tests.
- Add migration, mutation atomicity, transfer, and failure-path qualification required by the acceptance matrix.

### Frontend work

- Add shared calculation, navigation, cache, stale-response, and local-runtime qualification tests.
- Add/maintain a physical-iPhone qualification checklist or harness for interaction/readability that automation cannot prove.
- Implement horizontal 30-day scrolling only if physical evidence demonstrates the static chart is not meaningfully usable.

### API work

- Qualify remote bounded-range and mark-Complete contracts, including deterministic mutation recovery and no-fallback failure behavior.

### Migration work

- Qualify E4-01 local/remote migrations and compatibility paths; this task should not introduce an unrelated schema change.

### Testing requirements

- Execute the complete automated acceptance matrix above for local and remote semantics where applicable.
- Run required PostgreSQL opt-in tests for changed remote persistence/concurrency surfaces.
- Run mobile unit/integration/native qualification required by changed local SQLite and UI surfaces.
- Record physical-iPhone evidence for 7-day/30-day chart behavior and Daily Log hierarchy.
- Record any evidence-driven 30-day chart adaptation and requalify it.

### Estimated implementation size

L

---

## E4-17 — Reconcile current documentation and close Epic 4

### Purpose

Promote implemented Epic 4 behavior from versioned planning into current canonical project, feature, architecture, and testing guides.

### Background

Versioned Epic 4 files are planning/closure evidence, while current guides own present repository behavior. They must be updated only after implementation and qualification prove the feature actually exists.

### Acceptance criteria

- Current State marks Epic 4 complete only after implementation/qualification is complete.
- Product Roadmap status is updated from implementation to Complete.
- Recipes/Logging feature guide accurately distinguishes immutable history substrate from the now-implemented History/Trends surface.
- Foods/Nutrition guide reflects the new manual Food form organization.
- Architecture overview/decision index reflect Complete persistence and bounded History read only after implementation exists.
- Testing guide references the qualification suite/evidence.
- Versioned Epic 4 PRD, architecture, data contracts, backlog, and qualification evidence remain reachable historical planning/closure records.
- Documentation validation and project audit pass.

### Out of scope

- New application behavior.
- Reopening frozen Epic 4 product scope.
- Rewriting historical planning documents to pretend implementation existed earlier.

### Dependencies

- E4-16.

### Backend work

- None; this is a documentation/closure task.

### Frontend work

- None; this is a documentation/closure task.

### API work

- None; this is a documentation/closure task.

### Migration work

- None; this is a documentation/closure task.

### Testing requirements

- `python3 scripts/validate-docs.py` passes.
- `scripts/project-audit.sh pre-commit` passes.
- Current guides are checked against the qualified implementation and closure evidence.

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

1. `python3 scripts/validate-docs.py` passes for the finalized planning package;
2. `scripts/project-audit.sh pre-commit` passes; and
3. `python3 scripts/github/create_issues.py docs/project/version-1.2/epic-4/implementation-backlog.md --repo MitCaine/Nutrition-App --dry-run` passes.

After those gates, run the same command without `--dry-run`. The repository utility owns creation/reconciliation of labels, source milestones, the parent Epic, child issues, generated Epic metadata/checklist, and the adjacent state file. Do not manually reproduce those GitHub records.