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

test("common fraction serving labels render as fractions in Food detail chips", () => {
  const half: ResolvedFoodAmount = {
    amount_definition_id: "serving-3",
    display_label: "0.5 cup",
    is_default: false,
    entered_quantity: "1",
    semantic_amount_mode: "serving",
    resolved_grams: "41",
    valid_for_logging: true,
    nutrients: [],
  };
  const quarter: ResolvedFoodAmount = {
    amount_definition_id: "serving-4",
    display_label: "0.25 cup",
    is_default: false,
    entered_quantity: "1",
    semantic_amount_mode: "serving",
    resolved_grams: "20.5",
    valid_for_logging: true,
    nutrients: [],
  };

  expect(formatResolvedFoodAmount(half)).toBe("1/2 cup (41 g)");
  expect(formatResolvedFoodAmount(quarter)).toBe("1/4 cup (20.5 g)");
});

test("manual serving labels remain authoritative and rendering leaves every canonical value unchanged", () => {
  const manual: ResolvedFoodAmount = {
    amount_definition_id: "serving-5",
    display_label: "Small bowl",
    is_default: false,
    entered_quantity: "1",
    semantic_amount_mode: "serving",
    resolved_grams: "123.134328",
    valid_for_logging: true,
    nutrients: [],
  };

  expect(formatResolvedFoodAmount(manual)).toBe("Small bowl (123.1 g)");
  expect(manual.display_label).toBe("Small bowl");
  expect(manual.resolved_grams).toBe("123.134328");
  expect(manual.entered_quantity).toBe("1");

  const fraction: ResolvedFoodAmount = {
    ...manual,
    display_label: "0.666666667 cup",
  };
  expect(formatResolvedFoodAmount(fraction)).toBe("2/3 cup (123.1 g)");
  expect(fraction.display_label).toBe("0.666666667 cup");
  expect(fraction.resolved_grams).toBe("123.134328");
});
