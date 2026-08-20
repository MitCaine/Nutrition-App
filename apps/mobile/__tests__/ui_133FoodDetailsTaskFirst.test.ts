import React from "react";
import {
  Pressable,
  ScrollView,
  Text,
} from "react-native";
import TestRenderer, {
  act,
} from "react-test-renderer";

import type {
  Food,
  FoodResolvedNutrition,
  ResolvedFoodAmount,
} from "../src/features/foods/api/types";

const LONG_FOOD_NAME =
  "A deliberately very long Food name that must wrap naturally in scrolling content without becoming route chrome";

const mockFood: Food = {
  id: "ui-133-food",
  name: LONG_FOOD_NAME,
  brand: "Example Brand",
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

function resolvedAmount({
  id,
  label,
  quantity,
  mode,
  grams,
  isDefault,
  calories,
}: {
  id: string;
  label: string;
  quantity: string;
  mode: "serving" | "g";
  grams: string | null;
  isDefault: boolean;
  calories: string;
}): ResolvedFoodAmount {
  return {
    amount_definition_id: id,
    display_label: label,
    is_default: isDefault,
    entered_quantity: quantity,
    semantic_amount_mode: mode,
    resolved_grams: grams,
    valid_for_logging: true,
    nutrients: [
      {
        nutrient_id: "calories",
        amount: calories,
        unit: "kcal",
        data_status: "known",
        source_basis: "per_serving",
      },
    ],
  };
}

const DEFAULT_AMOUNT =
  resolvedAmount({
    id: "serving-cup",
    label: "1 cup",
    quantity: "1.000000",
    mode: "serving",
    grams: "200.000000",
    isDefault: true,
    calories: "1000.000000",
  });

const GRAM_AMOUNT =
  resolvedAmount({
    id: "serving-100g",
    label: "100 g",
    quantity: "100.000000",
    mode: "g",
    grams: "100.000000",
    isDefault: false,
    calories: "500.000000",
  });

let mockResolvedNutrition:
  FoodResolvedNutrition;

const mockDeleteFood =
  jest.fn();

const mockSetFavorite =
  jest.fn();

const mockDuplicateFood =
  jest.fn();

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
      data: mockResolvedNutrition,
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
  "@expo/vector-icons",
  () => ({
    Ionicons: "Ionicons",
  }),
);

jest.mock(
  "../src/app/theme/AppTheme",
  () => {
    const actual =
      jest.requireActual(
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

function textContent(
  node:
    TestRenderer.ReactTestInstance
    | string,
): string {
  return typeof node === "string"
    ? node
    : node.children
        .map(
          (child) =>
            textContent(
              child as
                TestRenderer.ReactTestInstance
                | string,
            ),
        )
        .join("");
}

function allText(
  root:
    TestRenderer.ReactTestInstance,
): string[] {
  return root
    .findAllByType(
      Text,
    )
    .map(
      textContent,
    );
}

function pressablesByLabel(
  root: TestRenderer.ReactTestInstance,
  accessibilityLabel: string,
): TestRenderer.ReactTestInstance[] {
  return root
    .findAllByType(
      Pressable,
    )
    .filter(
      (node) =>
        node.props.accessibilityLabel
        === accessibilityLabel,
    );
}

function pressableByLabel(
  root: TestRenderer.ReactTestInstance,
  accessibilityLabel: string,
): TestRenderer.ReactTestInstance {
  const matches =
    pressablesByLabel(
      root,
      accessibilityLabel,
    );

  if (matches.length !== 1) {
    throw new Error(
      `Expected one Pressable labelled "${accessibilityLabel}", found ${matches.length}.`,
    );
  }

  return matches[0];
}

beforeEach(() => {
  mockResolvedNutrition = {
    nutrition_authority:
      "food_item",
    recipe_id: null,
    recipe_publication_revision_id:
      null,
    amounts: [
      DEFAULT_AMOUNT,
      GRAM_AMOUNT,
    ],
  };

  mockDeleteFood.mockReset();
  mockSetFavorite.mockReset();
  mockDuplicateFood.mockReset();
});

test(
  "Food Details keeps Back, Food, Log, and Edit in one fixed route header while identity and management scroll",
  async () => {
    const onLog =
      jest.fn();

    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(
      async () => {
        renderer =
          TestRenderer.create(
            React.createElement(
              FoodDetailsScreen,
              {
                foodId:
                  mockFood.id,
                onBack:
                  jest.fn(),
                onDeleted:
                  jest.fn(),
                onEdit:
                  jest.fn(),
                onLog,
              },
            ),
          );
      },
    );

    const header =
      renderer.root.findByProps({
        testID:
          "route-screen-header",
      });

    expect(
      allText(
        header,
      ),
    ).toContain(
      "Food",
    );

    expect(
      allText(
        header,
      ),
    ).not.toContain(
      LONG_FOOD_NAME,
    );

    expect(
      pressablesByLabel(
        header,
        "Back from food details",
      ),
    ).toHaveLength(
      1,
    );

    expect(
      pressablesByLabel(
        header,
        "Log food",
      ),
    ).toHaveLength(
      1,
    );

    expect(
      pressablesByLabel(
        header,
        "Edit food",
      ),
    ).toHaveLength(
      1,
    );

    expect(
      renderer.root.findAllByProps({
        testID:
          "food-detail-task-row",
      }),
    ).toHaveLength(
      0,
    );

    const scroll =
      renderer.root.findByProps({
        testID:
          "food-detail-scroll",
      });

    expect(
      scroll.type,
    ).toBe(
      ScrollView,
    );

    expect(
      pressablesByLabel(
        scroll,
        "Log food",
      ),
    ).toHaveLength(
      0,
    );

    expect(
      pressablesByLabel(
        scroll,
        "Edit food",
      ),
    ).toHaveLength(
      0,
    );

    const name =
      scroll.findByProps({
        testID:
          "food-detail-name",
      });

    expect(
      textContent(
        name,
      ),
    ).toBe(
      LONG_FOOD_NAME,
    );

    expect(
      name.props.numberOfLines,
    ).toBeUndefined();

    expect(
      name.props.ellipsizeMode,
    ).toBeUndefined();

    const secondary =
      scroll.findByProps({
        testID:
          "food-detail-secondary-actions",
      });

    expect(
      pressablesByLabel(
        secondary,
        "Duplicate food",
      ),
    ).toHaveLength(
      1,
    );

    expect(
      pressablesByLabel(
        secondary,
        "Favorite food",
      ),
    ).toHaveLength(
      1,
    );

    expect(
      pressablesByLabel(
        secondary,
        "Delete food",
      ),
    ).toHaveLength(
      1,
    );

    expect(
      allText(
        renderer.root,
      ),
    ).toContain(
      "1,000 kcal",
    );

    const gramChoice =
      scroll.findAllByType(
        Pressable,
      ).find(
        (node) =>
          node.props
            .accessibilityRole
          === "radio"
          && node.props
            .accessibilityLabel
          === "100 g",
      );

    expect(
      gramChoice,
    ).toBeDefined();

    await act(
      async () => {
        gramChoice?.props
          .onPress();
      },
    );

    expect(
      allText(
        renderer.root,
      ),
    ).toContain(
      "500 kcal",
    );

    await act(
      async () => {
        pressableByLabel(
          renderer.root.findByProps({
            testID:
              "route-screen-header",
          }),
          "Log food",
        ).props.onPress();
      },
    );

    expect(
      onLog,
    ).toHaveBeenCalledTimes(
      1,
    );

    expect(
      onLog,
    ).toHaveBeenCalledWith({
      amountDefinitionId:
        "serving-100g",
      amountQuantity:
        "100.000000",
      amountUnit:
        "g",
    });

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);

test(
  "recipe-backed Food Details keeps Log in the header while Edit and Delete remain absent by ownership authority",
  async () => {
    mockResolvedNutrition = {
      ...mockResolvedNutrition,
      nutrition_authority:
        "recipe_publication_revision",
      recipe_id:
        "recipe-1",
      recipe_publication_revision_id:
        "revision-1",
    };

    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(
      async () => {
        renderer =
          TestRenderer.create(
            React.createElement(
              FoodDetailsScreen,
              {
                foodId:
                  mockFood.id,
                onBack:
                  jest.fn(),
                onDeleted:
                  jest.fn(),
                onEdit:
                  jest.fn(),
                onLog:
                  jest.fn(),
              },
            ),
          );
      },
    );

    const header =
      renderer.root.findByProps({
        testID:
          "route-screen-header",
      });

    expect(
      pressablesByLabel(
        header,
        "Log food",
      ),
    ).toHaveLength(
      1,
    );

    expect(
      pressablesByLabel(
        header,
        "Edit food",
      ),
    ).toHaveLength(
      0,
    );

    const secondary =
      renderer.root.findByProps({
        testID:
          "food-detail-secondary-actions",
      });

    expect(
      pressablesByLabel(
        secondary,
        "Delete food",
      ),
    ).toHaveLength(
      0,
    );

    expect(
      pressablesByLabel(
        secondary,
        "Duplicate food",
      ),
    ).toHaveLength(
      1,
    );

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);
