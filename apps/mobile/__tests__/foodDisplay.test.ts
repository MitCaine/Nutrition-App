import type { Food } from "../src/features/foods/api/types";
import {
  defaultServing,
  formatFoodNutrientLabel,
  formatNutrientAmount,
  formatResolvedFoodAmount,
  formatResolvedFoodNutrient,
  primaryServingLabel,
  selectedResolvedFoodAmount,
} from "../src/features/foods/utils/foodDisplay";
import type { ResolvedFoodAmount } from "../src/features/foods/api/types";

const usdaFood: Food = {
  id: "food-usda",
  name: "Example Protein Bar",
  brand: "Example Foods",
  source_type: "usda",
  source_id: "555000",
  is_recipe: false,
  source_kind: "usda", source_label: "USDA", is_favorite: false, can_favorite: true,
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
  nutrients: [
    {
      id: "nutrient-calories",
      nutrient_id: "calories",
      amount: "300.000000",
      unit: "kcal",
      basis: "per_100g",
      data_status: "known",
      source: "usda_fdc",
      is_user_confirmed: false,
      original_amount: "300.000000",
      original_unit: "KCAL",
      original_text: "1008",
    },
    {
      id: "nutrient-cholesterol",
      nutrient_id: "cholesterol",
      amount: "0.000000",
      unit: "mg",
      basis: "per_100g",
      data_status: "zero",
      source: "usda_fdc",
      is_user_confirmed: false,
    },
    {
      id: "nutrient-vitamin-d",
      nutrient_id: "vitamin_d",
      amount: null,
      unit: "mcg",
      basis: "per_100g",
      data_status: "unknown",
      source: "usda_fdc",
      is_user_confirmed: false,
    },
  ],
};

test("USDA food detail helpers render known zero and unknown nutrients distinctly", () => {
  const nutrients = Object.fromEntries(usdaFood.nutrients.map((nutrient) => [nutrient.nutrient_id, nutrient]));

  expect(formatNutrientAmount(nutrients.calories)).toBe("300kcal");
  expect(formatNutrientAmount(nutrients.cholesterol)).toBe("0mg");
  expect(formatNutrientAmount(nutrients.vitamin_d)).toBe("unknown");
  expect(formatFoodNutrientLabel(nutrients.vitamin_d)).toBe("Vitamin D");
});

test("USDA branded default serving is preferred and 100 g remains available", () => {
  expect(defaultServing(usdaFood.serving_definitions)?.id).toBe("serving-bar");
  expect(primaryServingLabel(usdaFood)).toBe("1 bar");
  expect(usdaFood.serving_definitions.some((serving) => serving.label === "100 g")).toBe(true);
});

const resolvedAmounts: ResolvedFoodAmount[] = [
  {
    amount_definition_id: "serving-bar",
    display_label: "1 bar",
    is_default: true,
    entered_quantity: "1",
    semantic_amount_mode: "serving",
    resolved_grams: "50.000000",
    valid_for_logging: true,
    nutrients: [
      { nutrient_id: "calories", amount: "150.000000", unit: "kcal", data_status: "known", source_basis: "per_100g" },
      { nutrient_id: "vitamin_d", amount: null, unit: "mcg", data_status: "unknown", source_basis: "per_100g" },
    ],
  },
  {
    amount_definition_id: "count-only",
    display_label: "1 serving",
    is_default: false,
    entered_quantity: "1",
    semantic_amount_mode: "serving",
    resolved_grams: null,
    valid_for_logging: true,
    nutrients: [
      { nutrient_id: "calories", amount: "240.000000", unit: "kcal", data_status: "estimated", source_basis: "per_serving" },
    ],
  },
];

test("food detail formats backend-resolved nutrients without scaling raw basis values", () => {
  expect(formatResolvedFoodAmount(resolvedAmounts[0])).toBe("1 bar (50 g)");
  expect(formatResolvedFoodNutrient(resolvedAmounts[0].nutrients[0])).toBe("150kcal");
  expect(formatResolvedFoodNutrient(resolvedAmounts[0].nutrients[1])).toBe("unknown");
});

test("food detail amount selection uses resolved options and keeps count-only servings", () => {
  expect(selectedResolvedFoodAmount(resolvedAmounts, null)?.amount_definition_id).toBe("serving-bar");
  const countOnly = selectedResolvedFoodAmount(resolvedAmounts, "count-only");
  expect(countOnly?.resolved_grams).toBeNull();
  expect(countOnly?.nutrients[0].data_status).toBe("estimated");
  expect(formatResolvedFoodAmount(countOnly!)).toBe("1 serving");
  expect(formatResolvedFoodNutrient(countOnly!.nutrients[0])).toBe("240kcal");
});

test("manual food detail helpers keep existing serving and nutrient behavior", () => {
  const manualFood: Food = {
    ...usdaFood,
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
    nutrients: [
      {
        id: "manual-protein",
        nutrient_id: "protein",
        amount: "20.000000",
        unit: "g",
        basis: "per_serving",
        data_status: "known",
        source: "manual",
        is_user_confirmed: true,
      },
    ],
  };

  expect(primaryServingLabel(manualFood)).toBe("1 cup");
  expect(formatNutrientAmount(manualFood.nutrients[0])).toBe("20g");
});
