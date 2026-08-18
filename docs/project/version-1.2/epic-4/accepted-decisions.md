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
- A nutrition-affecting Log mutation should clear the completion assertion for every affected date so the user can reconfirm the changed day.
- Moving an entry should clear completion for both source and destination dates.
- A meal-label or note-only change does not inherently change nutritional completeness and should not clear completion solely for that reason.
- Empty dates should not be treated as confirmed zero-consumption days merely because they contain no Logs. A future explicit fasting/no-intake concept would require separate semantics if ever needed.

### Logging-first Daily Log information hierarchy

The expanded nutrient catalog exposed a product hierarchy problem: the Daily Log currently places full target progress and full nutrient totals before the meal entries and `Add Food` actions. As the catalog grew, the main logging workflow became buried under analysis.

The accepted direction is **logging first, analysis one interaction away**.

The Daily Log should prioritize:

1. sticky header with day state and Settings;
2. date controls;
3. a compact nutrition summary;
4. meal entries and meal-level `Add Food` actions.

The complete nutrient catalog should no longer sit between the selected date and the meal logging workflow.

A likely compact summary is Calories plus Protein, Carbohydrate, and Fat, followed by a `View nutrition details` action. Exact composition and styling remain Grill/PRD decisions.

### Daily Nutrition becomes a deliberate detail surface

The current full `Target Progress` and `Totals` sections substantially overlap. The accepted planning direction is to consolidate full-day nutrient inspection into one coherent Daily Nutrition detail surface rather than displaying the entire catalog twice in the Daily Log.

The resulting conceptual structure is:

```text
Daily Log
├── meals and logging for one date
├── Daily Nutrition
│   └── complete nutrient analysis for one date
└── Nutrition History
    └── nutrient analysis across dates
```

This is an information-architecture decision, not yet a route/API implementation decision.

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

The following planning decisions remain open for Grill discussion:

- exact 7-day / 30-day range behavior and whether Today can be explicitly included;
- exact Daily Nutrition route and compact-summary composition;
- chart type and interaction details, although discrete daily bars remain the working recommendation;
- how current target/reference context is presented in History without implying historical target versioning;
- whether any explicit data-quality detail surface is useful after default unknown warnings are removed;
- whether 90-day/custom ranges belong in the initial Epic;
- whether period contributor ranking is useful enough to justify additional scope; and
- exact Food-form grouping/order for the default Nutrition Facts subset and extended nutrient picker.

## Regulatory reference used for the default Nutrition Facts subset

The planning decision above uses current FDA Nutrition Facts guidance as a product-entry reference, not as an attempt to make Nutrition App a regulatory-label-authoring tool. The application records nutrition supplied by the user/source; it does not certify label compliance.

Relevant FDA references:

- <https://www.fda.gov/food/nutrition-facts-label/daily-value-nutrition-and-supplement-facts-labels>
- <https://www.fda.gov/food/nutrition-food-labeling-and-critical-foods/industry-resources-changes-nutrition-facts-label>
