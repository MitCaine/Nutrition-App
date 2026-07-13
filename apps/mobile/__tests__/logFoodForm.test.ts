import type { Food } from "../src/features/foods/api/types";
import {
  buildLogInput,
  buildLogUpdateInput,
  editServingChoices,
  formatInitialLogAmount,
  formatServingGramWeight,
  initialServingId,
  initialEditAmountId,
} from "../src/features/logging/utils/logFoodForm";
import type { DailyLog, DailyLogEditContext } from "../src/features/logging/api/types";

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

test("count-only serving remains selectable for resolver-backed logging", () => {
  const countOnlyFood: Food = {
    ...importedFood,
    id: "food-count-only",
    name: "Count Only Food",
    source_type: "recipe",
    source_id: "recipe-1",
    is_recipe: true,
    serving_definitions: [
      {
        id: "count-serving",
        label: "1 serving",
        quantity: "1",
        unit: "serving",
        gram_weight: null,
        is_default: true,
        source: "recipe",
        is_user_confirmed: true,
      },
    ],
    nutrients: [
      {
        id: "count-protein",
        nutrient_id: "protein",
        amount: "12.5",
        unit: "g",
        basis: "per_serving",
        data_status: "known",
        source: "recipe",
        is_user_confirmed: true,
      },
    ],
  };

  expect(initialServingId(countOnlyFood)).toBe("count-serving");
  expect(buildLogInput({
    foodId: countOnlyFood.id,
    date: "2026-07-08",
    amount: "0.5",
    unit: "serving",
    selectedServingId: initialServingId(countOnlyFood),
  })).toEqual({
    food_item_id: "food-count-only",
    logged_date: "2026-07-08",
    amount_quantity: "0.5",
    amount_unit: "serving",
    serving_definition_id: "count-serving",
  });
});

test("log form display formatting trims initial amounts and serving gram weights", () => {
  expect(formatInitialLogAmount("9.000000")).toBe("9");
  expect(formatInitialLogAmount("1.250000")).toBe("1.25");
  expect(formatInitialLogAmount(null)).toBe("1");
  expect(formatServingGramWeight("100.000000")).toBe("100g");
  expect(formatServingGramWeight("85.500000")).toBe("85.5g");
  expect(formatServingGramWeight(null)).toBeNull();
});

test("log update input omits creation-only food item id", () => {
  expect(buildLogUpdateInput({
    food_item_id: "food-1",
    logged_date: "2026-07-08",
    amount_quantity: "2",
    amount_unit: "g",
    serving_definition_id: null,
  })).toEqual({
    logged_date: "2026-07-08",
    amount_quantity: "2",
    amount_unit: "g",
    serving_definition_id: null,
  });
});

test("revision-backed edit choices ignore current projection servings", () => {
  const log: DailyLog = {
    id: "log-1",
    food_item_id: "recipe-food",
    food_name_snapshot: "Historical Recipe",
    is_editable: true,
    source_food_available: true,
    edit_block_reason: null,
    logged_date: "2026-07-13",
    amount_quantity: "1",
    amount_unit: "serving",
    serving_definition_id: null,
  };
  const context: DailyLogEditContext = {
    log_id: log.id,
    source_food_available: true,
    is_revision_backed: true,
    recipe_publication_revision_id: "revision-1",
    selected_amount_definition_id: "historical-amount",
    amount_choices: [
      {
        amount_definition_id: "historical-amount",
        display_label: "1 historical serving",
        semantic_mode: "serving",
        display_quantity: "1",
        display_unit: "serving",
        gram_equivalent: "120",
        is_default: true,
        is_selected: true,
      },
      {
        amount_definition_id: "historical-grams",
        display_label: "g",
        semantic_mode: "g",
        display_quantity: null,
        display_unit: "g",
        gram_equivalent: null,
        is_default: false,
        is_selected: false,
      },
    ],
  };
  const currentProjection: Food = {
    ...importedFood,
    id: log.food_item_id,
    source_type: "recipe",
    source_id: "recipe-1",
    is_recipe: true,
    serving_definitions: [
      {
        ...importedFood.serving_definitions[0],
        id: "current-projection-serving",
        label: "1 current serving",
      },
    ],
  };

  expect(initialEditAmountId(currentProjection, log, context)).toBe("historical-amount");
  expect(editServingChoices(currentProjection, context)).toEqual([
    {
      id: "historical-amount",
      label: "1 historical serving",
      gram_weight: "120",
      is_default: true,
    },
  ]);
  expect(editServingChoices(currentProjection, context).map((choice) => choice.id)).not.toContain(
    "current-projection-serving",
  );
  expect(buildLogUpdateInput(buildLogInput({
    foodId: log.food_item_id,
    date: log.logged_date,
    amount: "2",
    unit: "serving",
    selectedServingId: initialEditAmountId(currentProjection, log, context),
  }))).toEqual({
    logged_date: log.logged_date,
    amount_quantity: "2",
    amount_unit: "serving",
    serving_definition_id: "historical-amount",
  });
});

test("legacy and Manual Food edits retain projection serving choices", () => {
  const compatibilityContext: DailyLogEditContext = {
    log_id: "manual-log",
    source_food_available: true,
    is_revision_backed: false,
    recipe_publication_revision_id: null,
    selected_amount_definition_id: null,
    amount_choices: [],
  };
  expect(editServingChoices(importedFood, compatibilityContext).map((choice) => choice.id)).toEqual([
    "serving-100g",
    "serving-bar",
  ]);
});
