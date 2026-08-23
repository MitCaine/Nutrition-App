# Issue #108 — Sticky navigation header inventory

This inventory records the mobile-screen audit required by GitHub issue #108. The implementation uses `RouteScreenHeader` as a sibling of the primary body scroller. It does not use absolute positioning or duplicate navigation callbacks. Fixed route-title and action text cap visual Dynamic Type growth at 1.5× while remaining fully accessible.

| Flow | Existing route chrome | #108 decision | Rationale |
|---|---|---|---|
| Daily Log | Title and Settings action already outside the scrolling log body | Keep unchanged | This is the established sticky-header reference behavior. |
| Settings | Back and route title were inside the settings `ScrollView` | Migrate | Settings can become long and includes nested configuration sections. |
| Nutrition Targets | Back and route title were inside `KeyboardSafeScrollView` | Migrate | The expanded nutrient manager is a long form and must retain route context. |
| Food Detail | Back and Food title were inside the detail `ScrollView` | Migrate | Serving choices, actions, and nutrient rows can extend well beyond one viewport. |
| Food create/edit/manage servings | Cancel and route title were inside `KeyboardSafeScrollView` | Migrate | Long serving/nutrient editing must retain Cancel and route context without moving Save. |
| Log Food / Edit Log | Cancel and route title were inside the form `ScrollView` | Migrate | Meal, amount, note, recovery, and source-review states can produce long content. |
| Move Legacy Entry | Cancel and route title were inside the move `ScrollView` | Migrate | Keep the route exit available while preserving the date-only recovery flow. |
| OCR Nutrition Confirmation | Cancel and route title were inside `KeyboardSafeScrollView` | Migrate | Nutrition review can contain many parsed nutrient/serving rows. |
| OCR Diagnostics | Back and route title were inside the diagnostics `ScrollView` | Migrate | Diagnostic output can become substantially longer than one viewport. |
| Recipe Detail | Back/Edit were fixed but the Recipe title scrolled with detail content | Migrate | Consolidate fixed route context and actions without changing Recipe behavior. |
| Recipe create/edit | Cancel and route title were inside `KeyboardSafeScrollView` | Migrate | Ingredient and serving editing is a long authoring flow; Save remains in its existing location. |
| USDA Preview | Back was fixed but the USDA Food title scrolled with preview content | Migrate | Keep the route title and Back together while long nutrient data scrolls. |
| Add Food | Route-level chrome is already outside the results scroller | Keep unchanged | Already satisfies the #108 behavior. |
| Ingredient Picker | Route-level chrome is already outside the results scroller | Keep unchanged | Already satisfies the #108 behavior. |
| USDA Search | Route-level chrome is already outside the results scroller | Keep unchanged | Already satisfies the #108 behavior. |
| Nutrition Scan acquisition | No long vertically scrolling route body requiring sticky chrome | Keep unchanged | Acquisition is a short camera/photo-selection surface rather than a long review form. |
| Bottom-navigation root screens | Root chrome is already outside the content scroller | Keep unchanged | These are root-level navigation surfaces, not Back/Cancel flows. |
| Date pickers, dependency dialogs, and other modals | Modal-specific controls | Keep unchanged | They are modal/contained surfaces rather than top-level scrollable routes. |
| Embedded Settings sections such as backup/credentials | No independent route-level Back/Cancel action | Keep unchanged | They inherit the fixed Settings route header. |

## Preserved contracts

The migration changes presentation ownership only. Existing Back, Cancel, Edit, Save, mutation, draft, recovery, target, Food, Recipe, OCR, USDA, and logging callbacks remain owned by their original screens. `RouteScreenHeader` does not perform navigation or persistence.

`#82` dirty/pristine/discard behavior remains at the existing navigation and screen callback boundaries. No new navigation guard is introduced.

Keyboard-safe screens retain their existing `KeyboardAvoidingView` and/or `KeyboardSafeScrollView`; only the route chrome moves outside the body scroller.

Daily Log is not refactored by #108, so its existing title/Settings sticky behavior remains its own proven implementation.

## Physical qualification

Physical iPhone QA remains required before issue closure. Exercise Settings, Nutrition Targets, long Food create/edit/detail, Log Food/Edit/Move, long Recipe create/edit/detail, OCR Confirmation, OCR Diagnostics, and USDA Preview. Scroll far enough that the former inline header would have left the viewport and verify the fixed title/action remains visible and usable.

For dirty authoring flows, verify existing Stay/Discard behavior is unchanged. While mutations are pending, verify the route action remains disabled/busy and visibly unavailable. Verify keyboard presentation does not cover or displace the fixed route header and that top/bottom content spacing remains usable.
