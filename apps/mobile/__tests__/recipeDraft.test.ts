import type { Food } from "../src/features/foods/api/types";
import {
  applyImportedIngredient,
  buildRecipePayload,
  canPublishRecipe,
  emptyRecipeDraft,
  formatIngredientAmount,
  formatRecipeIngredientDetail,
  formatServingChoiceLabel,
  ingredientForFood,
  moveIngredient,
  recipeToDraft,
  switchIngredientMode,
  usefulServingDefinitions,
  validateRecipeDraft,
} from "../src/features/recipes/utils/recipeDraft";
import { formatRecipeTotal } from "../src/features/recipes/utils/recipeDisplay";
import { convertedGramsPreview, massToGrams } from "../src/features/recipes/utils/massUnits";

const food: Food = {
  id: "food-1",
  name: "Black Beans",
  brand: "Pantry Co",
  source_type: "manual",
  is_recipe: false,
  serving_definitions: [
    {
      id: "serving-1",
      label: "1 cup",
      quantity: "1",
      unit: "cup",
      gram_weight: "170",
      is_default: true,
      source: "manual",
      is_user_confirmed: true,
    },
  ],
  nutrients: [],
};

const usdaFood: Food = {
  ...food,
  id: "food-2",
  name: "Onions, raw",
  brand: null,
  source_type: "usda",
  source_id: "11282",
};

test("recipe payload maps ordered gram and serving ingredients", () => {
  const gramIngredient = switchIngredientMode(ingredientForFood(food), "g");
  const servingIngredient = ingredientForFood(usdaFood);
  const payload = buildRecipePayload({
    ...emptyRecipeDraft(),
    name: "Bean Bowl",
    notes: "batch",
    servingCountYield: "4",
    finalCookedWeightGrams: "900",
    ingredients: [gramIngredient, servingIngredient],
  });

  expect(payload).toEqual({
    name: "Bean Bowl",
    notes: "batch",
    serving_count_yield: "4",
    final_cooked_weight_grams: "900",
    final_cooked_weight_display_quantity: "900",
    final_cooked_weight_display_unit: "g",
    ingredients: [
      {
        food_item_id: "food-1",
        position: 0,
        amount_quantity: "100",
        amount_unit: "g",
        serving_definition_id: null,
        preparation_note: null,
        amount_display_quantity: "100",
        amount_display_unit: "g",
      },
      {
        food_item_id: "food-2",
        position: 1,
        amount_quantity: "1",
        amount_unit: "serving",
        serving_definition_id: "serving-1",
        preparation_note: null,
        amount_display_quantity: null,
        amount_display_unit: null,
      },
    ],
  });
});

test("mass conversion normalizes grams ounces and pounds without float arithmetic", () => {
  expect(massToGrams("500", "g")).toBe("500");
  expect(massToGrams("28", "oz")).toBe("793.786648");
  expect(massToGrams("1", "lb")).toBe("453.59237");
  expect(convertedGramsPreview("2", "lb")).toBe("907.18474 g");
});

test("recipe payload normalizes ingredient and final cooked mass units to grams", () => {
  const ingredient = { ...ingredientForFood(food), amountUnit: "g" as const, amountQuantity: "28", massUnit: "oz" as const };
  const payload = buildRecipePayload({
    ...emptyRecipeDraft(),
    name: "Tomatoes",
    finalCookedWeightGrams: "2",
    finalCookedWeightUnit: "lb",
    ingredients: [ingredient],
  });
  expect(payload?.final_cooked_weight_grams).toBe("907.18474");
  expect(payload?.ingredients[0].amount_quantity).toBe("793.786648");
});

test("switching ingredient modes clears incompatible serving state and formats amounts", () => {
  const servingIngredient = ingredientForFood(food);
  expect(formatIngredientAmount(servingIngredient)).toBe("1 1 cup");

  const gramIngredient = switchIngredientMode(servingIngredient, "g");
  expect(gramIngredient.servingDefinitionId).toBeNull();
  expect(gramIngredient.amountQuantity).toBe("100");
  expect(formatIngredientAmount(gramIngredient)).toBe("100 g");

  const backToServing = switchIngredientMode(gramIngredient, "serving");
  expect(backToServing.servingDefinitionId).toBe("serving-1");
});

test("mass to serving switching clears display metadata from payload", () => {
  const ozIngredient = { ...ingredientForFood(food), amountUnit: "g" as const, amountQuantity: "28", massUnit: "oz" as const };
  const servingIngredient = switchIngredientMode(ozIngredient, "serving");
  const payload = buildRecipePayload({ ...emptyRecipeDraft(), name: "Switch", ingredients: [servingIngredient] });
  expect(payload?.ingredients[0]).toEqual(expect.objectContaining({
    amount_quantity: "1",
    amount_unit: "serving",
    serving_definition_id: "serving-1",
    amount_display_quantity: null,
    amount_display_unit: null,
  }));
});

test("lb to serving and repeated switching preserve payload invariants", () => {
  const lbIngredient = { ...ingredientForFood(food), amountUnit: "g" as const, amountQuantity: "1", massUnit: "lb" as const };
  const serving = switchIngredientMode(lbIngredient, "serving");
  const mass = switchIngredientMode(serving, "g");
  const servingAgain = switchIngredientMode(mass, "serving");
  const servingPayload = buildRecipePayload({ ...emptyRecipeDraft(), name: "Switch", ingredients: [servingAgain] });
  const massPayload = buildRecipePayload({ ...emptyRecipeDraft(), name: "Switch", ingredients: [mass] });
  expect(servingPayload?.ingredients[0].serving_definition_id).toBe("serving-1");
  expect(servingPayload?.ingredients[0].amount_display_unit).toBeNull();
  expect(massPayload?.ingredients[0].serving_definition_id).toBeNull();
  expect(massPayload?.ingredients[0].amount_display_unit).toBe("g");
});

test("ingredient ordering helper moves items without mutating draft state", () => {
  const first = ingredientForFood(food);
  const second = ingredientForFood(usdaFood);
  const moved = moveIngredient([first, second], 1, -1);
  expect(moved.map((ingredient) => ingredient.food.id)).toEqual(["food-2", "food-1"]);
});

test("recipe draft initialization preserves order and does not drop loaded ingredients", () => {
  const result = recipeToDraft(
    {
      id: "recipe-1",
      user_id: "user-1",
      name: "Ordered",
      created_at: "2026-07-10T00:00:00Z",
      updated_at: "2026-07-10T00:00:00Z",
      ingredients: [
        {
          id: "ingredient-2",
          recipe_id: "recipe-1",
          food_item_id: "food-2",
          position: 1,
          amount_quantity: "2.000000",
          amount_unit: "serving",
          serving_definition_id: "serving-1",
        },
        {
          id: "ingredient-1",
          recipe_id: "recipe-1",
          food_item_id: "food-1",
          position: 0,
          amount_quantity: "100.000000",
          amount_unit: "g",
          serving_definition_id: null,
        },
      ],
    },
    [food, usdaFood],
  );

  expect(result.ok).toBe(true);
  if (result.ok) {
    expect(result.draft.ingredients.map((ingredient) => ingredient.food.id)).toEqual(["food-1", "food-2"]);
  }
});

test("recipe draft preserves selected mass unit while editing before persistence", () => {
  const ingredient = { ...ingredientForFood(food), amountUnit: "g" as const, amountQuantity: "28", massUnit: "oz" as const };
  const draft = {
    ...emptyRecipeDraft(),
    name: "Round trip",
    finalCookedWeightGrams: "2",
    finalCookedWeightUnit: "lb" as const,
    ingredients: [ingredient],
  };
  expect(draft.finalCookedWeightUnit).toBe("lb");
  expect(draft.ingredients[0].massUnit).toBe("oz");
  expect(formatIngredientAmount(draft.ingredients[0])).toBe("28 oz");
});

test("recipe draft restores persisted display mass units when present", () => {
  const result = recipeToDraft(
    {
      id: "recipe-1",
      user_id: "user-1",
      name: "Display Units",
      final_cooked_weight_grams: "907.184740",
      final_cooked_weight_display_quantity: "2.000000",
      final_cooked_weight_display_unit: "lb",
      created_at: "2026-07-10T00:00:00Z",
      updated_at: "2026-07-10T00:00:00Z",
      ingredients: [
        {
          id: "ingredient-1",
          recipe_id: "recipe-1",
          food_item_id: "food-1",
          position: 0,
          amount_quantity: "793.786648",
          amount_unit: "g",
          serving_definition_id: null,
          amount_display_quantity: "28.000000",
          amount_display_unit: "oz",
        },
      ],
    },
    [food],
  );
  expect(result.ok).toBe(true);
  if (result.ok) {
    expect(result.draft.finalCookedWeightGrams).toBe("2");
    expect(result.draft.finalCookedWeightUnit).toBe("lb");
    expect(result.draft.ingredients[0].amountQuantity).toBe("28");
    expect(result.draft.ingredients[0].massUnit).toBe("oz");
  }
});

test("serving and ingredient detail display include labels and gram weights", () => {
  expect(formatServingChoiceLabel(food.serving_definitions[0])).toBe("1 cup (170g)");
  expect(
    formatRecipeIngredientDetail({
      food,
      amountQuantity: "1",
      amountUnit: "serving",
      servingDefinitionId: "serving-1",
    }),
  ).toBe("Black Beans - 1 1 cup");
  expect(
    formatRecipeIngredientDetail({
      food: usdaFood,
      amountQuantity: "28",
      amountUnit: "g",
      massUnit: "oz",
    }),
  ).toBe("Onions, raw - 28 oz");
});

test("useful serving choices keep valid ambiguous portions but sort them last", () => {
  expect(
    usefulServingDefinitions([
      { label: "1 RACC", gram_weight: "30" },
      { label: "Edible", gram_weight: "100" },
      { label: "1 medium", gram_weight: "110" },
      { label: "Quantity not specified", gram_weight: "55" },
      { label: "1 clove", gram_weight: null },
    ]).map((serving) => serving.label),
  ).toEqual(["1 medium", "1 RACC", "Edible"]);
});

test("recipe draft initialization reports missing food IDs instead of filtering ingredients", () => {
  const result = recipeToDraft(
    {
      id: "recipe-1",
      user_id: "user-1",
      name: "Missing",
      created_at: "2026-07-10T00:00:00Z",
      updated_at: "2026-07-10T00:00:00Z",
      ingredients: [
        {
          id: "ingredient-1",
          recipe_id: "recipe-1",
          food_item_id: "food-1",
          position: 0,
          amount_quantity: "100.000000",
          amount_unit: "g",
          serving_definition_id: null,
        },
        {
          id: "ingredient-2",
          recipe_id: "recipe-1",
          food_item_id: "missing-food",
          position: 1,
          amount_quantity: "1.000000",
          amount_unit: "serving",
          serving_definition_id: "serving-1",
        },
      ],
    },
    [food],
  );

  expect(result).toEqual({ ok: false, missingFoodItemIds: ["missing-food"] });
});

test("USDA import result is returned through same ingredient selection path", () => {
  const draft = { ...emptyRecipeDraft(), name: "Soup", ingredients: [ingredientForFood(food)] };
  const updated = applyImportedIngredient(draft, usdaFood);
  expect(updated.ingredients.map((ingredient) => ingredient.food.id)).toEqual(["food-1", "food-2"]);

  const duplicateImport = applyImportedIngredient(draft, food);
  expect(duplicateImport.ingredients[1].food.id).toBe("food-1");
});

test("publish eligibility requires at least one usable yield", () => {
  expect(canPublishRecipe({ servingCountYield: "", finalCookedWeightGrams: "" })).toBe(false);
  expect(canPublishRecipe({ servingCountYield: "0", finalCookedWeightGrams: "" })).toBe(false);
  expect(canPublishRecipe({ servingCountYield: "6", finalCookedWeightGrams: "" })).toBe(true);
  expect(canPublishRecipe({ servingCountYield: "", finalCookedWeightGrams: "1240" })).toBe(true);
});

test("recipe draft validation catches missing quantity and serving selection", () => {
  expect(validateRecipeDraft({ ...emptyRecipeDraft(), name: "" })).toBe("Recipe name is required.");
  expect(
    validateRecipeDraft({
      ...emptyRecipeDraft(),
      name: "Bad",
      ingredients: [{ ...ingredientForFood(food), amountQuantity: "" }],
    }),
  ).toBe("Ingredient amounts must be greater than zero.");
  expect(
    validateRecipeDraft({
      ...emptyRecipeDraft(),
      name: "Bad",
      ingredients: [{ ...ingredientForFood(food), servingDefinitionId: null }],
    }),
  ).toBe("Serving ingredients need a selected serving.");
});

test("recipe preview formatting preserves known zero and unknown contributors", () => {
  expect(
    formatRecipeTotal({
      nutrientId: "added_sugars",
      amountKnown: "0",
      amountEstimated: "0",
      unit: "g",
      hasUnknownContributors: false,
      unknownContributorCount: 0,
    }),
  ).toBe("0g");
  expect(
    formatRecipeTotal({
      nutrientId: "vitamin_d",
      amountKnown: "0",
      amountEstimated: "0",
      unit: "mcg",
      hasUnknownContributors: true,
      unknownContributorCount: 2,
    }),
  ).toBe("Unknown from 2 items");
  expect(
    formatRecipeTotal({
      nutrientId: "calcium",
      amountKnown: "24",
      amountEstimated: "0",
      unit: "mg",
      hasUnknownContributors: true,
      unknownContributorCount: 1,
    }),
  ).toBe("24mg + unknown from 1 item");
});
