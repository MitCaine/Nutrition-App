# Epic 4 — Nutrition History and Trends planning

> **Document role: Pre-Grill Planning / Research Record.** This document gathers product research,
> current-repository constraints, reusable implementation surfaces, working recommendations, and
> unresolved decisions for Epic 4. It is not a Feature PRD, architecture approval, implementation
> backlog, or authorization to change application behavior.
>
> **Research snapshot:** 2026-08-18.

Epic 4 should turn the Nutrition App's already-trustworthy Daily Log snapshots into a compact,
inspectable multi-day view. The objective is not to create a coaching product or a general analytics
platform. The user should be able to answer questions such as: What did I actually log over the last
week or month? Which days are driving a nutrient high or low? How much of the period is based on
complete versus uncertain data? How does the logged pattern compare with the reference or target I
currently care about?

The central product constraint is that a multi-day chart must not destroy the semantic precision the
single-day product already has. Missing dates, explicitly zero values, estimated values, unknown
nutrient contributors, partially logged days, and target/reference changes are different states and
must not be flattened into a misleading line or average.

## Product preferences and planning constraints

The working plan should preserve the existing product direction:

- Keep the experience neutral and informational. Do not add coaching, adherence scores, warnings
  framed as success/failure, automatic diet recommendations, predictive goals, diagnoses, or
  medical interpretation.
- Prefer a compact overview with deliberate drill-down over a dense dashboard showing every nutrient
  at once.
- Preserve explicit unknown-versus-zero semantics and immutable historical nutrition.
- Keep target/reference authority visible rather than presenting every comparison as a personalized
  goal.
- Favor bounded, incremental changes that reuse current runtime capabilities and UI patterns instead
  of widening architecture merely because a chart is being added.
- Keep the feature useful without requiring weight, exercise, body measurements, HealthKit, or other
  new health-data domains.
- Historical analysis should help the user inspect their own data; the application should not tell
  the user whether a week was "good" or "bad."

## What the current Nutrition App already provides

Epic 4 does not need to invent a historical data model from scratch.

### Immutable daily nutrition substrate

Daily Logs already snapshot resolved nutrient values when an entry is created or nutrition-affecting
Log edits occur. Daily summaries aggregate only those immutable `daily_log_nutrient_snapshots`; they
never recalculate the past from current Food or Recipe definitions.

Each daily nutrient total already distinguishes:

- known amount;
- estimated amount;
- unit;
- whether unknown contributors exist; and
- unknown-contributor count.

This is a stronger basis for honest history than a simple daily calorie number.

### Existing daily target/reference semantics

The current target model already distinguishes:

- manual overrides;
- calculated calorie estimates;
- DRI recommendations;
- FDA Daily Values;
- amount-only nutrients;
- ignored nutrients;
- target, minimum, limit, reference, and unavailable directions; and
- unknown contributors in the consumed amount.

The existing Daily Log target-progress UI also already contains useful display behavior: exact
amount formatting, percentages, direction-aware limit attention, uncapped-overflow semantics,
unknown-data labeling, nutrient hierarchy, grouping, and accessibility labels.

However, target configuration is mutable current state. The runtime does not expose a historical
version stream of target/profile changes. A historical chart therefore must not draw a line and
claim "this was your goal on that date" unless Epic 4 deliberately adds a new target-history model.
The current implementation resolves stored profile/override state with an `as_of` date; it does not
reconstruct the configuration that actually existed on the historical date.

### Existing date and navigation behavior

The Daily Log already provides authoritative-calendar handling, previous/next-day navigation, direct
date selection, date classification, DST-safe calendar-day helpers, and navigation back to a
specific date. Epic 4 can reuse those semantics when a chart point or history row drills back into a
Daily Log.

### Existing UI and dependency surface

The mobile application already has:

- React Query read-state patterns for initial load, stale refresh, retry, empty, and unavailable
  states;
- `RootScreenHeader`, fixed route chrome, accessible pressables, accessibility status components,
  theme primitives, and shared nutrition formatting;
- `react-native-svg`, already used by the application, so a bounded chart does not inherently
  require another chart dependency.

The current bottom navigation is deliberately three-tab-shaped (`Foods`, `Daily Log`, `Recipes`) and
contains geometry/divider logic written around those three items. A fourth top-level tab is possible,
but it is not a zero-cost addition.

### Missing read model

`DailyLogsRuntime` currently exposes single-date Log reads and a single-date daily summary. There is
no bounded range-summary operation. Repeating one network request per date would be avoidable work
and would make local/remote parity harder to reason about as ranges grow.

Epic 4 should therefore add a bounded range read inside the existing Daily Logs capability rather
than inventing a ninth `NutritionRuntime` capability. History is a read projection over Daily Log
authority, not a new source of truth.

### Missing day-completeness state

The current Log contracts tell the application whether a date has entries, but they do not record a
user assertion that a day's food logging is complete. This matters because these are not equivalent:

1. no entries were logged;
2. only part of the day's food was logged;
3. all food was logged, but one or more Foods have unknown nutrient data;
4. all food was logged and the selected nutrient data is complete; and
5. a true consumed value is zero.

The current app can distinguish several of these states at the nutrient level, but it cannot prove
whether a non-empty day represents all food consumed that day. Epic 4 needs an explicit policy for
that uncertainty.

## Competitive research

The useful patterns are not concentrated in one competitor. The best fit for Nutrition App is a
combination of ideas with the coaching and score-heavy portions removed.

### Cronometer

Cronometer's Nutrition Report shows average daily nutrition over a selected range. Its most useful
idea for Epic 4 is explicit denominator control: reports can use All Days, Non-Empty Days, or days the
user marked Complete. It also lets the user exclude Today because an in-progress current day can
artificially lower an average. Its chart system supports nutrient charts and target lines.

Relevant sources:

- [Cronometer Nutrition Report](https://support.cronometer.com/hc/en-us/articles/360018569691-Nutrition-Report)
- [Cronometer Mobile Nutrition Report](https://support.cronometer.com/hc/en-us/articles/360019864891-Mobile-Nutrition-Report)
- [Cronometer Mobile Charts](https://support.cronometer.com/hc/en-us/articles/360019864311-Mobile-Charts)

What is reusable:

- make range inclusion rules visible;
- treat Today as potentially in progress rather than an ordinary finished day;
- let missing/incomplete days remain visibly different from zero;
- use average daily nutrition as a compact period summary.

What should not be copied directly:

- a highly configurable reporting system with many chart/report modes;
- the assumption that every nutrient needs a configurable graph on the main surface;
- green/red target framing as a general judgment about whether intake was good or bad.

### MacroFactor

MacroFactor separates a compact nutrition overview from nutrient-specific drill-down. Users can pin
nutrients they care about, open a nutrient to view intake over time, inspect exact prior-day values,
and view weekly averages. It also treats partial logging as a materially different state rather than
assuming a small logged value is necessarily true intake. MacroFactor additionally stores historical
micronutrient goals and reflects those historical goals on charts.

Relevant sources:

- [MacroFactor: View micronutrient intake over time](https://help.macrofactorapp.com/en/articles/131-how-to-view-micronutrient-intake-over-time)
- [MacroFactor: View weekly nutrition averages](https://help.macrofactorapp.com/en/articles/18-view-weekly-nutrition-averages)
- [MacroFactor: Pin nutrients to the dashboard](https://help.macrofactorapp.com/en/articles/129-pin-nutrients-to-the-dashboard)
- [MacroFactor: What is partial logging?](https://help.macrofactorapp.com/en/articles/241-what-is-partial-logging)
- [MacroFactor: Micronutrient goal history](https://help.macrofactorapp.com/en/articles/137-view-or-edit-your-micronutrient-goal-history)

What is reusable:

- overview first, nutrient detail second;
- direct nutrient selection instead of showing every nutrient chart simultaneously;
- exact day inspection from a chart;
- explicit treatment of partial logging;
- the conceptual distinction between current goals and historically stored goals.

What should not be copied directly:

- coaching logic that tries to infer what the user should do next;
- expenditure algorithms, weight-trend coupling, or goal-adjustment workflows;
- automatic behavioral judgments based on logging consistency.

MacroFactor's historical-goal approach is useful mainly as a warning: Nutrition App does not have
that model today, so it should not imitate the visual result without first adding equivalent
semantics.

### MyFitnessPal

MyFitnessPal exposes simple Daily/Weekly nutrition views and reporting periods such as 7, 30, and 90
days. Its Weekly Digest packages recent nutrition into a summary with calorie-goal and food-group
insights.

Relevant sources:

- [MyFitnessPal free nutrition views](https://support.myfitnesspal.com/hc/en-us/articles/15457546881805-What-is-included-in-the-free-version)
- [MyFitnessPal Weekly Digest](https://support.myfitnesspal.com/hc/en-us/articles/360032622591-Weekly-Digest)

What is reusable:

- simple preset periods instead of requiring a date-range editor for ordinary use;
- keeping the range control easy to understand.

What should not be copied directly:

- "remaining" or deficit language applied indiscriminately to nutrients;
- weekly summaries that frame a period as a good/off week;
- food-group or behavior coaching that exceeds Nutrition App's neutral informational scope.

### Lose It!

Lose It!'s Highlights surface waits for enough logging history and then presents patterns and goal
consistency. The useful idea is not the coaching content; it is that trend interpretation should not
pretend a tiny amount of history is meaningful.

Relevant source:

- [Lose It! Highlights](https://loseit.zendesk.com/hc/en-us/articles/47773480314772-About-Highlights)

What is reusable:

- an explicit insufficient-history state;
- avoid presenting a "trend" when only one or two usable days exist.

What should not be copied directly:

- success/habit judgments;
- personalized strategy recommendations;
- reward/streak framing as part of the History feature.

### Apple Health

Apple Health uses a useful information architecture even though its data domains are broader than
Nutrition App: a compact summary, user-pinned important categories, and category-specific detail
with weekly/monthly/yearly ranges. It also separates highlights from the underlying detailed data.

Relevant source:

- [Apple: View your data in Health on iPhone](https://support.apple.com/guide/iphone/view-your-health-data-iphe3d379c32/ios)

What is reusable:

- summary-to-detail navigation;
- allowing a small number of important metrics to dominate the overview;
- range switching near the focused metric rather than building one giant report.

What should not be copied directly:

- automatic health-trend alerts;
- significance claims about changes;
- broader health-data aggregation or HealthKit scope.

## Working product direction

The following is the recommended starting point for Grill discussion. Items marked as working
recommendations are deliberately reversible until accepted.

### 1. Put History under the Daily Log tab, not in a new fourth tab initially

**Working recommendation:** Add a dedicated `Nutrition History` route owned by the Daily Log tab.
The Daily Log gets a clear History action; selecting a date from History returns to the existing
Daily Log route for that date.

Why:

- History is interpretation of Daily Log data, so the ownership is natural.
- The screen still gets full dedicated route space rather than being embedded in the already-long
  Daily Log screen.
- The current bottom navigation is three-tab-specific, so this keeps the change bounded.
- If History later proves important enough to merit a fourth tab, that can be a deliberate navigation
  redesign rather than incidental Epic 4 scope.

### 2. Start with 7-day and 30-day ranges

**Working recommendation:** Provide `7 days` and `30 days` as the initial presets. Default to the
previous seven calendar dates ending yesterday.

Why:

- Daily Log already owns the current day. History can be genuinely backward-looking by default.
- Excluding Today by default avoids the common partial-day average problem Cronometer explicitly
  accounts for.
- Seven days is useful for short-term consistency; 30 days is enough to see whether a pattern is
  persistent without turning the first implementation into a long-range reporting engine.
- A 90-day or custom range can be added later if real use shows value.

An `Include today` option remains a reasonable follow-up, but Today must be visibly identified as in
progress if it participates in a period.

### 3. Use discrete daily bars, not a continuous line, for intake

**Working recommendation:** Nutrient detail uses one bar per calendar day.

A line connecting dates suggests continuity and interpolation between observations. Daily food intake
is a discrete daily total, and missing dates should create visible gaps rather than a line passing
through them.

Each day should be able to represent:

- known amount;
- estimated amount as a visually distinct stacked portion;
- unknown contributors with an explicit marker/state;
- no logs as a gap, not a zero-height consumed bar; and
- an explicitly confirmed zero only if the product has enough day-state information to support that
  claim.

The chart must not be the only representation of the data. Exact textual values and accessible day
selection remain required.

### 4. Separate logging coverage from nutrient-data completeness

**Working recommendation:** Treat these as independent concepts in both the data contract and UI.

- **Logging coverage** asks whether the day represents all food the user intended to record.
- **Nutrient completeness** asks whether the logged Foods supplied complete data for the selected
  nutrient.

A day may be completely logged while sodium is still incomplete because one Food has unknown sodium.
Conversely, every logged Food can have complete sodium data while the user forgot dinner.

The current snapshot model already supports nutrient completeness. Epic 4 needs a decision about
logging coverage.

### 5. Add a lightweight user-confirmed day-completeness concept

**Working recommendation:** Introduce an optional day-level `complete` assertion rather than an
automatic partial-logging detector.

A conservative model would be:

- every historical date starts unconfirmed;
- a user may mark a date `Complete` from the Daily Log when they believe the day's logging is done;
- removing that assertion returns the date to unconfirmed;
- History always shows all dates honestly, but can distinguish complete, unconfirmed non-empty, and
  empty dates;
- period summaries state the denominator explicitly, for example: `5 of 7 days have logs; 3 are
  marked complete`;
- a future filter could offer `Logged days` versus `Complete days` if useful.

This borrows Cronometer's strongest data-quality idea without requiring MacroFactor-style coaching or
heuristic detection.

The main tradeoff is extra state and one small end-of-day action. If that feels like unnecessary
administration in practice, the fallback is to omit completion state and label every aggregate as
`logged average`, but that is weaker because a partially logged day remains indistinguishable from a
truly low-intake day.

### 6. Define averages as logged-data summaries, never inferred intake

**Working recommendation:** Period summaries should say exactly what denominator they use.

Examples:

- `Logged-day average: 2,041 kcal · 6 logged days`
- `5 of 7 dates contain logs`
- `3 dates marked complete`
- `2 days include unknown sodium contributors`

Do not silently divide by all calendar dates and treat missing days as zero. Do not call a value
`average intake` when the application only knows `average of logged amounts`.

If a Complete-days filter is accepted, the UI can additionally expose `Complete-day average` without
changing the raw historical data.

### 7. Use the current target/reference as a lens, not as fake historical goal state

**Working recommendation:** Epic 4 does not add target-history versioning.

The History screen may compare the selected nutrient's logged-day average with the **current**
effective target/reference. The label must say `Current target`, `Current DRI`, `Current Daily Value`,
`Current custom target`, or equivalent authority-aware wording.

The chart may draw a horizontal current-reference line/band when it is meaningful, but it must not
imply that the same value was configured on every historical date.

If the product later needs "what goal did I have at the time?", that requires a separate immutable or
versioned target-history design similar in concept to MacroFactor's goal history. It should not be
smuggled into Epic 4 presentation.

### 8. Keep the overview compact and drill into one nutrient at a time

**Working recommendation:** The initial History overview should emphasize calories and macronutrients,
then offer the full canonical nutrient catalog through a grouped nutrient picker/detail flow. Existing
`ignored` tracking preferences should continue to hide nutrients the user deliberately excluded.

Do not add a second history-specific pin/favorite preference until there is evidence that it is
needed. The existing tracking-preference model already gives the product one user-controlled nutrient
visibility axis.

A likely first screen hierarchy:

1. `Nutrition History` header.
2. `7 days` / `30 days` range control.
3. coverage summary.
4. compact Calories / Protein / Carbohydrate / Fat period rows.
5. `View another nutrient` grouped picker.
6. tapping a nutrient opens/focuses nutrient detail.

Nutrient detail should contain:

1. nutrient name and unit;
2. logged-day average and denominator;
3. current target/reference context, when available;
4. discrete daily chart;
5. data-quality summary for estimated/unknown values; and
6. exact daily rows/tiles that open the contributing Daily Log date.

This gives detailed access without making the first screen a wall of micronutrient charts.

### 9. Do not add automatic trend judgments in the first implementation

**Working recommendation:** Show the data and period summaries without labeling a nutrient
`improving`, `worsening`, `on track`, or `off track`.

A later Grill decision could add neutral comparisons such as `7-day logged average vs prior 7-day
logged average`, but only if the denominator and completeness semantics are strong enough. There is
no need to manufacture a trend score simply because the Epic name contains "Trends."

A well-designed chronological chart is already a trend view.

### 10. Defer contributor ranking unless the core history flow feels incomplete without it

MacroFactor can show which Foods contributed most to a nutrient over a day/week/month. Nutrition App
has enough immutable snapshot provenance to make some contributor analysis possible, but a correct
period contributor model is additional read-model and UI scope.

The original Epic outcome only requires navigation back to contributing days. Start there. A user can
open an unusual date and inspect its entries using the existing Daily Log. Period-level `top sodium
sources` or similar ranking should be a separate follow-up decision rather than an assumed Epic 4
requirement.

## Proposed architecture shape

This section is planning guidance, not architecture approval.

### Keep History inside Daily Logs authority

Do not add a new top-level runtime capability solely for History. Extend `DailyLogsRuntime` with a
bounded read such as:

```ts
getHistoryRange(startDate: string, endDate: string): Promise<NutritionHistoryRange>
```

The exact name belongs in architecture review, but the ownership should remain with Daily Logs.

A useful range response would preserve per-day state rather than returning only one precomputed
average:

```ts
type NutritionHistoryDay = {
  loggedDate: string;
  entryCount: number;
  loggingComplete: boolean | null;
  totals: AggregatedNutrientTotal[];
};

type NutritionHistoryRange = {
  startDate: string;
  endDate: string;
  days: NutritionHistoryDay[];
};
```

`loggingComplete` is included only if the day-completeness decision is accepted. `null`/unconfirmed
must remain distinct from `false` if the final model distinguishes an explicit incomplete state.

### Local authority

The local SQLite runtime can perform one ordered range read over Daily Logs and
`daily_log_nutrient_snapshots`, preserving the same exact-decimal and status validation used by
single-day summaries. It should not materialize or duplicate historical nutrient truth into a new
cache table merely to draw a chart.

### Remote/reference authority

The preserved FastAPI/PostgreSQL authority should expose one bounded range endpoint under the Log
surface rather than requiring 7 or 30 independent daily-summary requests. The response must have the
same semantic contract as the local runtime.

### Shared calculation layer

Period statistics can be implemented as deterministic pure functions over the range response:

- choose included days;
- calculate exact logged-day averages;
- count missing/unconfirmed/complete dates;
- propagate estimated and unknown states;
- prepare chart points without inventing zeros; and
- apply current target/reference context separately from historical nutrition.

These functions should use the existing exact-decimal helpers rather than JavaScript floating-point
math.

### Reuse current target presentation, not current target storage as history

Reuse:

- nutrient labels and catalog order;
- target authority/direction vocabulary;
- target amount/percentage formatting;
- hierarchy/grouping helpers;
- unknown-data wording and accessibility semantics.

Do not reuse `getDailyComparison(date)` in a loop and call the resulting target values historical
goals. History should keep immutable intake and mutable current comparison context conceptually
separate.

### Chart implementation

Because `react-native-svg` is already an application dependency, the initial daily-bar chart can be a
small purpose-built component rather than adding a large charting package. The first chart needs a
bounded feature set: bars, stacked known/estimated portions, gaps, a reference line, selection, and
accessible labels.

A third-party chart library should be considered only if the accepted Grill scope requires
interaction/zooming complexity that would otherwise create more custom code than it removes.

## Likely qualification requirements

A later implementation backlog should prove at least the following behaviors:

- historical values derive only from immutable Daily Log snapshots;
- Food and Recipe edits do not change history results;
- a missing date is never serialized or rendered as consumed zero;
- an explicit nutrient zero remains different from missing data;
- estimated amount remains distinguishable from known amount;
- unknown nutrient contributors propagate into period/detail quality state;
- a completely logged day with unknown nutrient data remains distinct from an incompletely logged
  day;
- range boundaries use authoritative calendar dates and remain DST-safe;
- Today cannot silently distort the default historical average;
- current target/reference context is labeled as current, not historical;
- `ignored` nutrients remain excluded from ordinary history discovery;
- local and remote/reference authorities return equivalent range semantics;
- chart selection opens the exact Daily Log date represented by the point;
- chart information remains available through text/accessibility semantics rather than visual shape
  alone; and
- stale refresh/failure behavior follows the existing presentation-safe read-state model.

Performance qualification should cover at least the accepted 7-day and 30-day ranges on a realistic
local history. If 90-day/custom ranges are later accepted, test and query design should be revisited
rather than assumed to scale automatically.

## Decision register for Grill discussion

These are the choices most worth resolving before a PRD is written.

| ID | Decision | Working recommendation |
| --- | --- | --- |
| E4-D1 | Where does History live? | Dedicated route owned by the Daily Log tab; do not add a fourth bottom tab initially. |
| E4-D2 | Initial ranges? | 7 days and 30 days. Default to the previous 7 dates ending yesterday. |
| E4-D3 | Include Today? | Not by default. Consider an explicit option later, with in-progress semantics. |
| E4-D4 | How are missing days handled? | Gaps and coverage counts; never implicit zero. |
| E4-D5 | How are partially logged days handled? | Add optional user-confirmed day completeness; no heuristic coaching/detection. |
| E4-D6 | What does the period average mean? | Explicit logged-day or confirmed-complete-day average with denominator shown. |
| E4-D7 | Historical target line? | No. Compare with a clearly labeled current target/reference unless target history is separately designed. |
| E4-D8 | Chart type? | Discrete daily bars with known/estimated distinction, unknown marker, and missing-date gaps. |
| E4-D9 | Overview nutrient density? | Calories/macros first; grouped access to any non-ignored canonical nutrient. No new pin preference initially. |
| E4-D10 | Automatic trend labels/scores? | No in initial Epic 4 scope. Let the chart and exact summaries show the pattern. |
| E4-D11 | 90-day/custom ranges? | Defer until 7/30-day usability is proven. |
| E4-D12 | Period contributor ranking? | Defer; drill from a date into the existing Daily Log first. |

## Expected personal-use flow

The recommended design is optimized for inspection rather than coaching:

1. Open Daily Log and choose `History`.
2. Start with the previous seven days.
3. See immediately how many dates actually contain logs and how many are confirmed complete.
4. Review compact calorie/macronutrient averages without having every nutrient compete for space.
5. Open a nutrient of interest when needed.
6. Inspect the daily bars, exact values, estimated/unknown markers, and current reference context.
7. Tap an unusual day to return to the actual Daily Log entries that produced it.
8. Switch to 30 days when the question is whether the pattern persists beyond one week.

The app remains a trustworthy instrument panel: it exposes the structure of the data and lets the user
reason from it. It does not try to replace that reasoning with a score or diet coach.

## Next planning step

Use this document as the starting evidence for an Epic 4 Grill. The Grill should explicitly resolve
E4-D1 through E4-D12, especially the day-completeness model and target/reference semantics, before a
Feature PRD is authored.

Once those decisions are accepted, the normal sequence remains:

1. Grill / resolved product decisions;
2. Feature PRD;
3. architecture review;
4. implementation backlog;
5. GitHub implementation issues and qualified delivery.
