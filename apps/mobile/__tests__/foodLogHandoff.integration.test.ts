import React from "react";
import { Pressable, Text, TextInput } from "react-native";
import TestRenderer, { act, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import { logFoodRoute } from "../src/app/navigation/logFoodRoute";
import type { Food, FoodResolvedNutrition, ResolvedFoodAmount } from "../src/features/foods/api/types";
import { FoodDetailsScreen } from "../src/features/foods/screens/FoodDetailsScreen";
import type { DailyLog, DailyLogEditContext } from "../src/features/logging/api/types";
import { LogFoodScreen } from "../src/features/logging/screens/LogFoodScreen";

let mockFoodQuery: Record<string, unknown>;
let mockResolvedQuery: Record<string, unknown>;
let mockEditContextQuery: Record<string, unknown>;
const mockCreateLog = jest.fn(async () => undefined);
const mockUpdateLog = jest.fn(async () => undefined);

jest.mock("../src/features/foods/hooks/useFoods", () => ({
  useFood: () => mockFoodQuery,
  useFoodResolvedNutrition: () => mockResolvedQuery,
  useFoodMutations: () => ({
    deleteFood: { isPending: false, mutate: jest.fn() },
    duplicateFood: { mutate: jest.fn() },
  }),
}));

jest.mock("../src/features/logging/hooks/useLogs", () => ({
  useLogEditContext: () => mockEditContextQuery,
  useLogMutations: () => ({
    createLog: { mutateAsync: mockCreateLog },
    updateLog: { mutateAsync: mockUpdateLog },
  }),
  useDailyLogs: () => ({ data: [] }),
}));

const food: Food = {
  id: "food-a",
  name: "Food A",
  source_type: "manual",
  source_id: null,
  is_recipe: false,
  serving_definitions: [
    {
      id: "default-serving",
      label: "1 cup",
      quantity: "1",
      unit: "cup",
      gram_weight: "200",
      is_default: true,
      source: "manual",
      is_user_confirmed: true,
    },
    {
      id: "selected-serving",
      label: "1 bowl",
      quantity: "1",
      unit: "bowl",
      gram_weight: "300",
      is_default: false,
      source: "manual",
      is_user_confirmed: true,
    },
    {
      id: "grams-amount",
      label: "75 g",
      quantity: "75",
      unit: "g",
      gram_weight: "75",
      is_default: false,
      source: "manual",
      is_user_confirmed: true,
    },
  ],
  nutrients: [],
};

function amount(
  id: string,
  mode: "serving" | "g",
  quantity: string,
  isDefault = false,
): ResolvedFoodAmount {
  return {
    amount_definition_id: id,
    display_label: id,
    is_default: isDefault,
    entered_quantity: quantity,
    semantic_amount_mode: mode,
    resolved_grams: mode === "g" ? quantity : "200",
    valid_for_logging: true,
    nutrients: [],
  };
}

function nutrition(
  amounts: ResolvedFoodAmount[],
  authority: FoodResolvedNutrition["nutrition_authority"] = "food_item",
): FoodResolvedNutrition {
  return {
    nutrition_authority: authority,
    recipe_id: authority === "recipe_publication_revision" ? "recipe-1" : null,
    recipe_publication_revision_id:
      authority === "recipe_publication_revision" ? "revision-b" : null,
    amounts,
  };
}

beforeEach(() => {
  mockCreateLog.mockClear();
  mockUpdateLog.mockClear();
  mockFoodQuery = {
    data: food,
    isLoading: false,
    isError: false,
    error: null,
    refetch: jest.fn(),
  };
  mockResolvedQuery = {
    data: nutrition([
      amount("default-serving", "serving", "1", true),
      amount("selected-serving", "serving", "2.5"),
      amount("grams-amount", "g", "75"),
    ]),
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
    refetch: jest.fn(),
  };
  mockEditContextQuery = {
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
  };
});

async function render(element: React.ReactElement): Promise<ReactTestRenderer> {
  let renderer: ReactTestRenderer | undefined;
  await act(async () => {
    renderer = TestRenderer.create(element);
  });
  return renderer as ReactTestRenderer;
}

function textContent(node: ReactTestInstance): string {
  return node.children
    .map((child) => (typeof child === "string" ? child : textContent(child)))
    .join("");
}

function pressableWithText(root: ReactTestInstance, label: string): ReactTestInstance {
  return root
    .findAllByType(Pressable)
    .find((node) => textContent(node) === label) as ReactTestInstance;
}

function hasText(root: ReactTestInstance, value: string): boolean {
  return root.findAllByType(Text).some((node) => textContent(node) === value);
}

async function foodDetailSelection(selectionLabel: string) {
  const onLog = jest.fn();
  const renderer = await render(React.createElement(FoodDetailsScreen, {
    foodId: food.id,
    onBack: jest.fn(),
    onDeleted: jest.fn(),
    onEdit: jest.fn(),
    onLog,
  }));
  const radio = renderer.root
    .findAllByProps({ accessibilityRole: "radio" })
    .find((node) => node.props.accessibilityLabel.startsWith(selectionLabel)) as ReactTestInstance;
  await act(async () => radio.props.onPress());
  await act(async () => pressableWithText(renderer.root, "Log").props.onPress());
  return onLog.mock.calls[0][0];
}

async function renderLog(initialAmount?: {
  amountDefinitionId: string;
  amountQuantity: string;
  amountUnit: "serving" | "g";
}, overrideFood: Food = food): Promise<ReactTestRenderer> {
  mockFoodQuery = { ...mockFoodQuery, data: overrideFood };
  const route = logFoodRoute(overrideFood.id, initialAmount);
  return render(React.createElement(LogFoodScreen, {
    foodId: route.foodId,
    initialAmount: route.initialAmount,
    date: "2026-07-13",
    onCancel: jest.fn(),
    onSaved: jest.fn(),
  }));
}

test("Manual serving flows through Food Detail and navigator into visible submission", async () => {
  const initial = await foodDetailSelection("selected-serving");
  const renderer = await renderLog(initial);
  expect(renderer.root.findByType(TextInput).props.value).toBe("2.5");
  await act(async () => pressableWithText(renderer.root, "Save Log").props.onPress());
  expect(mockCreateLog).toHaveBeenCalledWith(expect.objectContaining({
    amount_quantity: "2.5",
    amount_unit: "serving",
    serving_definition_id: "selected-serving",
  }));
});

test("gram selection opens Log Food in gram mode with its amount identity", async () => {
  const initial = await foodDetailSelection("grams-amount");
  const renderer = await renderLog(initial);
  expect(renderer.root.findByType(TextInput).props.value).toBe("75");
  await act(async () => pressableWithText(renderer.root, "Save Log").props.onPress());
  expect(mockCreateLog).toHaveBeenCalledWith(expect.objectContaining({
    amount_quantity: "75",
    amount_unit: "g",
    serving_definition_id: "grams-amount",
  }));
});

test("managed Recipe immutable amount ID crosses the component boundary unchanged", async () => {
  const recipeFood = { ...food, source_type: "recipe", is_recipe: true };
  const revisionAmount = amount("revision-b-amount", "serving", "3", true);
  mockFoodQuery = { ...mockFoodQuery, data: recipeFood };
  mockResolvedQuery = {
    ...mockResolvedQuery,
    data: nutrition([revisionAmount], "recipe_publication_revision"),
  };
  const initial = await foodDetailSelection("revision-b-amount");
  const renderer = await renderLog(initial, recipeFood);
  await act(async () => pressableWithText(renderer.root, "Save Log").props.onPress());
  expect(mockCreateLog).toHaveBeenCalledWith(expect.objectContaining({
    serving_definition_id: "revision-b-amount",
    amount_quantity: "3",
  }));
});

test("stale Recipe selection falls back to B, warns, and submits only B", async () => {
  const recipeFood = { ...food, source_type: "recipe", is_recipe: true };
  mockResolvedQuery = {
    ...mockResolvedQuery,
    data: nutrition(
      [amount("revision-b-default", "serving", "1", true)],
      "recipe_publication_revision",
    ),
  };
  const renderer = await renderLog({
    amountDefinitionId: "revision-a-amount",
    amountQuantity: "4",
    amountUnit: "serving",
  }, recipeFood);
  expect(hasText(
    renderer.root,
    "That amount is no longer available. The current default was selected.",
  )).toBe(true);
  expect(renderer.root.findByType(TextInput).props.value).toBe("1");
  await act(async () => pressableWithText(renderer.root, "Save Log").props.onPress());
  expect(mockCreateLog).toHaveBeenCalledWith(expect.objectContaining({
    serving_definition_id: "revision-b-default",
    amount_quantity: "1",
  }));
});

test("invalid quantity preserves selection, warns once, and user changes dismiss warning", async () => {
  const renderer = await renderLog({
    amountDefinitionId: "selected-serving",
    amountQuantity: "0",
    amountUnit: "serving",
  });
  const warning = "The quantity was invalid and was reset to 1.";
  expect(hasText(renderer.root, warning)).toBe(true);
  expect(renderer.root.findAllByProps({ accessibilityLiveRegion: "polite" }).length).toBeGreaterThan(0);
  const warningText = renderer.root.findAllByType(Text).find(
    (node) => textContent(node) === warning,
  ) as ReactTestInstance;
  expect(warningText.props.accessibilityRole).toBeUndefined();
  expect(renderer.root.findByProps({
    accessibilityLabel: "Dismiss amount notice",
  }).props.accessibilityRole).toBe("button");
  await act(async () => renderer.root.findByType(TextInput).props.onChangeText("6"));
  expect(hasText(renderer.root, warning)).toBe(false);
  await act(async () => pressableWithText(renderer.root, "Save Log").props.onPress());
  expect(mockCreateLog).toHaveBeenCalledWith(expect.objectContaining({
    serving_definition_id: "selected-serving",
    amount_quantity: "6",
  }));
});

test("fallback warning can be dismissed and does not reappear", async () => {
  const initial = {
    amountDefinitionId: "missing-serving",
    amountQuantity: "2",
    amountUnit: "serving" as const,
  };
  const renderer = await renderLog(initial);
  const warning = "That amount is no longer available. The current default was selected.";
  expect(hasText(renderer.root, warning)).toBe(true);
  await act(async () => renderer.root.findByProps({
    accessibilityLabel: "Dismiss amount notice",
  }).props.onPress());
  expect(hasText(renderer.root, warning)).toBe(false);

  await act(async () => renderer.update(React.createElement(LogFoodScreen, {
    foodId: food.id,
    initialAmount: initial,
    date: "2026-07-13",
    onCancel: jest.fn(),
    onSaved: jest.fn(),
  })));
  expect(hasText(renderer.root, warning)).toBe(false);
});

test("resolved-nutrition refetch does not overwrite user changes", async () => {
  const initial = {
    amountDefinitionId: "selected-serving",
    amountQuantity: "2.5",
    amountUnit: "serving" as const,
  };
  const renderer = await renderLog(initial);
  await act(async () => renderer.root.findByType(TextInput).props.onChangeText("8"));
  mockResolvedQuery = {
    ...mockResolvedQuery,
    data: nutrition([amount("new-default", "serving", "1", true)]),
  };
  await act(async () => renderer.update(React.createElement(LogFoodScreen, {
    foodId: food.id,
    initialAmount: initial,
    date: "2026-07-13",
    onCancel: jest.fn(),
    onSaved: jest.fn(),
  })));
  expect(renderer.root.findByType(TextInput).props.value).toBe("8");
});

test("edit-log mode ignores create initialization and shows no create warning", async () => {
  const log: DailyLog = {
    id: "log-1",
    food_item_id: food.id,
    food_name_snapshot: food.name,
    source_food_available: true,
    logged_date: "2026-07-13",
    amount_quantity: "7",
    amount_unit: "serving",
    serving_definition_id: "default-serving",
  };
  const context: DailyLogEditContext = {
    log_id: log.id,
    source_food_available: true,
    is_revision_backed: false,
    recipe_publication_revision_id: null,
    selected_amount_definition_id: null,
    amount_choices: [],
  };
  mockEditContextQuery = { ...mockEditContextQuery, data: context };
  const renderer = await render(React.createElement(LogFoodScreen, {
    foodId: food.id,
    log,
    initialAmount: {
      amountDefinitionId: "missing",
      amountQuantity: "0",
      amountUnit: "g",
    },
    date: log.logged_date,
    onCancel: jest.fn(),
    onSaved: jest.fn(),
  }));
  expect(renderer.root.findByType(TextInput).props.value).toBe("7");
  expect(hasText(renderer.root, "That amount is no longer available. The current default was selected.")).toBe(false);
});

test("fresh routes isolate Foods and remounting the same Food reapplies new state", async () => {
  const first = await renderLog({
    amountDefinitionId: "selected-serving",
    amountQuantity: "2",
    amountUnit: "serving",
  });
  expect(first.root.findByType(TextInput).props.value).toBe("2");
  first.unmount();

  const foodB = { ...food, id: "food-b", name: "Food B" };
  mockFoodQuery = { ...mockFoodQuery, data: foodB };
  const second = await renderLog(undefined, foodB);
  expect(second.root.findByType(TextInput).props.value).toBe("1");
  expect(second.root.findAllByType(Text).some((node) => textContent(node).includes("no longer available"))).toBe(false);
  second.unmount();

  mockFoodQuery = { ...mockFoodQuery, data: food };
  const reopened = await renderLog({
    amountDefinitionId: "selected-serving",
    amountQuantity: "9",
    amountUnit: "serving",
  });
  expect(reopened.root.findByType(TextInput).props.value).toBe("9");
});

test("default Recipe Detail-style caller has no warning", async () => {
  const renderer = await renderLog();
  const warningTexts = renderer.root
    .findAllByType(Text)
    .map(textContent)
    .filter((value) => value.includes("current default") || value.includes("invalid"));
  expect(warningTexts).toEqual([]);
});
