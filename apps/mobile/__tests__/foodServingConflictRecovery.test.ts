import React from "react";
import { Text, TextInput } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { Food } from "../src/features/foods/api/types";
import { RuntimeError } from "../src/runtime/RuntimeError";

const mockCreateFood = jest.fn();
const mockUpdateFood = jest.fn();

jest.mock("../src/features/foods/hooks/useFoods", () => ({
  useNutrients: () => ({ data: [], isLoading: false, isError: false, refetch: jest.fn() }),
  useFoodMutations: () => ({
    createFood: { mutateAsync: mockCreateFood, isPending: false },
    updateFood: { mutateAsync: mockUpdateFood, isPending: false },
  }),
}));

import { FoodFormScreen } from "../src/features/foods/screens/FoodFormScreen";

const editableFood: Food = {
  id: "food-edit",
  name: "Bacon",
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
    { id: "scoop", label: "1 scoop", quantity: "1", unit: "scoop", gram_weight: "30", is_default: false, source: "manual", is_user_confirmed: true },
  ],
  nutrients: [],
};

function textContent(node: TestRenderer.ReactTestInstance | string): string {
  return typeof node === "string"
    ? node
    : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join("");
}

beforeEach(() => {
  mockCreateFood.mockReset().mockResolvedValue({ id: "food-new" });
  mockUpdateFood.mockReset();
});

test("rejected Recipe serving changes restore saved servings without discarding other Food edits", async () => {
  mockUpdateFood.mockRejectedValueOnce(new RuntimeError({
    kind: "conflict",
    code: "food_update_recipe_serving_conflict",
    message: "This serving change would alter active Recipe ingredients.",
    retryable: false,
    mutationOutcome: "confirmed_non_commit",
    details: {
      food_id: editableFood.id,
      affected_recipes: [{ recipe_id: "recipe-1", recipe_name: "Breakfast", ingredients: [] }],
    },
  }));

  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(FoodFormScreen, {
      food: editableFood,
      onCancel: jest.fn(),
      onSaved: jest.fn(),
    }));
  });

  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Brand" }).props.onChangeText("Edited brand"));
  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Remove 1 scoop" }).props.onPress());
  expect(renderer.root.findAllByProps({ accessibilityLabel: "Edit 1 scoop" })).toHaveLength(0);

  await act(async () => renderer.root.findByProps({ accessibilityLabel: "Save food" }).props.onPress());

  expect(mockUpdateFood).toHaveBeenCalledTimes(1);
  expect(mockUpdateFood.mock.calls[0][0].input.brand).toBe("Edited brand");
  expect(mockUpdateFood.mock.calls[0][0].input.serving_definitions).toHaveLength(1);
  expect(renderer.root.findByProps({ accessibilityLabel: "Edit 1 scoop" })).toBeDefined();
  expect(renderer.root.findAllByType(TextInput).find((node) => node.props.accessibilityLabel === "Brand")?.props.value).toBe("Edited brand");

  const alert = renderer.root.findAllByType(Text).find((node) => node.props.accessibilityRole === "alert");
  expect(alert).toBeDefined();
  expect(textContent(alert!)).toContain("an active Recipe uses that serving");
  expect(textContent(alert!)).toContain("saved serving sizes have been restored");

  await act(async () => renderer.unmount());
});
