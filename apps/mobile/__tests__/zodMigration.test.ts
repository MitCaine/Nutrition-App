import { z } from "zod";

import { logInputSchema } from "../src/features/logging/validation/logValidation";
import { NOTE_TOO_LONG_MESSAGE } from "../src/features/logging/validation/logContracts";

// The upstream fix must reject a constrained collection before parsing its
// elements. Tiny inputs distinguish eager traversal without risking exhaustion.
test.each(["array", "set", "map"] as const)(
  "%s rejects oversized collections before visiting elements",
  (kind) => {
    let visited = 0;
    const element = z.string().transform((value) => {
      visited += 1;
      return value;
    });
    const values = ["a", "b", "c"];
    const schema = kind === "array"
      ? z.array(element).max(2)
      : kind === "set"
      ? z.set(element).max(2)
      : z.map(z.string(), element).max(2);
    const input = kind === "array"
      ? values
      : kind === "set"
      ? new Set(values)
      : new Map(values.map((value) => [value, value]));

    const result = schema.safeParse(input);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues).toHaveLength(1);
      expect(result.error.issues[0].code).toBe("too_big");
    }
    expect(visited).toBe(0);
  },
);

test("a collection at the bound still parses each element", () => {
  let visited = 0;
  const schema = z.array(z.string().transform((value) => {
    visited += 1;
    return value.toUpperCase();
  })).max(2);

  expect(schema.parse(["a", "b"])).toEqual(["A", "B"]);
  expect(visited).toBe(2);
});

const log = {
  food_item_id: "food-1",
  logged_date: "2026-10-30",
  amount_quantity: "1",
  amount_unit: "g" as const,
};

test("Log required fields and absent versus null optional values remain distinct", () => {
  expect(logInputSchema.parse(log)).toEqual(log);
  expect(logInputSchema.parse({ ...log, notes: null, meal_type: null }))
    .toEqual({ ...log, notes: null, meal_type: null });
  const { food_item_id: omitted, ...missingRequired } = log;
  expect(omitted).toBe("food-1");
  expect(logInputSchema.safeParse(missingRequired).success).toBe(false);
});

test("Log preprocessing and custom field errors retain their contract", () => {
  expect(logInputSchema.parse({ ...log, notes: "   " }).notes).toBeNull();
  expect(logInputSchema.parse({ ...log, notes: "  keep me  " }).notes).toBe("keep me");
  expect(() => logInputSchema.parse({ ...log, notes: "x".repeat(1001) }))
    .toThrow(NOTE_TOO_LONG_MESSAGE);
  expect(() => logInputSchema.parse({ ...log, amount_quantity: "0" }))
    .toThrow("Amount must be greater than zero");
});
