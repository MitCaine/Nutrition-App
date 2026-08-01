import { logInputSchema } from "../src/features/logging/validation/logValidation";
import {
  MAX_NOTE_CODE_POINTS,
  SUPPORTED_MEALS,
  LogContractError,
  codePointLength,
  normalizeLogMeal,
  normalizeLogNote,
} from "../src/features/logging/validation/logContracts";

test("meal contract accepts the four supported meals and canonical absence", () => {
  expect(SUPPORTED_MEALS.map((meal) => normalizeLogMeal(meal))).toEqual(SUPPORTED_MEALS);
  expect(normalizeLogMeal(null)).toBeNull();
  try {
    normalizeLogMeal("brunch");
    throw new Error("expected meal validation to fail");
  } catch (error) {
    expect(error).toBeInstanceOf(LogContractError);
    expect((error as LogContractError).code).toBe("meal_invalid");
  }
});

test("note contract trims edges, preserves internal whitespace, and counts code points", () => {
  expect(normalizeLogNote("  first\n second  ")).toBe("first\n second");
  expect(normalizeLogNote(" \n ")).toBeNull();
  expect(codePointLength("🙂".repeat(MAX_NOTE_CODE_POINTS))).toBe(MAX_NOTE_CODE_POINTS);
  expect(normalizeLogNote("🙂".repeat(MAX_NOTE_CODE_POINTS))).toBe("🙂".repeat(MAX_NOTE_CODE_POINTS));
  try {
    normalizeLogNote("🙂".repeat(MAX_NOTE_CODE_POINTS + 1));
    throw new Error("expected note validation to fail");
  } catch (error) {
    expect(error).toBeInstanceOf(LogContractError);
    expect((error as LogContractError).code).toBe("note_too_long");
  }
});

test("mobile request validation serializes canonical note absence and rejects invalid contracts", () => {
  const valid = logInputSchema.safeParse({
    food_item_id: "food-1",
    logged_date: "2026-07-08",
    amount_quantity: "1",
    amount_unit: "serving",
    meal_type: null,
    notes: "  note  ",
  });
  expect(valid.success).toBe(true);
  if (valid.success) {
    expect(valid.data.meal_type).toBeNull();
    expect(valid.data.notes).toBe("note");
  }

  expect(logInputSchema.safeParse({
    food_item_id: "food-1",
    logged_date: "2026-07-08",
    amount_quantity: "1",
    amount_unit: "serving",
    meal_type: "brunch",
  }).success).toBe(false);
  expect(logInputSchema.safeParse({
    food_item_id: "food-1",
    logged_date: "2026-07-08",
    amount_quantity: "1",
    amount_unit: "serving",
    notes: "🙂".repeat(MAX_NOTE_CODE_POINTS + 1),
  }).success).toBe(false);
});
