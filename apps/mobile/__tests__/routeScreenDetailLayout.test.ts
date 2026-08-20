import React from "react";
import TestRenderer, {
  act,
} from "react-test-renderer";

import type {
  Food,
} from "../src/features/foods/api/types";
import type {
  Recipe,
} from "../src/features/recipes/api/types";
import {
  expectFixedRouteHeader,
} from "./routeScreenHeaderTestSupport";

const mockDeleteFood = jest.fn();
const mockSetFavorite = jest.fn();
const mockDuplicateFood = jest.fn();
const mockPublishRecipe = jest.fn();
const mockDeleteRecipe = jest.fn();

const mockFood: Food = {
  id: "layout-food",
  name: "Layout Food",
  brand: null,
  notes: null,
  source_type: "manual",
  source_id: null,
  is_recipe: false,
  source_kind: "manual",
  source_label: "Manual",
  is_favorite: false,
  can_favorite: true,
  serving_definitions: [],
  nutrients: [],
};

const mockRecipe: Recipe = {
  id: "layout-recipe",
  user_id: "user-1",
  name: "Layout Recipe",
  notes: null,
  serving_count_yield: null,
  final_cooked_weight_grams: null,
  final_cooked_weight_display_quantity: null,
  final_cooked_weight_display_unit: null,
  needs_republish: false,
  created_at:
    "2026-08-17T00:00:00Z",
  updated_at:
    "2026-08-17T00:00:00Z",
  ingredients: [],
};

jest.mock(
  "../src/features/foods/hooks/useFoods",
  () => ({
    useFood: () => ({
      data: mockFood,
      isLoading: false,
      isError: false,
      error: null,
      refetch: jest.fn(),
    }),
    useFoodResolvedNutrition: () => ({
      data: {
        nutrition_authority:
          "food_item",
        recipe_id: null,
        recipe_publication_revision_id:
          null,
        amounts: [],
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: jest.fn(),
    }),
    useFoodMutations: () => ({
      deleteFood: {
        isPending: false,
        mutate: mockDeleteFood,
      },
      setFavorite: {
        isPending: false,
        mutate: mockSetFavorite,
      },
      duplicateFood: {
        isPending: false,
        mutate: mockDuplicateFood,
      },
    }),
  }),
);

jest.mock(
  "../src/features/recipes/hooks/useRecipes",
  () => ({
    useRecipeNutrition: () => ({
      data: {
        totals: [],
        perServing: null,
        per100g: null,
      },
      isError: false,
      error: null,
      refetch: jest.fn(),
    }),
    useRecipeMutations: () => ({
      publishRecipe: {
        isPending: false,
        isError: false,
        error: null,
        mutateAsync:
          mockPublishRecipe,
      },
      deleteRecipe: {
        isPending: false,
        mutateAsync:
          mockDeleteRecipe,
      },
    }),
  }),
);

jest.mock(
  "@expo/vector-icons",
  () => ({
    Ionicons: "Ionicons",
  }),
);

jest.mock(
  "../src/app/theme/AppTheme",
  () => {
    const actual = jest.requireActual(
      "../src/app/theme/AppTheme",
    );

    return {
      ...actual,
      useAppTheme: () => ({
        ...actual.LIGHT_THEME,
        preference: "system",
        effectiveScheme: "light",
        setPreference: jest.fn(),
      }),
    };
  },
);

import {
  FoodDetailsScreen,
} from "../src/features/foods/screens/FoodDetailsScreen";
import {
  RecipeDetailScreen,
} from "../src/features/recipes/screens/RecipeDetailScreen";

test("#108 Food Detail keeps Back and its route title outside detail scrolling", async () => {
  const onBack = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      React.createElement(
        FoodDetailsScreen,
        {
          foodId: mockFood.id,
          onBack,
          onDeleted: jest.fn(),
          onEdit: jest.fn(),
          onLog: jest.fn(),
        },
      ),
    );
  });

  const header = expectFixedRouteHeader(
    renderer.root,
    "Food",
  );

  expect(
    header.findByProps({
      accessibilityLabel:
        "Back from food details",
    }),
  ).toBeDefined();

  await act(async () =>
    renderer.unmount(),
  );
});

test("#108 Recipe Detail keeps Back, Edit, and its route title outside detail scrolling", async () => {
  const onBack = jest.fn();
  const onEdit = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(
      React.createElement(
        RecipeDetailScreen,
        {
          recipe: mockRecipe,
          onBack,
          onEdit,
          onOpenFood: jest.fn(),
          onLogFood: jest.fn(),
          onDeleted: jest.fn(),
        },
      ),
    );
  });

  const header = expectFixedRouteHeader(
    renderer.root,
    "Layout Recipe",
  );

  expect(
    header.findByProps({
      accessibilityLabel:
        "Back from Recipe details",
    }),
  ).toBeDefined();

  expect(
    header.findByProps({
      accessibilityLabel:
        "Edit Recipe",
    }),
  ).toBeDefined();

  await act(async () =>
    renderer.unmount(),
  );
});
