import React from "react";
import { Pressable } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type { RecentFood } from "../src/features/foods/api/types";
import type { Recipe } from "../src/features/recipes/api/types";

let mockRecipesQuery: {
  data: Recipe[] | undefined;
  isLoading: boolean;
  isError: boolean;
  refetch: jest.Mock;
};

let mockRecentQuery: {
  data: RecentFood[] | undefined;
  isLoading: boolean;
  isError: boolean;
  refetch: jest.Mock;
};

jest.mock("../src/features/recipes/hooks/useRecipes", () => ({
  useRecipes: () => mockRecipesQuery,
}));

jest.mock("../src/features/foods/hooks/useFoods", () => ({
  useRecentFoods: () => mockRecentQuery,
}));

jest.mock("../src/shared/components/RootScreenHeader", () => ({
  RootScreenHeader: () => null,
}));

jest.mock("../src/shared/components/TransientSuccessBanner", () => ({
  TransientSuccessBanner: () => null,
}));

jest.mock("../src/app/theme/AppTheme", () => {
  const actual = jest.requireActual("../src/app/theme/AppTheme");
  return {
    ...actual,
    useAppTheme: () => ({
      ...actual.LIGHT_THEME,
      preference: "system",
      effectiveScheme: "light",
      setPreference: jest.fn(),
    }),
  };
});

import {
  RecipeListScreen,
  recentRecipeRows,
  recipePublicationStatus,
} from "../src/features/recipes/screens/RecipeListScreen";

function recipe(overrides: Partial<Recipe> = {}): Recipe {
  return {
    id: "recipe-default",
    user_id: "user-1",
    published_food_item_id: null,
    name: "Recipe",
    notes: null,
    serving_count_yield: null,
    final_cooked_weight_grams: null,
    final_cooked_weight_display_quantity: null,
    final_cooked_weight_display_unit: null,
    needs_republish: false,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ingredients: [],
    ...overrides,
  };
}

function recentFood(
  id: string,
  lastUsedAt: string,
  overrides: Partial<RecentFood["food"]> = {},
): RecentFood {
  return {
    food: {
      id,
      name: `Food ${id}`,
      brand: null,
      notes: null,
      source_type: "recipe",
      source_id: "deliberately-not-used-for-recipe-mapping",
      is_recipe: true,
      source_kind: "recipe",
      source_label: "Recipe",
      is_favorite: false,
      can_favorite: false,
      serving_definitions: [],
      nutrients: [],
      ...overrides,
    },
    last_used_at: lastUsedAt,
  };
}

beforeEach(() => {
  mockRecipesQuery = {
    data: [],
    isLoading: false,
    isError: false,
    refetch: jest.fn(),
  };
  mockRecentQuery = {
    data: [],
    isLoading: false,
    isError: false,
    refetch: jest.fn(),
  };
});

test("publication status distinguishes Draft, Published/current, and Update Needed Recipes", () => {
  expect(recipePublicationStatus(recipe())).toBe("Draft");
  expect(recipePublicationStatus(recipe({
    published_food_item_id: "food-current",
    needs_republish: false,
  }))).toBe("Published/current");
  expect(recipePublicationStatus(recipe({
    published_food_item_id: "food-stale",
    needs_republish: true,
  }))).toBe("Update Needed");
});

test("recent Recipe discovery preserves canonical Food order, de-duplicates, and maps by published Food identity", () => {
  const current = recipe({
    id: "recipe-current",
    name: "Current Recipe",
    published_food_item_id: "food-current",
  });
  const stale = recipe({
    id: "recipe-stale",
    name: "Stale Recipe",
    published_food_item_id: "food-stale",
    needs_republish: true,
  });

  const recents: RecentFood[] = [
    recentFood("food-stale", "2026-08-21T10:00:00Z"),
    recentFood("unmapped-recipe-food", "2026-08-21T09:30:00Z"),
    recentFood("food-current", "2026-08-21T09:00:00Z"),
    recentFood("food-stale", "2026-08-21T08:00:00Z"),
    recentFood("ordinary-food", "2026-08-21T07:00:00Z", {
      source_type: "manual",
      source_id: null,
      is_recipe: false,
      source_kind: "manual",
      source_label: "Manual",
      can_favorite: true,
    }),
  ];

  expect(
    recentRecipeRows([current, stale], recents, "").map(({ recipe: value }) => value.id),
  ).toEqual(["recipe-stale", "recipe-current"]);

  expect(recentRecipeRows([current, stale], recents, "stale")).toEqual([]);
});

test("Recipe list renders lifecycle state and recent discovery routes through existing Recipe navigation", async () => {
  const neverPublished = recipe({
    id: "recipe-never",
    name: "Never Recipe",
  });
  const current = recipe({
    id: "recipe-current",
    name: "Current Recipe",
    published_food_item_id: "food-current",
  });
  const stale = recipe({
    id: "recipe-stale",
    name: "Stale Recipe",
    published_food_item_id: "food-stale",
    needs_republish: true,
  });

  mockRecipesQuery.data = [neverPublished, current, stale];
  mockRecentQuery.data = [
    recentFood("food-stale", "2026-08-21T10:00:00Z"),
    recentFood("food-current", "2026-08-21T09:00:00Z"),
    recentFood("food-stale", "2026-08-21T08:00:00Z"),
  ];

  const onOpenRecipe = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      React.createElement(RecipeListScreen, {
        query: "",
        setQuery: jest.fn(),
        onCreate: jest.fn(),
        onOpenRecipe,
        initialScrollOffset: 0,
        onScrollSessionChange: jest.fn(),
        onOpenSettings: jest.fn(),
      }),
    );
  });

  expect(renderer.root.findByProps({ testID: "recent-recipes" })).toBeDefined();

  const mainLabels = renderer.root.findAllByType(Pressable)
    .map((node) => node.props.accessibilityLabel)
    .filter((label): label is string => typeof label === "string");

  expect(mainLabels).toContain("Never Recipe, 0 ingredients, Draft");
  expect(mainLabels).toContain("Current Recipe, 0 ingredients, Published/current");
  expect(mainLabels).toContain("Stale Recipe, 0 ingredients, Update Needed");

  const recentButtons = renderer.root.findAllByType(Pressable).filter(
    (node) => typeof node.props.accessibilityLabel === "string"
      && node.props.accessibilityLabel.includes(", recent Recipe,"),
  );

  expect(
    recentButtons.map(
      (node) => String(node.props.accessibilityLabel).split(", recent Recipe,")[0],
    ),
  ).toEqual(["Stale Recipe", "Current Recipe"]);

  await act(async () => {
    recentButtons[0].props.onPress();
  });

  expect(onOpenRecipe).toHaveBeenCalledWith("recipe-stale");
  expect(onOpenRecipe).toHaveBeenCalledTimes(1);

  await act(async () => {
    renderer.unmount();
  });
});
