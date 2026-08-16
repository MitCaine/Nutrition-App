import React from "react";
import { TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { Food } from "../src/features/foods/api/types";
import type { RecipeDraft } from "../src/features/recipes/utils/recipeDraft";

jest.mock("../src/features/recipes/hooks/useRecipes", () => ({
  useRecipeMutations: () => ({
    createRecipe: { isPending: false, isError: false, mutateAsync: jest.fn() },
    updateRecipe: { isPending: false, isError: false, mutateAsync: jest.fn() },
  }),
}));

jest.mock("../src/runtime/NutritionRuntimeContext", () => ({
  useNutritionRuntime: () => ({
    foods: { createServingDefinition: jest.fn() },
  }),
}));

import { RecipeFormScreen } from "../src/features/recipes/screens/RecipeFormScreen";

const food: Food = {
  id: "food-1",
  name: "Oats",
  brand: null,
  notes: null,
  source_type: "manual",
  source_id: null,
  is_recipe: false,
  source_kind: "manual",
  source_label: "Manual",
  is_favorite: false,
  can_favorite: true,
  serving_definitions: [
    { id: "base", label: "100 g", quantity: "100", unit: "g", gram_weight: "100", is_default: true, source: "manual", is_user_confirmed: true },
    { id: "slice", label: "1 slice", quantity: "1", unit: "slice", gram_weight: "30", is_default: false, source: "manual", is_user_confirmed: true },
  ],
  nutrients: [],
};

const draft: RecipeDraft = {
  name: "Test Recipe",
  notes: "",
  servingCountYield: "",
  legacyCookedWeight: null,
  ingredients: [{
    localId: "ingredient-1",
    food,
    amountQuantity: "1",
    amountUnit: "serving",
    massUnit: "g",
    servingDefinitionId: "slice",
    preparationNote: "",
  }],
};

test("Recipe custom serving creation uses the shared structured unit picker", async () => {
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(RecipeFormScreen, {
      draft,
      setDraft: jest.fn(),
      onCancel: jest.fn(),
      onSaved: jest.fn(),
      onAddIngredient: jest.fn(),
    }));
  });

  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Create a new serving size for Oats" }).props.onPress());

  const trigger = renderer.root.findByProps({
    accessibilityLabel: "Choose unit for serving size for Oats, current unit not selected",
  });
  expect(trigger.props.accessibilityState).toMatchObject({ expanded: false, disabled: false });

  await act(async () => trigger.props.onPress());
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "cup" }).props.onPress());

  expect(renderer.root.findByProps({
    accessibilityLabel: "Choose unit for serving size for Oats, current unit cup",
  })).toBeDefined();
  expect(renderer.root.findAllByType(TextInput).find((node) => node.props.accessibilityLabel === "Unit")?.props.value).toBe("cup");
  expect(renderer.root.findAllByType(TextInput).find((node) => node.props.accessibilityLabel === "Oats grams per cup")).toBeDefined();

  await act(async () => renderer.unmount());
});
