import {
  buildCustomServingDefinition,
  formatServingChoiceLabel,
  formatServingMultiplier,
  reconcileRecipeDraftFoodAfterServingManagement,
  validateRecipeDraft,
} from "../src/features/recipes/utils/recipeDraft";
import type { Food } from "../src/features/foods/api/types";
import type { RecipeDraft } from "../src/features/recipes/utils/recipeDraft";

test("serving choices do not repeat a gram weight already present in the label", () => {
  expect(formatServingChoiceLabel({ label: "100 g", gram_weight: "100" })).toBe("100 g");
  expect(formatServingChoiceLabel({ label: "100 grams", gram_weight: "100.000000" })).toBe("100 grams");
});

test("serving choices retain useful gram context for non-mass labels", () => {
  expect(formatServingChoiceLabel({ label: "1 slice", gram_weight: "2" })).toBe("1 slice (2g)");
});

test("recipe serving creation derives total gram weight from quantity and per-unit weight", () => {
  expect(buildCustomServingDefinition({
    quantity: "2",
    unit: "slices",
    gramWeightPerUnit: "28",
    customLabel: "",
    useCustomLabel: false,
  })).toEqual({
    label: "2 slices",
    quantity: "2",
    unit: "slice",
    gram_weight: "56",
    is_default: false,
  });
});

test("recipe serving gram multiplication preserves decimal precision", () => {
  expect(buildCustomServingDefinition({
    quantity: "1.5",
    unit: "slice",
    gramWeightPerUnit: "28.35",
    customLabel: "",
    useCustomLabel: false,
  })?.gram_weight).toBe("42.525");
});

test("recipe serving creation supports an explicit display-name override", () => {
  expect(buildCustomServingDefinition({
    quantity: "2",
    unit: "slice",
    gramWeightPerUnit: "28",
    customLabel: "2 thick-cut slices",
    useCustomLabel: true,
  })?.label).toBe("2 thick-cut slices");
});

test("recipe serving creation requires positive structured values", () => {
  expect(buildCustomServingDefinition({
    quantity: "2",
    unit: "slice",
    gramWeightPerUnit: "",
    customLabel: "",
    useCustomLabel: false,
  })).toBeNull();
});

test("recipe ingredient serving count is distinct from the selected serving size", () => {
  expect(formatServingMultiplier("1", "2 slices")).toBe("2 slices");
  expect(formatServingMultiplier("3", "2 slices")).toBe("3 × 2 slices");
});

// E2_86_RECONCILIATION_TESTS

function foodForServingManagement(
  servingDefinitions: Food["serving_definitions"],
): Food {
  return {
    id: "food-managed",
    name: "Managed Food",
    brand: null,
    notes: null,
    source_type: "manual",
    source_id: null,
    is_recipe: false,
    source_kind: "manual",
    source_label: "Manual",
    is_favorite: false,
    can_favorite: true,
    serving_definitions: servingDefinitions,
    nutrients: [],
  };
}

test("Recipe draft remaps regenerated serving IDs only by authoritative serving semantics", () => {
  const originalFood = foodForServingManagement([
    {
      id: "old-base",
      label: "100 g",
      quantity: "100.000000",
      unit: "g",
      gram_weight: "100.000000",
      is_default: true,
      source: "manual",
      is_user_confirmed: true,
    },
    {
      id: "old-cup",
      label: "1 cup",
      quantity: "1.000000",
      unit: "cup",
      gram_weight: "240.000000",
      is_default: false,
      source: "manual",
      is_user_confirmed: true,
    },
  ]);

  const updatedFood = foodForServingManagement([
    {
      id: "new-base",
      label: "100 g",
      quantity: "100",
      unit: "g",
      gram_weight: "100",
      is_default: true,
      source: "manual",
      is_user_confirmed: true,
    },
    {
      id: "new-cup",
      label: "Cup serving renamed",
      quantity: "1",
      unit: "cup",
      gram_weight: "240",
      is_default: false,
      source: "manual",
      is_user_confirmed: true,
    },
  ]);

  const draft: RecipeDraft = {
    name: "Recipe",
    notes: "",
    servingCountYield: "",
    legacyCookedWeight: null,
    ingredients: [
      {
        localId: "serving-ingredient",
        food: originalFood,
        amountQuantity: "2",
        amountUnit: "serving",
        massUnit: "g",
        servingDefinitionId: "old-cup",
        preparationNote: "",
      },
      {
        localId: "weight-ingredient",
        food: originalFood,
        amountQuantity: "50",
        amountUnit: "g",
        massUnit: "g",
        servingDefinitionId: null,
        preparationNote: "",
      },
    ],
  };

  const reconciled =
    reconcileRecipeDraftFoodAfterServingManagement(draft, updatedFood);

  expect(reconciled.ingredients[0]!.food).toBe(updatedFood);
  expect(reconciled.ingredients[0]!.servingDefinitionId).toBe("new-cup");
  expect(reconciled.ingredients[0]!.amountQuantity).toBe("2");
  expect(reconciled.ingredients[1]!.food).toBe(updatedFood);
  expect(reconciled.ingredients[1]!.amountQuantity).toBe("50");
});

test("Recipe draft requires explicit reselection when a managed serving has no safe successor", () => {
  const originalFood = foodForServingManagement([
    {
      id: "old-base",
      label: "100 g",
      quantity: "100",
      unit: "g",
      gram_weight: "100",
      is_default: true,
      source: "manual",
      is_user_confirmed: true,
    },
    {
      id: "old-scoop",
      label: "1 scoop",
      quantity: "1",
      unit: "scoop",
      gram_weight: "30",
      is_default: false,
      source: "manual",
      is_user_confirmed: true,
    },
  ]);

  const updatedFood = foodForServingManagement([
    {
      id: "new-base",
      label: "100 g",
      quantity: "100",
      unit: "g",
      gram_weight: "100",
      is_default: true,
      source: "manual",
      is_user_confirmed: true,
    },
  ]);

  const draft: RecipeDraft = {
    name: "Recipe",
    notes: "",
    servingCountYield: "",
    legacyCookedWeight: null,
    ingredients: [{
      localId: "ingredient",
      food: originalFood,
      amountQuantity: "1",
      amountUnit: "serving",
      massUnit: "g",
      servingDefinitionId: "old-scoop",
      preparationNote: "",
    }],
  };

  const reconciled =
    reconcileRecipeDraftFoodAfterServingManagement(draft, updatedFood);

  expect(reconciled.ingredients[0]!.servingDefinitionId).toBeNull();
  expect(validateRecipeDraft(reconciled)).toBe(
    "Serving ingredients need a selected serving.",
  );
});

test("Recipe draft refuses ambiguous serving successors instead of substituting one", () => {
  const originalFood = foodForServingManagement([
    {
      id: "old-serving",
      label: "1 piece",
      quantity: "1",
      unit: "piece",
      gram_weight: "25",
      is_default: true,
      source: "manual",
      is_user_confirmed: true,
    },
  ]);

  const updatedFood = foodForServingManagement([
    {
      id: "successor-a",
      label: "Piece A",
      quantity: "1.000000",
      unit: "piece",
      gram_weight: "25.000000",
      is_default: true,
      source: "manual",
      is_user_confirmed: true,
    },
    {
      id: "successor-b",
      label: "Piece B",
      quantity: "1",
      unit: "piece",
      gram_weight: "25",
      is_default: false,
      source: "manual",
      is_user_confirmed: true,
    },
  ]);

  const draft: RecipeDraft = {
    name: "Recipe",
    notes: "",
    servingCountYield: "",
    legacyCookedWeight: null,
    ingredients: [{
      localId: "ingredient",
      food: originalFood,
      amountQuantity: "3",
      amountUnit: "serving",
      massUnit: "g",
      servingDefinitionId: "old-serving",
      preparationNote: "",
    }],
  };

  const reconciled =
    reconcileRecipeDraftFoodAfterServingManagement(draft, updatedFood);

  expect(reconciled.ingredients[0]!.servingDefinitionId).toBeNull();
});
