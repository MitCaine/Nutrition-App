# Version 1.2 Epic 4 — Nutrition History and Trends Feature PRD

> **Document role: Feature PRD.** This document is the normative product contract for Epic 4. It is derived from the [research record](planning.md) and the completed [Grill decision record](accepted-decisions.md). Implementation details belong in the [architecture review](architecture-review.md), [data contracts](data-contracts.md), and [implementation backlog](implementation-backlog.md).

## 1. Purpose

Epic 4 turns the Nutrition App's existing immutable Daily Log nutrition snapshots into a compact, inspectable multi-day History experience without weakening historical correctness.

The feature must help the user answer:

- what was logged over the last 7 or 30 calendar days;
- which dates drove a nutrient higher or lower;
- whether the period statistic is based on user-confirmed Complete days or all logged days;
- what exact value was recorded on a given date; and
- how that historical pattern compares with the nutrient's current target/reference context.

The feature is informational rather than coaching-oriented. It must not manufacture adherence judgments, infer unlogged intake, reinterpret unknown nutrient values as zero, or imply that current target settings were historically active.

## 2. Product structure

Epic 4 preserves the existing three-tab product model. History remains owned by the Daily Log tab.

```text
Daily Log
├── fast meal logging for one date
├── Daily Nutrition
│   └── exhaustive nutrition for the selected date
└── Nutrition History
    └── multi-day nutrition analysis
```

The governing information-hierarchy rule is **logging first, analysis one interaction away**.

History is an analysis/navigation surface. It may navigate back to an authoritative Daily Log date, but Epic 4 does not edit meals, delete Log entries, or mutate Foods/Recipes directly from History.

## 3. Scope

Epic 4 includes:

- a durable user-confirmed day-level `Complete` assertion;
- a logging-first Daily Log layout with a fixed four-nutrient compact summary;
- a consolidated Daily Nutrition detail route;
- a dedicated Nutrition History route under Daily Log;
- 7-day and 30-day calendar ranges ending no later than yesterday;
- period paging by whole 7-day or 30-day windows;
- explicit Complete-day versus Logged-day denominator semantics;
- fixed overview cards for Calories, Protein, Carbohydrate, and Fat;
- discrete daily bar charts;
- a separate Nutrition Details surface using familiar Nutrition Facts hierarchy plus Vitamins, Minerals, and Fatty Acids sections;
- focused per-nutrient History with exact daily rows and navigation to the corresponding Daily Log date;
- current target/reference comparison as a present-day lens rather than historical goal reconstruction;
- bounded range-read support inside the existing Daily Logs runtime capability;
- local SQLite and remote FastAPI/PostgreSQL semantic parity;
- History-specific loading, cache, stale-response, retry, and invalidation rules;
- a simplified manual Food authoring surface using the conventional Nutrition Facts field set by default, with extended nutrients available through grouped `More nutrients` disclosure; and
- migration, backup/restore, one-time authority-transfer, parity, exact-value, and physical-device qualification required by this PRD.

## 4. Product invariants

### 4.1 Historical nutrition remains immutable

- History derives nutrition only from persisted Daily Log nutrient snapshots.
- Later Food or Recipe changes must not alter existing historical nutrition.
- History must not recalculate past intake from current Food/Recipe definitions.
- Existing exact-decimal semantics remain authoritative.
- Parent nutrients must not be fabricated by summing incomplete child sets.

### 4.2 Unknown is not zero

- `known`, `estimated`, `zero`, and `unknown` remain semantically distinct.
- A date with no Logs is not a zero-consumption date.
- A nutrient with no usable numeric evidence is not a zero value.
- An explicit source value of zero may remain explicit zero.
- Unknown contributors may remain visually quiet in ordinary views, but the underlying uncertainty must remain available to calculation logic.

### 4.3 One application-data authority

- History remains part of the existing Daily Logs capability.
- A running context uses exactly one application-data authority: local SQLite or remote FastAPI/PostgreSQL.
- No History request may mix local and remote evidence.
- No fallback, dual read, shadow read, synchronization, or background replication is introduced.

### 4.4 Calendar dates are authoritative

- History ranges are authoritative Daily Log calendar-date ranges, not elapsed-hour windows.
- `7 Days` means seven calendar dates, not 168 hours.
- `30 Days` means thirty calendar dates.
- DST and timezone transitions must not skip, duplicate, or migrate existing historical dates.
- History does not infer consumption time from Log creation timestamps.

### 4.5 Current target/reference is not historical goal state

- The existing target/profile configuration is mutable current state.
- Epic 4 does not add target-history versioning.
- Any target/reference shown in History must be labeled as current context, such as `Current target`, `Current custom target`, `Current DRI`, `Current Daily Value`, or `Current limit`.
- The UI must not imply that the current value was configured on each historical date.

## 5. Daily Log changes

The Daily Log must prioritize the logging workflow in this order:

1. sticky header with `Complete` and Settings;
2. date navigation: `Previous Day | History | Next Day`;
3. selected-date heading and direct date selection;
4. compact nutrition summary;
5. `View Nutrition`; and
6. meal sections with meal-level `Add Food` actions.

`History` occupies the center space between Previous Day and Next Day. It does not add another bottom-navigation tab.

### 5.1 Compact nutrition summary

The compact summary is fixed to:

- Calories;
- Protein;
- Carbohydrate; and
- Fat.

Requirements:

- no pinning or arbitrary nutrient customization;
- no progress bars;
- no percentage display on the compact Daily Log surface;
- where a meaningful target exists, use concise `consumed / target` presentation;
- amount-only nutrients show consumed amount only; and
- on an empty date, `0` may mean `0 logged` for these four rows, but must not be reused by History as evidence of zero consumption.

The full nutrient catalog must no longer sit before the meal logging flow.

## 6. Complete state

`Complete` is a durable positive assertion by the user that food logging for one authoritative Daily Log date is finished.

It is not:

- a nutrient-data-quality assertion;
- a lock on the day;
- a success/adherence score;
- an automatically inferred state; or
- an assertion that all nutrients are known.

### 6.1 Availability and persistence

- Complete belongs to the calendar date, not to individual Log entries.
- The control is available for Today and past dates that contain at least one Log.
- Empty dates cannot be marked Complete.
- Existing historical dates are not backfilled as Complete when the feature ships.
- Absence of a Complete assertion means `not confirmed complete`, not `Incomplete`.
- Complete is durable application data and survives supported backup/restore and one-time authority transfer.
- A historical Complete assertion remains attached to its authoritative date if timezone/calendar settings later change.
- Internal persistence may retain `completed_at` or equivalent evidence; Epic 4 does not expose it as a streak/timing metric.

### 6.2 Control behavior

- Use a compact labeled control such as `☐ Complete` / `✓ Complete` in the sticky header.
- The checked state is shown only after authoritative persistence succeeds.
- A failed write leaves the date unchecked and provides compact retry/error handling.
- While a nutrition-changing mutation for the same date is unresolved, Complete is temporarily unavailable.
- Remote Complete writes use the existing deterministic Daily Log mutation/reconciliation model.

Manual retraction of an already asserted Complete state is not required in initial Epic 4 and remains deferred future scope.

### 6.3 Invalidation rules

A nutrition-affecting Log mutation clears Complete automatically without another confirmation prompt.

- The mutation and Complete invalidation must be atomic within the selected authority.
- Moving an entry clears Complete for both source and destination dates.
- Deleting the final entry clears Complete because the date becomes empty.
- A serving/amount edit that produces an exactly unchanged resulting nutrient snapshot preserves Complete.
- Any resulting nutrient-snapshot change clears Complete.
- Meal-label-only and note-only edits preserve Complete.
- Later edits to source Foods or Recipes do not clear Complete for historical Logs because the stored snapshots did not change.
- Nutrition Target changes do not clear Complete.

## 7. Daily Nutrition

`View Nutrition` opens a dedicated Daily Nutrition route for the selected Daily Log date.

Requirements:

- display the selected date prominently;
- inherit date context from Daily Log rather than creating another date picker/state owner;
- return to the same Daily Log date;
- no own Previous/Next Day controls in initial Epic 4;
- consolidate the current overlapping Target Progress and Totals surfaces into one coherent nutrient presentation;
- preserve the canonical nutrient grouping/hierarchy;
- sections are collapsible and start expanded;
- collapse state persists during the current navigation/session context but resets to expanded on a fresh app session;
- `Nutrition targets` configuration moves from the primary Daily Log to this secondary analysis surface;
- recommended/custom target rows show consumed/target and percentage where useful;
- limit rows remain direction-aware without pass/fail framing;
- amount-only rows show consumed amount only;
- ignored nutrients are omitted from ordinary presentation;
- unknown contributors do not generate routine `Incomplete data` warnings or verbose source-count suffixes; and
- a fully unavailable/unknown total uses a neutral presentation such as `—`.

## 8. Nutrition History range model

### 8.1 Initial ranges

History supports exactly:

- `7 Days`; and
- `30 Days`.

Today is excluded from History in initial Epic 4. The newest supported History endpoint is yesterday, even when Today is marked Complete.

A fresh History launch opens the most recent supported period ending yesterday. The app may remember the user's preferred 7-day versus 30-day mode, but it must not reopen an arbitrarily old range on a fresh launch.

### 8.2 Whole-period paging

- Previous/Next moves exactly 7 dates in 7-day mode.
- Previous/Next moves exactly 30 dates in 30-day mode.
- Next never advances beyond yesterday.
- The earliest partial window containing the first logged date remains reachable.
- Dates before the first Log within that partial window remain missing, not zero.
- Previous is disabled once the next older period would be entirely before the first logged date.
- If no Logs exist at all, the first-logged-date boundary is absent and backward paging is disabled.

Paging remains available from:

- History overview;
- Nutrition Details; and
- focused nutrient History.

Detail context remains active when paging.

### 8.3 Navigation state

Within a History navigation session, preserve where practical:

- 7/30-day mode;
- selected date range;
- Complete-days versus Logged-days denominator mode;
- overview/detail surface;
- expanded nutrient groups;
- focused nutrient;
- selected chart date;
- Daily-values section state;
- scroll position; and
- return context after opening a Daily Log date.

## 9. History averages and coverage

Every period statistic must state what denominator it represents.

### 9.1 Default denominator

- If the range contains no Complete days, use `Logged-day average` and show the number of logged/usable days.
- If the range contains at least one Complete day, default to `Complete-day average`.
- Expose a lightweight global control to switch between Complete days and Logged days.
- The selected denominator mode applies to all overview cards, Nutrition Details rows, and focused nutrients together.
- Do not show a disabled Complete option when no Complete days exist; hide the selector and use Logged-day average.

### 9.2 Nutrient-specific usable-day count

Complete is logging coverage, not nutrient completeness.

For a selected nutrient:

- a Complete day participates in the Complete-day numeric average only if that date has usable numerical evidence for the nutrient;
- a Logged day participates in the Logged-day numeric average only if that date has usable numerical evidence for the nutrient;
- an estimated numeric value is usable numerical evidence;
- a date whose selected nutrient is entirely unknown/unavailable does not become zero and does not enter the numeric denominator; and
- labels must disclose the actual numeric denominator, for example `Complete-day average · 4 days used`.

No arbitrary minimum sample threshold is imposed. One usable day may produce a valid average if its denominator is stated explicitly.

## 10. History overview

If the selected range contains no Logs at all, retain range controls and show a dedicated empty-period state such as `No food was logged during this period.` Do not render four meaningless empty cards.

When the period contains Logs, the overview always contains four stable cards:

- Calories;
- Protein;
- Carbohydrate; and
- Fat.

Each card contains:

- the selected denominator's period statistic;
- compact current target/reference context where meaningful; and
- one small discrete daily bar chart.

Requirements:

- cards remain present even when one nutrient has no usable values;
- neutral `—` presentation is used instead of removing/reflowing a card;
- mini charts do not contain target/reference lines;
- missing dates remain gaps rather than zero-height consumption bars;
- target/limit status must not use strong red/green success/failure framing; and
- `Show more nutrition` opens the separate Nutrition Details surface.

## 11. Nutrition Details surface

`Show more nutrition` opens a distinct detail surface rather than expanding beneath the four overview cards. While this surface is active, the four overview charts are not simultaneously visible.

On iPhone, the surface may be an effectively full-height sheet/card with its own header, Close control, and vertical scrolling.

The default information structure follows familiar Nutrition Facts ordering without visually imitating a physical FDA label:

```text
Nutrition Details

▼ Nutrition Facts
   Calories
   Total Fat
     Saturated Fat
     Trans Fat
   Cholesterol
   Sodium
   Total Carbohydrate
     Fiber
     Total Sugars
       Added Sugars
   Protein
   Vitamin D
   Calcium
   Iron
   Potassium

▶ Vitamins
▶ Minerals
▶ Fatty Acids
```

Requirements:

- Nutrition Facts starts expanded;
- Vitamins, Minerals, and Fatty Acids start collapsed;
- groups use expandable cards/accordions rather than swipe-only category pages;
- expanded/collapsed state persists while the user remains in History and when drilling into a nutrient and back;
- every canonical nutrient row remains structurally available even if the selected range has no usable value for it;
- unavailable rows show neutral `—` rather than disappearing;
- rows stay compact and do not embed one chart each;
- rows may show period value plus current target/reference context where meaningful; and
- tapping a nutrient opens its focused History view.

## 12. Focused nutrient History

Focused History displays one nutrient at a time.

Required content:

- nutrient name;
- stable canonical display unit;
- selected denominator's average and usable-day count;
- current target/reference context where available;
- one daily bar per calendar date;
- exact daily values; and
- deliberate navigation from a daily row to that exact Daily Log date.

### 12.1 Chart semantics

- Use discrete bars, not a connected line.
- The vertical axis uses a true zero baseline.
- Scale through at least the greater of the maximum displayed daily value or the current target/reference line.
- Do not truncate the axis merely to exaggerate ordinary differences.
- A current reference line is allowed only on focused charts and must be explicitly labeled as current context.
- Estimated contribution may be distinguished subtly when materially useful.
- Missing dates remain gaps.
- Selecting a bar reveals/highlights its exact date/value rather than immediately navigating away.

Thirty-day mode initially attempts a static 30-bar chart. If physical-device qualification shows that individual dates cannot be meaningfully read/selected, horizontal scrolling is permitted while preserving all 30 daily observations. Weekly aggregation, dropped dates, or changed statistic meaning are not permitted as a narrow-screen workaround.

### 12.2 Exact daily rows

- 7-day focused views show seven calendar rows and start `Daily values` expanded.
- 30-day focused views contain thirty calendar rows and start `Daily values` collapsed.
- Dates with no Logs remain visible as neutral `No logs`/unavailable rows.
- A subtle checkmark may identify Complete dates without reward/success coloring.
- If a chart date is selected while Daily values are collapsed, preserve that selected date when the section is later opened.
- Opening a daily row navigates to the exact Daily Log date.

Focused detail does not support swipe-left/right nutrient switching in initial Epic 4. Back returns to Nutrition Details at the prior group/scroll state.

## 13. Current target/reference presentation

History may display current target/reference context without changing historical intake data.

- Target changes update the current-reference lens immediately.
- Target changes must not invalidate/refetch the historical intake range solely because the target changed.
- The mini overview cards use compact numeric target/reference context only.
- The focused chart may include a horizontal current-reference line.
- No automatic previous-period comparison is included.
- No `improving`, `worsening`, `good week`, `bad week`, `on track`, `off track`, adherence, or reward language is included.

## 14. Loading, cache, refresh, and stale-response behavior

History data shown under a date-range label must belong to that exact range and selected authority.

- When paging to a different range, do not leave prior-range values visible beneath the new range label.
- Keep range/navigation chrome visible and use lightweight analytical-content loading state.
- If refreshing the same range fails and a valid same-range cache exists, retain the cached values and show a compact refresh-failure/retry indication such as `Couldn't refresh · Retry`.
- A persistent `last updated` timestamp is not required.
- Cached data from another range or another application-data authority must never satisfy the request.
- Rapid paging is allowed; late superseded responses must not overwrite the newest selected range.
- A Log or Complete mutation invalidates cached History ranges containing the affected date.
- Moving an entry invalidates ranges containing either source or destination date.
- Unrelated historical ranges need not be flushed.
- A target change refreshes only target/reference context.
- A remote range failure with no valid same-range remote cache shows Retry/error; it must not fall back to SQLite.

## 15. Manual Food authoring refinement

The expanded canonical nutrient catalog must remain available without forcing every nutrient onto the ordinary Food form.

For new manual Foods, the default fields after serving information follow familiar conventional Nutrition Facts order:

1. Calories;
2. Total Fat;
3. Saturated Fat;
4. Trans Fat;
5. Cholesterol;
6. Sodium;
7. Total Carbohydrate;
8. Dietary Fiber;
9. Total Sugars;
10. Added Sugars;
11. Protein;
12. Vitamin D;
13. Calcium;
14. Iron; and
15. Potassium.

Additional canonical nutrients are available through grouped `More nutrients` disclosure using:

- Vitamins;
- Minerals; and
- Fatty Acids.

Requirements:

- a newly added extended nutrient begins `unknown`, not zero;
- existing Foods continue to show already populated extended nutrients when edited;
- create and edit use the same grouped discovery model;
- an explicit source `0` may be stored as zero;
- clearing/not knowing a field leaves it unknown;
- absence from a source label does not auto-fill zero; and
- a `not a significant source` regulatory statement does not become exact zero automatically.

This is an authoring usability contract, not regulatory-label certification.

## 16. Runtime/read requirements

Epic 4 adds one bounded History range read inside the existing Daily Logs capability.

Product-level requirements:

- one authoritative range operation for 7/30-day History rather than N daily network requests;
- maximum initial range length of 30 calendar dates;
- response includes every calendar date in the requested range, including dates with no Logs;
- response includes enough per-date aggregate nutrient evidence for all canonical nutrients, not just the four overview nutrients;
- response includes Complete state and first-logged-date bounds metadata;
- the same payload supports Complete-day and Logged-day projections without another authoritative read;
- local and remote authorities expose equivalent semantics; and
- the client/shared projection layer calculates averages from the returned daily evidence consistently.

The normative technical contract is defined in [data-contracts.md](data-contracts.md).

## 17. Explicit non-goals

Initial Epic 4 excludes:

- a fourth bottom-navigation tab;
- Today in History;
- 90-day range;
- arbitrary custom date ranges;
- historical target/profile versioning;
- automatic previous-period comparisons;
- coaching, recommendations, adherence scoring, streaks, or reward systems;
- inferred meal/consumption times;
- per-meal analytics;
- contributor/source ranking such as top foods for sodium;
- a dedicated data-quality diagnostic screen;
- manual Complete retraction after assertion;
- swiping between focused nutrients;
- HealthKit, weight, exercise, medication, or other new health-data domains;
- synchronization or multi-device merge;
- fallback between local and remote authorities;
- Android OCR work;
- comprehensive accessibility-specific chart product requirements or dedicated accessibility settings; and
- regulatory Nutrition Facts label authoring/certification.

Deferred options remain in [Future Product and Scalability Options](../../future-product-and-scale.md).

## 18. Acceptance and qualification gates

Epic 4 is not complete until implementation proves:

- Complete-state migration creates no historical backfill;
- Complete persistence is date-owned and authority-isolated;
- nutrition-changing mutations and Complete invalidation are atomic;
- remote Complete reconciliation is deterministic under indeterminate responses;
- backup/restore preserves Complete state;
- one-time PostgreSQL-to-SQLite transfer preserves Complete state without creating synchronization;
- 7/30-day local and remote range reads are semantically equivalent;
- exact-decimal aggregation/average behavior matches across authorities;
- known, estimated, explicit zero, unknown-only, and no-Log states remain distinct;
- Complete-day and Logged-day denominator calculations match the contract;
- a Complete day with no usable selected-nutrient number is excluded from that nutrient's numeric denominator;
- DST/month/year boundaries preserve calendar-date semantics;
- first-logged-date partial-window and no-history behavior are correct;
- target changes alter only current-reference presentation;
- rapid paging cannot be overwritten by stale responses;
- same-range stale-cache failure behavior is honest;
- local/remote authority isolation and no-fallback behavior are preserved;
- 30-day charts are physically usable on the target iPhone, with horizontal scrolling introduced only if static bars fail qualification;
- the Nutrition Details surface and focused drill-down preserve navigation state; and
- manual Food authoring preserves unknown-versus-zero semantics while reducing default catalog density.

A parity fixture must deliberately cover difficult states rather than only ordinary fully populated days.

## 19. Authorization boundary

This PRD freezes Epic 4 product scope. New ideas discovered during implementation belong in the future-product register unless they are required to satisfy an invariant or acceptance criterion in this document.

Implementation may begin only after:

1. the [architecture review](architecture-review.md) approves the PRD and [data contracts](data-contracts.md);
2. the [implementation backlog](implementation-backlog.md) is complete and internally consistent; and
3. repository documentation validation and project audit pass for the resulting planning package.
