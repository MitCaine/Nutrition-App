import { logInputSchema } from "../src/features/logging/validation/logValidation";

test("log validation rejects non-positive amounts", () => {
  expect(
    logInputSchema.safeParse({
      food_item_id: "food-1",
      logged_date: "2026-07-08",
      amount_quantity: "0",
      amount_unit: "serving",
    }).success,
  ).toBe(false);
});
