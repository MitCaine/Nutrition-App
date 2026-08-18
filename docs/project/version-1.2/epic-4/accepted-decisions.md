# Epic 4 — accepted planning decisions

> **Document role: Pre-Grill Decision Record.** This records product choices accepted during Epic 4 planning. It refines the working recommendations in `planning.md`; it is not a Feature PRD, architecture approval, implementation backlog, or authorization to change application behavior.
>
> **Decision snapshot:** 2026-08-18.

## Accepted direction

### E4-D1 — History remains owned by Daily Log

Nutrition History should be a dedicated route under the Daily Log tab rather than a fourth bottom-navigation tab in the initial implementation.

The Daily Log remains the primary place to record and inspect a day. History is an analysis route over that authoritative Daily Log history.

### E4-D5 — Day completion is explicit and visible

A lightweight user-confirmed `Complete` state is accepted as the preferred way to distinguish a deliberately finished day from a day that merely contains some Logs.

The `Complete` control should live in the sticky Daily Log header so that the state remains visible while scrolling without consuming additional vertical space in the meal flow.

Working semantics for later Grill/architecture confirmation:

- `Complete` is a user assertion about logging coverage, not a nutrient-data-quality claim.
- The control does not lock the day or prevent later edits.
- An unchecked day means **not confirmed complete**, not automatically `Incomplete`.
- `Complete` may be asserted for Today as well as past dates when the user has finished logging.
- A nutrition-affecting Log mutation should clear the completion assertion for every affected date so the user can reconfirm the changed day.
- Moving an entry should clear completion for both source and destination dates.
- A meal-label or note-only change does not inherently change nutritional completeness and should not clear completion solely for that reason.
- Empty dates should not be treated as confirmed zero-consumption days merely because they contain no Logs. A future explicit fasting/no-intake concept would require separate semantics if ever needed.

### Logging-first Daily Log information hierarchy

The expanded nutrient catalog exposed a product hierarchy problem: the Daily Log currently places full target progress and full nutrient totals before the meal entries and `Add Food` actions. As the catalog grew, the main logging workflow became buried under analysis.

The accepted direction is **logging first, analysis one interaction away**.

The Daily Log should prioritize:

1. sticky header with `Complete` state and Settings;
2. date-navigation row with `Previous Day`, `History`, and `Next Day`;
3. selected-date heading and direct date selection;
4. a compact nutrition summary;
5. a compact `View Nutrition` action; and
6. meal entries with meal-level `Add Food` actions.

`History` should occupy the currently unused center space between `Previous Day` and `Next Day` rather than consuming another row below the nutrition summary. This placement also matches its meaning: History is navigation across dates. `View Nutrition` stays with the compact nutrition summary because it opens deeper analysis of the currently selected date.

The complete nutrient catalog should no longer sit between the selected date and the meal logging workflow.

The compact nutrition summary is accepted as four fixed rows in the initial implementation:

- Calories;
- Protein;
- Carbohydrate; and
- Fat.

The compact summary should favor concise numeric presentation rather than progress bars. Where a target exists, the row may show `consumed / target`; if a value is amount-only, the row shows the consumed amount without inventing a denominator.

Do not add arbitrary nutrient pinning/configuration to the compact Daily Log summary in the initial Epic. The point of this surface is to remain bounded as the canonical catalog grows.

### Daily Nutrition becomes a deliberate detail surface

The current full `Target Progress` and `Totals` sections substantially overlap. The accepted direction is to consolidate full-day nutrient inspection into one coherent `Daily Nutrition` route rather than displaying the entire catalog twice in the Daily Log.

The resulting conceptual structure is:

```text
Daily Log
├── meals and logging for one date
├── Daily Nutrition
│   └── complete nutrient analysis for one date
└── Nutrition History
    └── nutrient analysis across dates
```

Daily Nutrition should preserve the existing canonical nutrient grouping and hierarchy because this is the surface where exhaustive nutrient information is intentional rather than obstructive.

Working row semantics:

- recommended/custom target available: show `consumed / target`, with percentage where useful;
- limit available: show consumed and limit using direction-aware presentation;
- amount-only nutrient: show consumed amount only;
- ignored nutrient: omit from ordinary Daily Nutrition presentation;
- unknown contributors: do not show ordinary warning styling or verbose per-row unknown-source text;
- fully unavailable/unknown total: use a neutral unavailable presentation such as an em dash rather than `Incomplete data`.

The current separate `Target Progress` and `Totals` blocks should not survive merely for backward visual compatibility if one coherent Daily Nutrition presentation can express both meanings without losing target authority or unknown-versus-zero semantics.

### Nutrition History overview and nutrient detail

The initial History information architecture is accepted as overview first, nutrient detail second.

The History overview should provide:

1. a `7 Days` / `30 Days` range control;
2. the selected date range;
3. logging-coverage/completion summary;
4. Calories, Protein, Carbohydrate, and Fat period summaries;
5. one small daily bar chart for each of those four overview nutrients; and
6. a `View Another Nutrient` action that opens the grouped canonical nutrient catalog.

The four overview nutrient cards remain structurally present even when one nutrient lacks usable data for the selected denominator. Use a neutral unavailable state rather than removing cards and shifting the page structure.

Selecting an overview nutrient or another nutrient should open a focused nutrient-history view containing:

- nutrient name and canonical unit;
- period average with an explicit denominator/coverage meaning;
- current target/reference context when available;
- one daily bar per calendar date;
- exact daily values; and
- direct navigation from a date back to that exact Daily Log.

The chart remains supplementary. Exact textual values and accessible selection must remain available without relying on bar height or color alone.

### Initial History range behavior

The initial implementation should support `7 Days` and `30 Days` only.

By default, History ends on yesterday rather than Today. For example, opening a 7-day History on August 18 shows August 11 through August 17. This prevents an unfinished current day from silently depressing a historical average and keeps the Daily Log responsible for the in-progress current date.

Today is excluded from the initial Epic 4 History model rather than being an optional History endpoint. `Complete` may still be asserted on Today in the Daily Log; that state becomes relevant once the day is historical.

A 90-day or arbitrary custom range is deferred until real use shows that the initial 7/30-day model is insufficient.

Thirty-day presentation should retain daily observations rather than silently switching the statistic to weekly averages. Exact chart mechanics may adapt to available screen width, but the data meaning should remain one point/bar per calendar day unless a later explicit product decision introduces aggregation.

### History period paging and navigation context

The selected period should be pageable without requiring a custom date-range picker.

- In `7 Days` mode, Previous and Next move the selected window by exactly seven calendar days.
- In `30 Days` mode, Previous and Next move the selected window by exactly thirty calendar days.
- Next never advances beyond the most recent supported History endpoint, which is yesterday in the initial model.
- The selected range and 7/30-day mode should survive navigation into nutrient detail and back.
- If the user opens a Daily Log from a History date and returns, History should restore the prior selected range, nutrient/detail context where practical, and scroll/focus position rather than resetting to the latest seven days.

This keeps older history reachable through a predictable calendar model while avoiding a heavier custom-range interaction in the initial Epic.

### History chart type

Discrete daily bars are accepted as the initial chart form rather than a connected line.

Daily intake is a discrete calendar-day observation. A connected line implies continuity/interpolation between days and can visually bridge missing dates in a misleading way.

The chart model must preserve distinctions among:

- a date with no logs;
- an explicit nutrient zero;
- a known amount;
- an estimated amount;
- unknown contributors; and
- the optional user-confirmed day-completion state.

Missing dates should remain gaps rather than zero-height consumption bars.

For 30-day mode, the working presentation should remain a static chart if thirty narrow daily bars are readable on physical devices. Do not introduce horizontal scrolling by default merely because there are thirty observations. Sparse date labels are acceptable. Horizontal chart scrolling or another interaction should be introduced only if real-device qualification demonstrates that the static chart is not usable or accessible.

### History averaging and Complete-day behavior

History must label what its average actually means.

If no accepted Complete-day denominator is available, use language such as `Logged-day average` with the logged-day count. Do not call that value `average intake` because the app cannot know that partially logged days represent all intake.

When Complete days exist, the preferred primary statistic is `Complete-day average` with the number of complete days shown. A lightweight control should allow switching between Complete days and all logged days rather than displaying competing averages simultaneously. If no days are Complete, History automatically uses Logged days rather than presenting an empty Complete-day statistic.

Do not impose an arbitrary minimum-day threshold before displaying a mathematically valid average. If only one Complete day is present, display the result with the denominator made explicit, for example `Complete-day average · 1 complete day`. The application should expose the evidence rather than decide that a small sample is meaningful or meaningless on the user's behalf.

Exact daily rows should make completion participation inspectable with a subtle state marker, such as a checkmark beside dates marked Complete. This should not become success coloring, streak framing, or visual reward. Overview charts do not need completion markers on every bar unless usability testing demonstrates that they materially help.

Completion state is intended to improve denominator honesty, not to create an adherence score or reward/streak system.

### Current target/reference context is a lens, not historical goal state

History may compare the selected nutrient against the **current** effective target/reference, but must label the authority honestly: for example `Current target`, `Current custom target`, `Current DRI`, or `Current Daily Value`.

The existing target configuration is mutable current state and is not an immutable historical goal stream. Epic 4 should not draw a historical-looking target line and imply the same target was configured on every past date.

Historical target versioning is deferred unless a later product decision explicitly needs `what was my target at the time?` semantics.

### No automatic trend judgments or period comparison in initial Epic 4

History should expose chronology and period statistics without labels such as `improving`, `worsening`, `good week`, `bad week`, `on track`, `off track`, or adherence scores.

A chronological chart is itself a trend view. The application should not manufacture behavioral conclusions merely because the Epic is named Nutrition History and Trends.

The initial Epic also should not add automatic comparisons such as `+8% vs previous week` or `142 kcal below previous 7 days`. Those comparisons are easy to calculate but introduce a second denominator/completeness problem and an additional interpretation layer. Previous-period comparison may be reconsidered later after the basic 7/30-day history model has been used and qualified.

### Unknown nutrient data is valid state, not an ordinary error

The existing four-state nutrient distinction remains authoritative:

- `known`;
- `estimated`;
- `zero`; and
- `unknown`.

Unknown must not be converted to explicit zero simply to remove warnings or simplify presentation. A missing amount and a measured/declarable zero are not equivalent, and Daily Log snapshots must not persist invented zeros into immutable history.

However, normal unknown nutrient information should also stop being presented as though the user made an error.

Accepted presentation direction:

- Ordinary Daily Log and Daily Nutrition rows do not need repeated `Incomplete data` warnings merely because one contributing Food has an unknown nutrient value.
- Ordinary rows also do not need verbose suffixes such as `1,400 mg + unknown from 1 food`.
- The app should normally show the useful known logged amount without warning styling.
- Unknown-contributor metadata remains preserved internally so aggregation/history logic does not silently reinterpret unknown as zero or claim unsupported precision.
- Uncertainty should be surfaced only when it materially changes an action or claim, or in an explicit data-quality/detail surface if one is later justified.
- OCR confirmation remains different: if recognition encountered information that appears to be present on the source label but could not resolve it, directed review can remain actionable before Food creation. Once a Food has legitimately been saved with unknown nutrient data, ordinary logging should not repeatedly nag the user about it.

### New Food authoring should not expose the entire nutrient catalog by default

The expanded canonical nutrient catalog should remain available without forcing every nutrient onto the primary manual Food-entry screen.

The default manual-entry set should correspond to the common conventional U.S. Nutrition Facts panel: Calories plus the routinely required label nutrients. Additional canonical nutrients should be reachable through an `Add nutrient` / `More nutrients` interaction.

For the current U.S. Nutrition Facts format, the routinely required nutrient set includes total fat, saturated fat, trans fat, cholesterol, sodium, total carbohydrate, dietary fiber, total sugars, added sugars, protein, vitamin D, calcium, iron, and potassium, alongside Calories and serving information. FDA simplified-label rules can permit some nutrients to be omitted when the product is not a significant source, so an absent field still must not be interpreted automatically as literal zero.

Manual-entry semantics:

- A value displayed as `0` on the source label may be entered as explicit `zero`.
- A field the user does not know remains `unknown`.
- An absent field is not auto-filled with `0`.
- A simplified-label statement such as `Not a significant source of ...` should not be silently converted into exact zero; the statement describes a regulatory declaration threshold, not necessarily literal absence of the nutrient.
- The user should not be required to search through the extended vitamin/mineral/fatty-acid catalog merely to enter an ordinary Nutrition Facts panel.

### History retains uncertainty semantics without visual overload

Epic 4 history calculations must continue to distinguish missing dates, explicit zero, estimated values, unknown contributors, and logging-completion state internally.

That does not require every uncertainty marker to be printed beside every value. The UI should favor concise values and explicit denominator/coverage wording, using uncertainty metadata to prevent false claims rather than turning every row into a warning surface.

For example, history can accurately describe a statistic as a `logged-day average` or `complete-day average` based on the accepted denominator without annotating each nutrient row with the number of Foods that lacked that nutrient.

## Remaining open Epic 4 choices

The first Grill batch resolved the primary Daily Log/History behavior. Remaining Grill/architecture choices are narrower implementation semantics rather than unresolved feature direction:

- exact sticky-header control styling and accessible state wording for `Complete`;
- exact mutation classes that clear a Complete assertion, including edge cases around serving-equivalent edits;
- exact 30-day chart sizing/label mechanics on narrow screens while preserving one-day-per-observation meaning;
- whether a dedicated data-quality detail surface is useful after ordinary unknown warnings are removed;
- exact Food-form grouping/order for the default Nutrition Facts subset and extended nutrient picker;
- whether period contributor ranking is valuable enough for a later follow-up; and
- whether 90-day/custom ranges merit a later expansion after 7/30-day real-device use.

## Regulatory reference used for the default Nutrition Facts subset

The planning decision above uses current FDA Nutrition Facts guidance as a product-entry reference, not as an attempt to make Nutrition App a regulatory-label-authoring tool. The application records nutrition supplied by the user/source; it does not certify label compliance.

Relevant FDA references:

- <https://www.fda.gov/food/nutrition-facts-label/daily-value-nutrition-and-supplement-facts-labels>
- <https://www.fda.gov/food/nutrition-food-labeling-and-critical-foods/industry-resources-changes-nutrition-facts-label>
