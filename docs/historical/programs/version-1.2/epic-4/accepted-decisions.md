# Epic 4 — accepted planning decisions

> **Document role: Pre-Grill Decision Record.** This records product choices accepted during Epic 4 planning. It refines `planning.md`; it is not a Feature PRD, architecture approval, implementation backlog, or authorization to change application behavior.
>
> **Decision snapshot:** 2026-08-18.

## Accepted product structure

Epic 4 keeps History owned by the Daily Log tab. The product is intentionally split into three layers:

```text
Daily Log
├── fast meal logging for one date
├── Daily Nutrition
│   └── exhaustive nutrition for the selected date
└── Nutrition History
    └── multi-day nutrition analysis
```

The design rule is **logging first, analysis one interaction away**. The expanded nutrient catalog must not again bury the primary logging workflow.

History is an analysis/navigation surface, not another editing surface. It may navigate to the authoritative Daily Log date, but initial Epic 4 does not edit meals, delete Logs, or assert Complete directly from History.

## Daily Log

The accepted Daily Log hierarchy is:

1. sticky header with `Complete` and Settings;
2. date-navigation row: `Previous Day | History | Next Day`;
3. selected-date heading and direct date selection;
4. compact Calories / Protein / Carbohydrate / Fat summary;
5. compact `View Nutrition` action; and
6. meal sections with meal-level `Add Food` actions.

`History` uses the existing center space between Previous Day and Next Day. `View Nutrition` remains attached to the selected day's compact nutrition summary.

The four summary nutrients are fixed for the initial Epic. Do not add pinning or arbitrary nutrient customization. Use concise numeric rows rather than progress bars or percentages. Where a meaningful target exists, show `consumed / target`; amount-only nutrients show consumed amount only.

On an empty Daily Log date, the compact summary may show `0` logged for Calories, Protein, Carbohydrate, and Fat. In this context zero means **nothing has been logged**, not a claim that the user consumed zero. History preserves the stronger distinction: an entirely unlogged historical date remains missing rather than becoming a zero-consumption observation.

## Complete state

`Complete` is a durable user assertion that the day's food logging is finished. It is not a nutrient-data-quality assertion and does not lock the day.

Accepted semantics:

- Complete belongs to the authoritative Daily Log **calendar date**, not to an individual Log entry.
- The sticky-header control is compact and labeled, such as `☐ Complete` / `✓ Complete`, rather than an ambiguous icon-only action.
- Complete is available for Today and past dates containing at least one Log and unavailable for empty dates.
- Unchecked means **not confirmed complete**, not `Incomplete`.
- Existing historical Logs are not retroactively marked Complete when the feature ships; only explicit user assertions create the state.
- The control becomes visibly checked only after the selected authority confirms persistence. While saving it may show a brief busy state; a failed write leaves the date unchecked with retry/error handling.
- While a nutrition-changing mutation for the date is unresolved, Complete is temporarily unavailable so it cannot be asserted against stale nutrition state.
- A nutrition-affecting Log mutation clears Complete automatically without another confirmation prompt.
- The nutrition mutation and resulting Complete invalidation are one atomic authoritative operation: they succeed or fail together.
- Moving an entry clears Complete for both source and destination dates.
- Deleting the final entry clears Complete because the day becomes empty.
- Note-only and meal-label-only edits preserve Complete because they do not change nutrition.
- A serving/amount edit that produces an exactly unchanged resulting nutrient snapshot preserves Complete; any resulting nutrient-snapshot change clears it.
- Later edits to the source Food or Recipe do not clear historical Complete state because historical Daily Log nutrition remains owned by the immutable stored snapshot.
- Complete survives supported backup/restore and one-time authority-transfer flows with the authoritative Log history it describes.
- Later timezone/calendar-setting changes do not migrate a historical Complete assertion to another date; it remains attached to the authoritative Daily Log date originally marked Complete.
- An empty date never implies confirmed zero intake. A future fasting/no-intake concept would require separate semantics.

Complete is positive date-owned state rather than a persisted historical `false` classification for every date. Absence of an assertion means **not confirmed complete**. The architectural shape should be equivalent to a day-state record keyed by owner and authoritative calendar date rather than a redundant flag on every Log entry.

An asserted state should retain internal persistence metadata such as `completed_at` for deterministic durability/transfer/recovery evidence. Initial Epic 4 does not expose that timestamp as a behavioral metric, streak, or timing feature.

The migration introducing Complete state performs **no historical backfill**. New storage begins with no historical dates confirmed Complete.

Remote Complete writes participate in the existing deterministic Daily Log mutation/recovery model. If connectivity is lost after submission, the application determines whether the assertion committed rather than guessing, blindly retrying, or introducing a weaker mutation-consistency path for Complete.

Manual retraction of an already asserted Complete state is not required in initial Epic 4. It is retained as a qualified future option rather than treated as a current product requirement.

## Daily Nutrition

The current full `Target Progress` and `Totals` blocks should be consolidated into one coherent Daily Nutrition route rather than showing the entire catalog twice.

Daily Nutrition:

- describes the date selected in Daily Log and displays that date prominently;
- inherits the selected date from Daily Log rather than owning a second calendar/date-selection state;
- returns to that same Daily Log date;
- does not need its own Previous/Next Day controls initially;
- preserves canonical nutrient grouping and hierarchy;
- uses collapsible sections, expanded by default;
- preserves section collapse state while the current navigation/session context remains active, but a fresh app session returns to the expanded-by-default state;
- owns the secondary `Nutrition targets` action rather than leaving target configuration on the primary Daily Log;
- shows `consumed / target` and percentage where meaningful;
- preserves direction-aware presentation for limits without success/failure framing;
- shows consumed amount only for amount-only nutrients;
- hides ignored nutrients;
- does not show ordinary `Incomplete data` warnings or verbose unknown-source suffixes; and
- uses a neutral unavailable presentation such as `—` when no usable total exists.

Do not use strong red/green judgment framing merely because a nutrient is above or below a target/reference. The UI may distinguish factual target/limit context, but it should not become a pass/fail dashboard.

## Unknown, estimated, zero, and missing data

The existing four-state nutrient semantics remain authoritative:

- `known`;
- `estimated`;
- `zero`; and
- `unknown`.

Unknown must never be auto-converted to zero merely to simplify the UI. Daily Log snapshots must not persist invented zeros into immutable history.

Normal unknown contributors should usually remain visually quiet. Preserve uncertainty internally so calculations cannot silently reinterpret unknown as zero or claim unsupported precision, but ordinary Daily Log/Daily Nutrition rows do not need warning coloring, `Incomplete data`, or text such as `1,400 mg + unknown from 1 food`.

Estimated values remain distinct internally. Focused nutrient-history views may distinguish estimated contribution subtly when it materially helps interpret an exact daily value; the four-macro overview should not acquire routine estimation decoration unless the displayed value materially depends on estimation.

Epic 4 does not add a dedicated data-quality screen. Preserve the metadata and surface it only where it changes an action or mathematical claim. OCR confirmation remains different because unresolved source-label information can remain actionable before Food creation.

## Manual Food nutrient authoring

New manual Foods should not expose the entire canonical nutrient catalog by default.

The default set follows the familiar conventional U.S. Nutrition Facts information set: Calories and routinely required label nutrients. Additional canonical nutrients remain available through an `Add nutrient` / `More nutrients` interaction.

The default field order follows the familiar Nutrition Facts hierarchy after serving information: Calories; Total Fat with Saturated Fat and Trans Fat; Cholesterol; Sodium; Total Carbohydrate with Fiber, Total Sugars, and Added Sugars; Protein; then Vitamin D, Calcium, Iron, and Potassium.

`More nutrients` uses the same broad grouped vocabulary used elsewhere in the app rather than another giant flat list. Additional entry is organized into `Vitamins`, `Minerals`, and `Fatty Acids` groups while the ordinary Nutrition Facts fields remain immediately available on the main authoring surface.

A newly added extended nutrient begins as `unknown`, not zero. Food edit uses the same grouped nutrient-discovery model as Food create. Existing populated nutrient fields remain visible, while absent extended nutrients are found through the grouped `More nutrients` interaction.

An explicit `0` on the source may be stored as `zero`. An unavailable or absent field remains `unknown`; absence is not auto-filled with zero. A regulatory `not a significant source` statement is not silently converted into literal zero.

This product-entry reference does not make Nutrition App a regulatory-label-authoring or certification tool.

## History range model

Initial History supports only:

- `7 Days`; and
- `30 Days`.

These are calendar-date ranges owned by the existing Daily Log calendar model. `7 Days` means seven authoritative Daily Log dates, not a rolling 168-hour interval; the same rule applies to 30-day History. DST and timezone boundaries therefore follow the Daily Log's date semantics rather than elapsed-hour windows.

History is independent of Log creation timestamps and consumption-time interpretation. Multiple entries on one authoritative calendar date contribute to that date regardless of the times at which they were created. Time-of-day nutrition analytics remain separate future scope.

History ends on yesterday. Today remains the in-progress Daily Log/Daily Nutrition date even if Today has been marked Complete.

Whole-period paging is accepted:

- Previous/Next moves exactly 7 calendar days in 7-day mode;
- Previous/Next moves exactly 30 calendar days in 30-day mode;
- Next never advances past the most recent period ending yesterday;
- the earliest partial period containing the first logged date remains reachable, with earlier dates in that period represented as missing;
- Previous is disabled once the next older period would be entirely before the first logged date; and
- 90-day/custom ranges are deferred until real use demonstrates a need.

The History range response exposes `firstLoggedDate`-equivalent bounds metadata so the client can determine the earliest useful period without probing progressively older empty windows. If the selected authority contains no Logs at all, `firstLoggedDate` is `null`; do not substitute install date, account date, or Today.

History state survives drill-down and return: selected range, selected 7/30 mode, denominator mode, detail-card state, expanded groups, scroll/focus position, and focused nutrient context where applicable.

A fresh app launch resets the selected History range to the most recent supported period ending yesterday rather than reopening an arbitrarily old date window. The app may preserve the user's preferred `7 Days` versus `30 Days` mode across launches.

The denominator mode is global for the current History view. Switching between Complete days and Logged days recalculates the four overview cards, Nutrition Details card, and focused nutrient views together.

The Complete/Logged toggle is a projection over the already loaded range payload. The payload must contain enough per-date information to calculate either denominator deterministically, so changing this lens is immediate and does not issue another SQLite/network range read.

If a selected range contains no Logs at all, keep the period controls available but replace the four empty macro cards with a dedicated empty-period state such as `No food was logged during this period.`

If the selected range contains Logs but no Complete days, hide the Complete/Logged selector and use `Logged-day average`. Once at least one Complete day is available, expose the selector and default to Complete days.

If Daily Log nutrition or Complete state changes while History remains in the navigation stack, returning to History refreshes/recalculates the affected data without resetting the user's analysis context.

Rapid period paging must not force the user to wait for every intermediate range request. The selected period may advance immediately, and late responses for superseded ranges must never overwrite the newest selected range.

Period paging remains available from the History overview, Nutrition Details surface, and focused nutrient view. Paging from detail preserves that detail context; paging from focused nutrient History keeps the user on the same nutrient for the newly selected period.

## History loading, cache, and refresh behavior

History data must always correspond to the date range currently shown in the UI.

- When paging to a different range, do not leave the prior range's analytical values visible under the new date label while the requested range loads. Keep the navigation/range chrome visible and use a lightweight loading state for analytical content.
- If refreshing the **same** range fails but valid cached data exists for that exact range, keep the cached values visible and show a compact refresh-failure/retry indication such as `Couldn't refresh · Retry`. Do not silently present cached data as freshly confirmed.
- A persistent `last updated` timestamp is not required in initial Epic 4 merely because same-range stale data can remain visible after refresh failure.
- Cached data from a different period must never be shown as though it belongs to the newly selected period.
- Latest-request-wins semantics are required for rapid paging so out-of-order responses cannot roll the user back to stale History data.
- Cache identity includes the selected application-data authority plus the exact start and end dates. Local and remote cache entries are never interchangeable.
- `Complete days` versus `Logged days` is not part of range cache identity because both are deterministic projections over the same evidence payload.
- A Log or Complete mutation invalidates cached History ranges that contain the affected date. Moving an entry invalidates ranges containing either source or destination date. Unrelated historical ranges need not be flushed.
- A Nutrition Target change does not invalidate/refetch historical intake ranges; it refreshes only the current-reference lens used to present already loaded history.

If a remote History range read fails and no valid cache exists for that exact remote range, show an explicit retry/error state. Do not fall back to SQLite or assemble a mixed-authority result.

## Runtime and authority boundary

Nutrition History remains part of the existing `Daily Logs` runtime capability. It is a projection over authoritative Daily Log snapshots and Complete metadata, not a ninth capability with an independent authority.

The History read contract is a bounded date-range operation rather than 7 or 30 independent per-day reads. Conceptually, the Daily Logs capability exposes one range read such as `getHistoryRange(startDate, endDate)`:

- local authority performs one bounded read from SQLite;
- remote authority performs one bounded FastAPI/HTTP read rather than N daily requests;
- local and remote implementations expose the same semantic contract;
- selecting remote authority must not change the meaning of an average or chart;
- no range may be assembled by mixing local and remote data;
- no fallback, dual-read, or shadow authority is introduced by History; and
- the initial contract rejects ranges larger than 30 calendar dates. Expanding that bound for future 90-day/custom History requires an explicit later decision.

The range payload is per-calendar-date evidence, not the entire individual Food/Log graph. Each returned date contains the aggregate nutrient values/status metadata needed for History, whether the date contains Logs, Complete state, and other bounded metadata necessary to preserve missing/known/estimated/zero/unknown semantics.

One loaded 7/30-day payload includes all canonical nutrient totals needed by the Nutrition Details surface and focused nutrient drill-down, not only Calories/Protein/Carbohydrate/Fat. The user should not incur another authoritative range read merely by opening Vitamins, Minerals, Fatty Acids, or a focused nutrient view.

Local and remote authorities produce the same per-date semantic contract. Complete-day averages, Logged-day averages, usable-day counts, gaps, and related period projections are computed by one shared History calculation layer rather than independently reinvented in SQLite and FastAPI.

## History calculation semantics

History calculations preserve existing exact-nutrition invariants rather than introducing presentation shortcuts.

- Aggregate and average authoritative exact-decimal values first; round only the final presentation value according to the nutrient's normal display precision. Do not round each day before averaging.
- Use the actual stored nutrient identity. Do not fabricate parent totals from child nutrients merely because some components are known; for example, do not derive Total Omega-3 from ALA/EPA/DHA or Total Fat from known subcomponents.
- Keep each nutrient's canonical display unit stable across the selected period. Do not alternate units by day merely because one value crosses a convenient display threshold.

## History overview

The primary History overview contains four analytical cards when the selected period contains logged history:

- Calories;
- Protein;
- Carbohydrate; and
- Fat.

Each card contains the period statistic and a small discrete daily bar chart. The four cards remain structurally present even when one has no usable nutrient value; use a neutral unavailable state rather than removing it.

History uses discrete bars, not connected lines. Missing dates remain gaps rather than zero-height intake bars.

The four small overview charts omit target/reference lines to keep them visually sparse. Where current target/reference context is useful, present it numerically in the surrounding card. The focused nutrient view owns the explicit horizontal current-reference line.

Thirty-day mode retains one observation per calendar day. Start with a static 30-bar chart if physical-device testing shows it remains readable. If physical-device qualification demonstrates that thirty static bars cannot make individual days meaningfully readable/selectable, horizontal chart scrolling is permitted while preserving all thirty daily observations. Do not solve narrow-screen pressure by aggregating days into weeks, dropping observations, or changing the statistic's calendar-day meaning.

Selecting a bar highlights/reveals its exact date and value rather than immediately navigating away. Textual daily rows provide deliberate navigation to the exact Daily Log date. Seven-day detail has seven rows; 30-day detail has thirty rows. Dates with no Logs remain visible as `No logs`/neutral unavailable rows.

Dedicated accessibility-specific chart behavior and accessibility qualification are not part of initial Epic 4 scope. They are retained as future product work.

## Show more nutrition — distinct detail card

`Show more nutrition` opens a **distinct Nutrition Details card/surface** over/from History. While this detail surface is active, the four overview macro charts are not simultaneously visible. This avoids simultaneous duplication while allowing the detail card to preserve a complete familiar Nutrition Facts hierarchy.

On iPhone, the card may present as an effectively full-height sheet/surface with its own header, Close control, and vertical scrolling rather than forcing dozens of rows into a cramped floating modal.

The detail card follows the familiar Nutrition Facts information hierarchy without trying to imitate a physical FDA label:

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

Accepted interaction:

- Nutrition Facts starts expanded.
- Vitamins, Minerals, and Fatty Acids start collapsed.
- Sections use expandable cards/accordions, not swipe-only category pages.
- Expanded/collapsed state persists while the user remains in History and when drilling into a nutrient and back.
- The selected History period and denominator are inherited by the detail card.
- Each nutrient row remains present even when no usable value exists, using neutral `—` rather than disappearing.
- Rows stay compact and do not embed a chart for every nutrient.
- Rows show the relevant period value and current target/reference context where meaningful.
- Selecting a nutrient opens its focused nutrient-history view.

Focused nutrient detail remains one nutrient at a time. Tapping a nutrient replaces the detail sheet's content with that nutrient's focused History view rather than stacking another modal. Back returns to the Nutrition Details card at the prior scroll/expanded state; closing the card returns to the four-macro History overview at its prior state.

Do not add swipe-left/right between nutrients in the initial Epic.

## Focused nutrient chart semantics

Focused nutrient charts use a true zero baseline. The vertical scale extends from zero through at least the greater of the highest displayed daily value or the current target/reference line. Do not truncate the axis merely to magnify ordinary variation.

When estimated contribution materially affects an exact daily value, the focused view may distinguish that state subtly. Unknown contributors remain governed by the quiet-default policy above.

A current target/reference line may be shown when meaningful, but it remains explicitly labeled as current context rather than historical goal state.

Focused views also provide exact per-date values:

- in `7 Days` mode, `Daily values` starts expanded;
- in `30 Days` mode, `Daily values` starts collapsed;
- selecting a chart bar selects/highlights the matching calendar date and exact value;
- if `Daily values` is collapsed, bar selection does not automatically force it open, but the selected date is retained if the user opens it; and
- paging Previous/Next Period keeps the user on the same nutrient.

## History averages and denominator honesty

History must state what an average actually represents.

- If no Complete days are available, use `Logged-day average` and show the logged-day count.
- When Complete days exist, default to `Complete-day average` and show the Complete-day count.
- Allow switching between Complete days and Logged days rather than showing competing averages at once.
- Do not impose an arbitrary minimum sample size.
- Complete means logging coverage, not nutrient completeness. A Complete day with no usable numerical value for the selected nutrient does not participate in that nutrient's numeric average.
- Concisely disclose the numerical denominator, e.g. `Complete-day average · 4 days used`, rather than adding unknown-data warnings to every row.
- Exact date rows may use a subtle checkmark to show Complete days. Do not use success coloring, streaks, rewards, or adherence scoring.

## Current targets are comparison context, not historical goal state

The current target/profile configuration is mutable and is not a historical target stream.

History may show a current reference line/context when meaningful, labeled honestly as `Current target`, `Current custom target`, `Current DRI`, `Current Daily Value`, or `Current limit`.

Changing current Nutrition Targets immediately updates this current-reference lens while leaving historical intake snapshots, bars, and averages unchanged. Do not imply that the current reference was configured on each historical date. Historical target versioning is deferred.

## No automatic behavioral interpretation

Initial Epic 4 does not add:

- `improving` / `worsening` labels;
- `good week` / `bad week`;
- `on track` / `off track`;
- adherence scores;
- streaks/rewards;
- automatic previous-period comparisons; or
- period-level contributor/source ranking such as `top foods for sodium`.

Chronology plus exact period statistics is sufficient for the initial History feature.

## Migration and durability qualification

The Complete-state migration and storage changes must explicitly qualify that:

- migration creates empty day-state storage without inferring Complete from existing Logs;
- local SQLite and remote PostgreSQL/FastAPI expose equivalent Complete semantics;
- backup/restore retains asserted Complete state;
- one-time authority transfer retains asserted Complete state without becoming synchronization;
- nutrition-changing mutations and Complete invalidation remain atomic within the selected authority;
- remote uncertain Complete writes resolve through deterministic mutation recovery; and
- historical immutable nutrition remains unchanged by adding Complete metadata.

## History qualification matrix

Qualification must use deliberate parity fixtures and failure cases rather than only ordinary populated days. At minimum, coverage should prove:

- known nutrient values;
- explicit zero;
- estimated values;
- unknown contributors without unknown-to-zero conversion;
- dates with no Logs;
- Complete and not-confirmed-complete dates;
- a one-usable-day average;
- mixed usable/unusable days for an individual nutrient;
- Complete-day versus Logged-day denominator projections from the same loaded evidence;
- exact-decimal aggregation before presentation rounding;
- 7-day and 30-day calendar boundaries;
- the earliest partial period and `firstLoggedDate = null` when no history exists;
- DST/calendar-date boundaries;
- current-target changes affecting only the comparison lens;
- local/remote semantic parity;
- migration with no historical Complete backfill;
- backup/restore and one-time transfer of Complete metadata;
- latest-request-wins behavior under stale/out-of-order remote responses;
- same-range cache behavior on refresh failure;
- no authority fallback on remote range-read failure; and
- physical-device qualification of 30-day chart readability, with horizontal scrolling allowed only if static daily bars fail usability while retaining all thirty observations.

## Grill complete and scope freeze

The Epic 4 Grill is complete. The accepted product scope is now frozen for conversion into the formal Feature PRD, architecture decision/data-contract documents, and bounded implementation backlog.

Implementation should not expand the product merely because another potentially useful idea appears during coding. New ideas go to `docs/project/future-product-and-scale.md` unless they are required to satisfy an already accepted Epic 4 invariant or qualification condition.

Before implementation is authorized, the accumulated planning changes should be reconciled into the formal documents and the repository documentation validator/project audit should be run. Do not assume the current planning-document set passes those checks merely because individual decision-record writes succeeded.

## Regulatory reference used for the default Nutrition Facts subset

Relevant FDA references:

- <https://www.fda.gov/food/nutrition-facts-label/daily-value-nutrition-and-supplement-facts-labels>
- <https://www.fda.gov/food/nutrition-food-labeling-and-critical-foods/industry-resources-changes-nutrition-facts-label>
