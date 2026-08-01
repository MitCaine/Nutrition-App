import {
  addCalendarDays,
  addLocalDays,
  classifyCalendarDate,
  formatReadableDate,
  localDateToApiDate,
  parseLocalDateString,
  setLocalDatePart,
  todayLocalDateString,
  todayInTimeZone,
  visibleDailyTotals,
  loggedFoodDisplayName,
  dailyLogEntryState,
  groupDailyLogs,
  legacyNoteNotice,
  mealAddContext,
  DAILY_LOG_MEAL_GROUPS,
  unsupportedMealNotice,
} from "../src/features/logging/utils/dailyLogDisplay";
import type { DailyLog } from "../src/features/logging/api/types";
import type { AggregatedNutrientTotal } from "../src/shared/nutrition/types";

function total(
  nutrientId: string,
  amountKnown: string,
  hasUnknownContributors = false,
): AggregatedNutrientTotal {
  return {
    nutrientId,
    amountKnown,
    amountEstimated: "0.000000",
    unit: nutrientId === "calories" ? "kcal" : "g",
    hasUnknownContributors,
    unknownContributorCount: hasUnknownContributors ? 1 : 0,
  };
}

test("daily log hides unknown-only totals but keeps known and partial totals", () => {
  const visible = visibleDailyTotals([
    total("vitamin_d", "0.000000", true),
    total("protein", "2.720000", true),
    total("calories", "120.000000", false),
  ]);

  expect(visible.map((item) => item.nutrientId)).toEqual(["calories", "protein"]);
  expect(visible[1].hasUnknownContributors).toBe(true);
});

test("daily log totals keep calories first", () => {
  expect(visibleDailyTotals([total("protein", "10"), total("calories", "50")]).map((item) => item.nutrientId)).toEqual([
    "calories",
    "protein",
  ]);
});

test("historical totals remain snapshot-summary values when current Food Detail differs", () => {
  const historicalSummary = [total("protein", "5.000000")];
  const currentPublishedFoodDetailAmount = "12.000000";

  expect(visibleDailyTotals(historicalSummary)[0].amountKnown).toBe("5.000000");
  expect(visibleDailyTotals(historicalSummary)[0].amountKnown).not.toBe(
    currentPublishedFoodDetailAmount,
  );
});

test("historical log display prefers snapshot name with sensible fallbacks", () => {
  const names = new Map([["food-1", "Current Name"]]);
  expect(loggedFoodDisplayName({ food_item_id: "food-1", food_name_snapshot: "Original Name" }, names)).toBe("Original Name");
  expect(loggedFoodDisplayName({ food_item_id: "food-1", food_name_snapshot: null }, names)).toBe("Current Name");
  expect(loggedFoodDisplayName({ food_item_id: "deleted-food", food_name_snapshot: null }, names)).toBe("Deleted food");
});

test("deleted-source compatibility log presentation is read-only but remains deletable", () => {
  expect(dailyLogEntryState({ is_editable: false, source_food_available: false, edit_block_reason: "source_food_deleted" })).toEqual({
    canDelete: true,
    canEdit: false,
    canOpenFood: false,
    sourceStatusLabel: "Source food deleted",
  });
});

test("active-source log presentation retains edit and food navigation", () => {
  expect(dailyLogEntryState({ is_editable: true, source_food_available: true, edit_block_reason: null })).toEqual({
    canDelete: true,
    canEdit: true,
    canOpenFood: true,
    sourceStatusLabel: null,
  });
});

test("revision-backed deleted-source log remains editable without food navigation", () => {
  expect(dailyLogEntryState({
    is_editable: true,
    source_food_available: false,
    edit_block_reason: null,
  })).toEqual({
    canDelete: true,
    canEdit: true,
    canOpenFood: false,
    sourceStatusLabel: "Source food deleted",
  });
});

test("local date helpers preserve calendar dates without UTC shifting", () => {
  expect(todayLocalDateString(new Date(2026, 6, 11, 23, 30))).toBe("2026-07-11");
  expect(todayLocalDateString(new Date(2026, 6, 11, 0, 30))).toBe("2026-07-11");
  expect(localDateToApiDate(new Date(2026, 6, 11, 23, 30))).toBe("2026-07-11");
  expect(parseLocalDateString("2026-07-11")?.getFullYear()).toBe(2026);
  expect(parseLocalDateString("2026-02-31")).toBeNull();
});

test("date selector helpers update date parts and readable labels", () => {
  expect(addLocalDays("2026-07-11", -1)).toBe("2026-07-10");
  expect(setLocalDatePart("2026-07-11", "month", 1)).toBe("2026-08-11");
  expect(setLocalDatePart("2026-01-31", "month", 1)).toBe("2026-02-28");
  expect(formatReadableDate("2026-07-11")).toContain("2026");
});

test("authoritative date arithmetic handles leap days and year boundaries", () => {
  expect(addCalendarDays("2028-02-28", 1)).toBe("2028-02-29");
  expect(addCalendarDays("2028-02-29", 1)).toBe("2028-03-01");
  expect(addCalendarDays("2026-12-31", 1)).toBe("2027-01-01");
  expect(addCalendarDays("2027-01-01", -1)).toBe("2026-12-31");
});

test("authoritative today uses the selected IANA zone across offset transitions", () => {
  expect(todayInTimeZone("America/New_York", new Date("2026-03-08T06:30:00.000Z"))).toBe("2026-03-08");
  expect(todayInTimeZone("Pacific/Kiritimati", new Date("2026-01-01T10:00:00.000Z"))).toBe("2026-01-02");
});

test("future classification compares calendar dates rather than elapsed time", () => {
  expect(classifyCalendarDate("2026-07-13", "2026-07-14")).toBe("past");
  expect(classifyCalendarDate("2026-07-14", "2026-07-14")).toBe("today");
  expect(classifyCalendarDate("2026-07-15", "2026-07-14")).toBe("future");
});

function entry(id: string, meal_type: string | null, created_at: string, notes: string | null = null): DailyLog {
  return {
    id,
    food_item_id: `food-${id}`,
    food_name_snapshot: `Food ${id}`,
    meal_type,
    source_food_available: true,
    logged_date: "2026-07-14",
    amount_quantity: "1",
    amount_unit: "serving",
    notes,
    created_at,
  };
}

test("meal grouping keeps fixed named groups, projects legacy meals, and orders deterministically", () => {
  const groups = groupDailyLogs([
    entry("b", "breakfast", "2026-07-14T08:00:00Z"),
    entry("a", "breakfast", "2026-07-14T08:00:00Z"),
    entry("legacy", "brunch", "2026-07-14T07:00:00Z"),
    entry("snack", "snack", "2026-07-14T09:00:00Z"),
  ]);

  expect(groups.map((group) => group.key)).toEqual([
    "breakfast", "lunch", "dinner", "snack", "unassigned",
  ]);
  expect(groups[0].entries.map((item) => item.id)).toEqual(["a", "b"]);
  expect(groups[4].entries.map((item) => item.id)).toEqual(["legacy"]);
});

test("compatibility notices preserve legacy values without rewriting them", () => {
  const legacy = entry("legacy", "brunch", "2026-07-14T07:00:00Z", "x".repeat(1001));
  expect(legacy.meal_type).toBe("brunch");
  expect(unsupportedMealNotice(legacy)).toContain("brunch");
  expect(legacyNoteNotice(legacy.notes)).toContain("remains readable");
  expect(legacyNoteNotice("🙂".repeat(1000))).toBeNull();
});

test("named meal actions carry their group context and Unassigned has none", () => {
  expect(DAILY_LOG_MEAL_GROUPS.map((group) => mealAddContext(group.key))).toEqual([
    "breakfast", "lunch", "dinner", "snack",
  ]);
  expect(mealAddContext("unassigned")).toBeNull();
});
