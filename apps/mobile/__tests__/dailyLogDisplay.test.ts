import {
  addLocalDays,
  formatReadableDate,
  localDateToApiDate,
  parseLocalDateString,
  setLocalDatePart,
  todayLocalDateString,
  visibleDailyTotals,
  loggedFoodDisplayName,
  dailyLogEntryState,
} from "../src/features/logging/utils/dailyLogDisplay";
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
