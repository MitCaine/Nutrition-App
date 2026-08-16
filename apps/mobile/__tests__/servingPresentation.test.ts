import type { ResolvedFoodAmount } from "../src/features/foods/api/types";
import { formatResolvedFoodAmount } from "../src/features/foods/utils/foodDisplay";

test("saved Food serving display uses a common fraction and one-decimal gram precision", () => {
  const amount: ResolvedFoodAmount = {
    amount_definition_id: "serving-1",
    display_label: "0.666666667 cup",
    is_default: true,
    entered_quantity: "1",
    semantic_amount_mode: "serving",
    resolved_grams: "55",
    valid_for_logging: true,
    nutrients: [],
  };

  expect(formatResolvedFoodAmount(amount)).toBe("2/3 cup (55 g)");
});

test("saved Food gram display rounds only presentation precision", () => {
  const amount: ResolvedFoodAmount = {
    amount_definition_id: "serving-2",
    display_label: "1 cup",
    is_default: true,
    entered_quantity: "1",
    semantic_amount_mode: "serving",
    resolved_grams: "82.089552",
    valid_for_logging: true,
    nutrients: [],
  };

  expect(formatResolvedFoodAmount(amount)).toBe("1 cup (82.1 g)");
  expect(amount.resolved_grams).toBe("82.089552");
});
