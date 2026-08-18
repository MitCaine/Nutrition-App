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

The design rule is **logging first, analysis one interaction away**. The expanded nutrient catalog must not again be allowed to bury the primary logging workflow.

## Daily Log

The accepted Daily Log hierarchy is:

1. sticky header with `Complete` and Settings;
2. date-navigation row: `Previous Day | History | Next Day`;
3. selected-date heading and direct date selection;
4. compact Calories / Protein / Carbohydrate / Fat summary;
5. compact `View Nutrition` action; and
6. meal sections with meal-level `Add Food` actions.

`History` uses the existing center space between Previous Day and Next Day. `View Nutrition` remains attached to the selected day's compact nutrition summary.

The four summary nutrients are fixed for the initial Epic. Do not add pinning or arbitrary nutrient customization to this surface. Use concise numeric rows rather than progress bars or percentages. Where a meaningful target exists, show `consumed / target`; amount-only nutrients show consumed amount only.

On an empty Daily Log date, the compact summary may show `0` logged for Calories, Protein, Carbohydrate, and Fat. In this context zero means **nothing has been logged**, not a claim that the user consumed zero. History preserves the stronger distinction: an entirely unlogged historical date remains missing rather than becoming a zero-consumption observation.

## Complete state

`Complete` is a user assertion that the day's food logging is finished. It is not a nutrient-data-quality assertion and does not lock the day.

Accepted semantics:

- compact labeled sticky-header control such as `☐ Complete` / `✓ Complete`, with explicit checked state and adequate touch target;
- available for Today and past dates containing at least one Log;
- unavailable for empty dates;
- unchecked means **not confirmed complete**, not `Incomplete`;
- nutrition-affecting Log mutations clear Complete automatically without an extra confirmation prompt;
- moving an entry clears Complete for both source and destination dates;
- deleting the last entry clears Complete because the day becomes empty;
- note-only and meal-label-only edits preserve Complete because they do not change nutrition;
- later edits to the source Food or Recipe do not clear historical Complete state because historical Daily Log nutrition remains owned by the immutable stored snapshot;
- a serving/amount edit that produces an exactly unchanged resulting nutrient snapshot preserves Complete, while any resulting nutrient-snapshot change clears it; and
- an empty date never implies confirmed zero intake. A future fasting/no-intake concept would require separate semantics.

## Daily Nutrition

The current full `Target Progress` and `Totals` blocks should be consolidated into one coherent Daily Nutrition route rather than showing the entire catalog twice.

Daily Nutrition:

- describes the date selected in Daily Log and displays that date prominently;
- inherits the selected date from Daily Log rather than owning a second calendar/date-selection state;
- returns to that same Daily Log date;
- does not need its own Previous/Next Day controls initially;
- preserves canonical nutrient grouping and hierarchy;
- uses collapsible sections, expanded by default;
- preserves section collapse state while the current navigation/session context remains active, but a fresh application session returns to the intentional expanded-by-default state;
- owns the secondary `Nutrition targets` action rather than leaving target configuration on the primary Daily Log;
- shows `consumed / target` and percentage where meaningful;
- preserves direction-aware presentation for limits without success/failure framing;
- shows consumed amount only for amount-only nutrients;
- hides ignored nutrients;
- does not show ordinary `Incomplete data` warnings or verbose unknown-source suffixes; and
- uses a neutral unavailable presentation such as `—` when no usable total exists.

Do not use strong red/green judgment framing merely because a nutrient is above or below a target/reference. The UI may distinguish factual target/limit context, but it should not turn nutrition analysis into a pass/fail dashboard.

## Unknown, estimated, zero, and missing data

The existing four-state nutrient semantics remain authoritative:

- `known`;
- `estimated`;
- `zero`; and
- `unknown`.

Unknown must never be auto-converted to zero merely to simplify the UI. Daily Log snapshots must not persist invented zeros into immutable history.

Normal unknown contributors should usually remain visually quiet. The application preserves uncertainty internally so calculations cannot silently reinterpret unknown as zero or claim unsupported precision, but ordinary Daily Log/Daily Nutrition rows do not need warning coloring, `Incomplete data`, or text such as `1,400 mg + unknown from 1 food`.

Estimated values remain distinct internally. Focused nutrient-history views may distinguish estimated contribution subtly when it materially helps interpret an exact daily value; the four-macro overview should not acquire routine estimation decoration unless the displayed value materially depends on estimation.

Epic 4 does not add a dedicated data-quality screen. Preserve the metadata and surface it only where it changes an action or mathematical claim. A separate diagnostic surface can be reconsidered later if real use demonstrates value.

OCR confirmation remains different: unresolved source-label information can remain actionable before Food creation. Once a Food is legitimately saved with unknown nutrient data, ordinary logging should not repeatedly nag the user about it.

## Manual Food nutrient authoring

New manual Foods should not expose the entire canonical nutrient catalog by default.

The default set follows the familiar conventional U.S. Nutrition Facts information set: Calories and routinely required label nutrients. Additional canonical nutrients remain available through an `Add nutrient` / `More nutrients` interaction.

The default field order follows the familiar Nutrition Facts hierarchy after serving information: Calories; Total Fat with Saturated Fat and Trans Fat; Cholesterol; Sodium; Total Carbohydrate with Fiber, Total Sugars, and Added Sugars; Protein; then Vitamin D, Calcium, Iron, and Potassium.

`More nutrients` should use the same broad grouped vocabulary used elsewhere in the app rather than another giant flat list. Additional entry is organized into `Vitamins`, `Minerals`, and `Fatty Acids` groups while the ordinary Nutrition Facts fields remain immediately available on the main authoring surface.

A newly added extended nutrient begins as `unknown`, not zero. Choosing to expose Magnesium, Vitamin K, or another nutrient field means the user wants the opportunity to enter it; it does not assert that the Food contains none of that nutrient.

Food edit uses the same grouped nutrient-discovery model as Food create. Existing populated nutrient fields remain visible, while absent extended nutrients are found through the same grouped `More nutrients` interaction rather than through a separate edit-only catalog.

An explicit `0` on the source may be stored as `zero`. An unavailable or absent field remains `unknown`; absence is not auto-filled with zero. A regulatory `not a significant source` statement is not silently converted into literal zero.

This product-entry reference does not make Nutrition App a regulatory-label-authoring or certification tool.

## History range model

Initial History supports only:

- `7 Days`; and
- `30 Days`.

History ends on yesterday. Today remains the in-progress Daily Log/Daily Nutrition date even if Today has been marked Complete.

Whole-period paging is accepted:

- Previous/Next moves exactly 7 calendar days in 7-day mode;
- Previous/Next moves exactly 30 calendar days in 30-day mode;
- Next never advances past the most recent period ending yesterday; and
- 90-day/custom ranges are deferred until real use demonstrates a need.

History state should survive drill-down and return: selected range, selected 7/30 mode, denominator mode, detail-card state, expanded groups, scroll/focus position, and focused nutrient context where applicable.

The denominator mode is global for the current History view. Switching between Complete days and Logged days recalculates the four overview cards, Nutrition Details card, and focused nutrient views together; different nutrients should not silently use different denominator modes.

If a selected range contains no Logs at all, keep the period controls available but replace the four empty macro cards with a dedicated empty-period state such as `No food was logged during this period.`

If the selected range contains Logs but no Complete days, hide the Complete/Logged selector and use `Logged-day average`. Once at least one Complete day is available, expose the selector and default to Complete days.

If Daily Log nutrition or Complete state changes while History remains in the navigation stack, returning to History refreshes/recalculates the affected data without resetting the user's analysis context. Preserve the selected period, 7/30-day mode, denominator, detail-card/section state, focused nutrient context, and scroll position where practical.

## History overview

The primary History overview always contains four analytical cards when the selected period contains logged history:

- Calories;
- Protein;
- Carbohydrate; and
- Fat.

Each card contains the period statistic and a small discrete daily bar chart. The four cards remain structurally present even when one has no usable nutrient value; use a neutral unavailable state rather than removing it.

History uses discrete bars, not connected lines. Daily intake is a discrete calendar observation and missing dates must remain gaps rather than zero-height intake bars.

The four small overview charts omit target/reference lines to keep them visually sparse. Where current target/reference context is useful, present it numerically in the surrounding card. The focused nutrient view owns the explicit horizontal current-reference line.

Thirty-day mode retains one observation per calendar day. Prefer a static 30-bar chart if physical-device testing shows it remains readable; do not add horizontal chart scrolling by default. Sparse date labels are acceptable. Change the interaction only if real-device qualification demonstrates that the static chart is unusable.

Selecting a bar highlights/reveals its exact date and value rather than immediately navigating away. Textual daily rows provide deliberate navigation to the exact Daily Log date. Seven-day detail has seven rows; 30-day detail has thirty rows. Dates with no Logs remain visible as `No logs`/neutral unavailable rows.

Dedicated accessibility-specific chart behavior and accessibility qualification are not part of initial Epic 4 scope. They are retained as future product work rather than expanding this Epic.

## Show more nutrition — distinct detail card

The original in-place expansion proposal was rejected because it would show duplicated macro information simultaneously and would make the History overview unnecessarily long.

`Show more nutrition` instead opens a **distinct Nutrition Details card/surface** over/from History. While this detail card is active, the four overview macro charts are not simultaneously visible.

That separation allows the detail card to preserve a complete familiar Nutrition Facts hierarchy without visual redundancy.

The detail card approximately follows this information structure while retaining Nutrition App's normal theme, typography, spacing, and interaction conventions rather than imitating a physical FDA label:

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

- Nutrition Facts starts expanded;
- Vitamins, Minerals, and Fatty Acids start collapsed;
- sections use ordinary expandable cards/accordions, not swipe-only category pages;
- expanded/collapsed state persists while the user remains in History and when drilling into a nutrient and back;
- the selected History period and denominator are inherited by the detail card;
- each nutrient row remains present even when no usable value exists, using neutral `—` rather than disappearing;
- rows stay compact and do not embed a chart for every nutrient;
- rows show the relevant period value and current target/reference context where meaningful; and
- selecting a nutrient opens its focused nutrient-history view.

A compact row can therefore look conceptually like `Sodium 1,824 / 2,300 mg >`; the focused view owns the full chart rather than inflating the grouped card.

Focused nutrient detail remains one nutrient at a time. It contains the period statistic, current reference context when applicable, daily bar chart, full date rows, and navigation to contributing Daily Log dates. Back returns to the Nutrition Details card at the prior scroll/expanded state; closing the card returns to the four-macro History overview at its prior state.

Do not add swipe-left/right between nutrients in the initial Epic. If physical use later shows repeated Back navigation is inefficient, adjacent-nutrient navigation can be reconsidered deliberately.

## Focused nutrient chart semantics

Focused nutrient charts use a true zero baseline. The vertical scale should extend from zero through at least the greater of the highest displayed daily value or the current target/reference line. Do not truncate the axis merely to magnify ordinary day-to-day variation.

When estimated contribution materially affects an exact daily value, the focused view may distinguish that state subtly. This must not turn estimates into warning-heavy presentation, and unknown contributors remain governed by the quiet-default policy above.

A current target/reference line may be shown when meaningful, but it remains explicitly labeled as current context rather than historical goal state.

## History averages and denominator honesty

History must state what an average actually represents.

- If no Complete days are available, use `Logged-day average` and show the logged-day count.
- When Complete days exist, default to `Complete-day average` and show the Complete-day count.
- Allow switching between Complete days and Logged days rather than showing competing averages at once.
- Do not impose an arbitrary minimum sample size. One usable Complete day may produce a mathematically valid average, but the denominator must be visible.
- Complete means logging coverage, not nutrient completeness. A Complete day with no usable numerical value for the selected nutrient does not participate in that nutrient's numeric average.
- Concisely disclose the numerical denominator, e.g. `Complete-day average · 4 days used`, rather than adding unknown-data warnings to every row.
- Exact date rows may use a subtle checkmark to show Complete days. Do not use success coloring, streaks, rewards, or adherence scoring.

## Current targets are comparison context, not historical goal state

The current target/profile configuration is mutable and is not a historical target stream.

History may show a current reference line/context when meaningful, but it must be labeled honestly, such as:

- `Current target`;
- `Current custom target`;
- `Current DRI`;
- `Current Daily Value`; or
- `Current limit`.

Do not imply that the current reference was configured on each historical date. Historical target versioning is deferred unless a future product decision explicitly requires it.

## No automatic behavioral interpretation

Initial Epic 4 does not add:

- `improving` / `worsening` labels;
- `good week` / `bad week`;
- `on track` / `off track`;
- adherence scores;
- streaks/rewards; or
- automatic previous-period comparisons such as `+8% vs previous week`.

Chronology plus exact period statistics is sufficient for the initial History feature.

## Remaining Grill/architecture questions

The first five Grill batches have resolved the primary product shape and most History semantics. Accessibility-specific product behavior has been explicitly deferred rather than treated as an Epic 4 requirement.

Remaining questions are increasingly implementation-focused, including:

- loading/error/stale-state behavior for range reads;
- performance/query boundaries for local and remote History projections;
- exact cache invalidation around Log and Complete mutations;
- exact card/modal presentation mechanics on iOS;
- whether contributor/source breakdown deserves later scope; and
- qualification boundaries for 7-day/30-day calculations and real-device chart readability.

## Regulatory reference used for the default Nutrition Facts subset

Relevant FDA references:

- <https://www.fda.gov/food/nutrition-facts-label/daily-value-nutrition-and-supplement-facts-labels>
- <https://www.fda.gov/food/nutrition-food-labeling-and-critical-foods/industry-resources-changes-nutrition-facts-label>
