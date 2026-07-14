import type {
  Food,
  FoodResolvedNutrition,
  ResolvedFoodAmount,
} from "../src/features/foods/api/types";
import {
  buildLogInput,
  foodDetailLogInitialAmount,
  resolveCreateLogInitialization,
  shouldApplyCreateLogInitialization,
} from "../src/features/logging/utils/logFoodForm";

const food: Food = {
  id: "food-1",
  name: "Food",
  source_type: "manual",
  source_id: null,
  is_recipe: false,
  serving_definitions: [
    {
      id: "serving-default",
      label: "1 cup",
      quantity: "1",
      unit: "cup",
      gram_weight: "200",
      is_default: true,
      source: "manual",
      is_user_confirmed: true,
    },
    {
      id: "serving-grams",
      label: "100 g",
      quantity: "100",
      unit: "g",
      gram_weight: "100",
      is_default: false,
      source: "manual",
      is_user_confirmed: true,
    },
  ],
  nutrients: [],
};

function amount(
  id: string,
  mode: "serving" | "g" = "serving",
  enteredQuantity = "1.000000",
  isDefault = false,
): ResolvedFoodAmount {
  return {
    amount_definition_id: id,
    display_label: id,
    is_default: isDefault,
    entered_quantity: enteredQuantity,
    semantic_amount_mode: mode,
    resolved_grams: mode === "g" ? enteredQuantity : "200",
    valid_for_logging: true,
    nutrients: [],
  };
}

function resolved(
  amounts: ResolvedFoodAmount[],
  authority: FoodResolvedNutrition["nutrition_authority"] = "food_item",
): FoodResolvedNutrition {
  return {
    nutrition_authority: authority,
    recipe_id: authority === "recipe_publication_revision" ? "recipe-1" : null,
    recipe_publication_revision_id:
      authority === "recipe_publication_revision" ? "revision-current" : null,
    amounts,
  };
}

test.each([
  ["Manual serving", amount("serving-default", "serving", "2.500000")],
  ["USDA serving", amount("usda-portion", "serving", "1.250000")],
  ["Manual grams", amount("serving-grams", "g", "75.500000")],
])("Food Detail passes %s identity, mode, and quantity", (_name, selected) => {
  expect(foodDetailLogInitialAmount(selected)).toEqual({
    amountDefinitionId: selected.amount_definition_id,
    amountQuantity: selected.entered_quantity,
    amountUnit: selected.semantic_amount_mode,
  });
});

test("managed Recipe revision amount ID is passed and submitted unchanged", () => {
  const selected = amount("revision-amount-id", "serving", "3.000000", true);
  const initial = foodDetailLogInitialAmount(selected);
  const initialization = resolveCreateLogInitialization(
    { ...food, source_type: "recipe", is_recipe: true },
    resolved([selected], "recipe_publication_revision"),
    initial,
  );

  expect(initialization).toEqual({
    amount: "3",
    unit: "serving",
    selectedAmountId: "revision-amount-id",
    selectedAmountMode: "serving",
  });
  expect(buildLogInput({
    foodId: "food-1",
    date: "2026-07-13",
    amount: initialization.amount,
    unit: initialization.unit,
    selectedServingId: initialization.selectedAmountId,
    selectedAmountMode: initialization.selectedAmountMode,
  }).serving_definition_id).toBe("revision-amount-id");
});

test("gram selection preserves its amount ID and normalized quantity", () => {
  const selected = amount("serving-grams", "g", "75.500000");
  const initialization = resolveCreateLogInitialization(
    food,
    resolved([selected]),
    foodDetailLogInitialAmount(selected),
  );
  expect(initialization.amount).toBe("75.5");
  expect(buildLogInput({
    foodId: food.id,
    date: "2026-07-13",
    amount: initialization.amount,
    unit: initialization.unit,
    selectedServingId: initialization.selectedAmountId,
    selectedAmountMode: initialization.selectedAmountMode,
  }).serving_definition_id).toBe("serving-grams");
});

test("missing selection retains existing Food default behavior", () => {
  expect(resolveCreateLogInitialization(food, resolved([amount("serving-default")]), undefined)).toEqual({
    amount: "1",
    unit: "serving",
    selectedAmountId: "serving-default",
    selectedAmountMode: "serving",
  });
});

test.each(["stale-id", "another-food-id"])(
  "%s is rejected locally and falls back to the current default",
  (amountDefinitionId) => {
    expect(resolveCreateLogInitialization(
      food,
      resolved([amount("serving-default", "serving", "1", true)]),
      { amountDefinitionId, amountQuantity: "9", amountUnit: "serving" },
    )).toEqual({
      amount: "1",
      unit: "serving",
      selectedAmountId: "serving-default",
      selectedAmountMode: "serving",
    });
  },
);

test("an amount ID with the wrong semantic mode is rejected locally", () => {
  expect(resolveCreateLogInitialization(
    food,
    resolved([amount("serving-default", "serving", "1", true)]),
    { amountDefinitionId: "serving-default", amountQuantity: "9", amountUnit: "g" },
  ).amount).toBe("1");
});

test("invalid route quantity falls back without discarding a valid selection", () => {
  expect(resolveCreateLogInitialization(
    food,
    resolved([amount("serving-default", "serving", "1", true)]),
    { amountDefinitionId: "serving-default", amountQuantity: "-2", amountUnit: "serving" },
  )).toEqual({
    amount: "1",
    unit: "serving",
    selectedAmountId: "serving-default",
    selectedAmountMode: "serving",
  });
});

test("republish removes revision A selection without reinterpreting it as revision B", () => {
  const initialization = resolveCreateLogInitialization(
    { ...food, source_type: "recipe", is_recipe: true },
    resolved([amount("revision-b-default", "serving", "1", true)], "recipe_publication_revision"),
    { amountDefinitionId: "revision-a-default", amountQuantity: "4", amountUnit: "serving" },
  );
  expect(initialization.selectedAmountId).toBe("revision-b-default");
  expect(initialization.amount).toBe("1");
});

test("edit mode and an already initialized create screen do not reapply route state", () => {
  expect(shouldApplyCreateLogInitialization({
    isEditMode: true,
    initializedFoodId: null,
    foodId: food.id,
    authoritativeChoicesReady: true,
  })).toBe(false);
  expect(shouldApplyCreateLogInitialization({
    isEditMode: false,
    initializedFoodId: food.id,
    foodId: food.id,
    authoritativeChoicesReady: true,
  })).toBe(false);
});

test("Food Detail omits invalid amount state", () => {
  expect(foodDetailLogInitialAmount({ ...amount("bad"), valid_for_logging: false })).toBeUndefined();
});
