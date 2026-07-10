import type { Food } from "../src/features/foods/api/types";
import {
  buildLogInput,
  formatInitialLogAmount,
  formatServingGramWeight,
  initialServingId,
} from "../src/features/logging/utils/logFoodForm";

const importedFood: Food = {
  id: "food-usda",
  name: "Example Protein Bar",
  brand: "Example Foods",
  source_type: "usda",
  source_id: "555000",
  is_recipe: false,
  serving_definitions: [
    {
      id: "serving-100g",
      label: "100 g",
      quantity: "100",
      unit: "g",
      gram_weight: "100.000000",
      is_default: false,
      source: "usda_fdc",
      is_user_confirmed: false,
    },
    {
      id: "serving-bar",
      label: "1 bar",
      quantity: "50",
      unit: "g",
      gram_weight: "50.000000",
      is_default: true,
      source: "usda_fdc",
      is_user_confirmed: false,
    },
  ],
  nutrients: [],
};

test("logging imported USDA food uses branded default serving", () => {
  const selectedServingId = initialServingId(importedFood);
  const input = buildLogInput({
    foodId: importedFood.id,
    date: "2026-07-08",
    amount: "1",
    unit: "serving",
    selectedServingId,
  });

  expect(selectedServingId).toBe("serving-bar");
  expect(input).toEqual({
    food_item_id: "food-usda",
    logged_date: "2026-07-08",
    amount_quantity: "1",
    amount_unit: "serving",
    serving_definition_id: "serving-bar",
  });
});

test("100 g serving can be selected for an imported USDA food", () => {
  const input = buildLogInput({
    foodId: importedFood.id,
    date: "2026-07-08",
    amount: "1",
    unit: "serving",
    selectedServingId: "serving-100g",
  });

  expect(importedFood.serving_definitions.some((serving) => serving.id === "serving-100g")).toBe(true);
  expect(input.serving_definition_id).toBe("serving-100g");
});

test("manual food logging uses the same default-serving path", () => {
  const manualFood: Food = {
    ...importedFood,
    id: "food-manual",
    name: "Manual Food",
    brand: null,
    source_type: "manual",
    source_id: null,
    serving_definitions: [
      {
        id: "manual-serving",
        label: "1 cup",
        quantity: "1",
        unit: "cup",
        gram_weight: "170.000000",
        is_default: true,
        source: "manual",
        is_user_confirmed: true,
      },
    ],
  };

  expect(initialServingId(manualFood)).toBe("manual-serving");
  expect(
    buildLogInput({
      foodId: manualFood.id,
      date: "2026-07-08",
      amount: "2",
      unit: "serving",
      selectedServingId: initialServingId(manualFood),
    }).serving_definition_id,
  ).toBe("manual-serving");
});

test("log form display formatting trims initial amounts and serving gram weights", () => {
  expect(formatInitialLogAmount("9.000000")).toBe("9");
  expect(formatInitialLogAmount("1.250000")).toBe("1.25");
  expect(formatInitialLogAmount(null)).toBe("1");
  expect(formatServingGramWeight("100.000000")).toBe("100g");
  expect(formatServingGramWeight("85.500000")).toBe("85.5g");
  expect(formatServingGramWeight(null)).toBeNull();
});
