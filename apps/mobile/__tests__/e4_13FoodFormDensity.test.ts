import React from "react";
import {
  Pressable,
  Text,
  TextInput,
} from "react-native";
import TestRenderer, {
  act,
} from "react-test-renderer";

import type {
  Food,
  FoodNutrient,
  NutrientDefinition,
} from "../src/features/foods/api/types";
import {
  CONVENTIONAL_NUTRITION_FACTS_NUTRIENT_IDS,
  conventionalNutritionFactsNutrients,
} from "../src/features/foods/utils/foodAuthoringNutrients";
import {
  NUTRIENT_CATALOG,
  NUTRIENT_CATALOG_BY_ID,
} from "../src/shared/nutrition/catalog";

let mockNutrients:
  NutrientDefinition[] = [];

const mockCreateFood =
  jest.fn();

const mockUpdateFood =
  jest.fn();

jest.mock(
  "../src/features/foods/hooks/useFoods",
  () => ({
    useNutrients:
      () => ({
        data:
          mockNutrients,
        isLoading:
          false,
        isError:
          false,
        refetch:
          jest.fn(),
      }),
    useFoodMutations:
      () => ({
        createFood: {
          isPending:
            false,
          mutateAsync:
            mockCreateFood,
        },
        updateFood: {
          isPending:
            false,
          mutateAsync:
            mockUpdateFood,
        },
      }),
  }),
);

import {
  FoodFormScreen,
} from "../src/features/foods/screens/FoodFormScreen";

const EXPECTED_IDS = [
  "calories",
  "total_fat",
  "saturated_fat",
  "trans_fat",
  "cholesterol",
  "sodium",
  "total_carbohydrate",
  "dietary_fiber",
  "total_sugars",
  "added_sugars",
  "protein",
  "vitamin_d",
  "calcium",
  "iron",
  "potassium",
];

const EXPECTED_LABELS = [
  "Calories",
  "Total Fat",
  "Saturated Fat",
  "Trans Fat",
  "Cholesterol",
  "Sodium",
  "Total Carbohydrate",
  "Dietary Fiber",
  "Total Sugars",
  "Added Sugars",
  "Protein",
  "Vitamin D",
  "Calcium",
  "Iron",
  "Potassium",
];

function nutrientDefinitions():
  NutrientDefinition[] {
  return NUTRIENT_CATALOG.map(
    (nutrient) => ({
      ...nutrient,
      dri_reference_kinds:
        [...nutrient.dri_reference_kinds],
    }),
  );
}

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

function populatedNutrient(
  nutrientId: string,
  amount = "12.345678",
): FoodNutrient {
  const definition =
    NUTRIENT_CATALOG_BY_ID.get(
      nutrientId,
    );

  if (!definition) {
    throw new Error(
      `Missing nutrient fixture: ${nutrientId}`,
    );
  }

  return {
    id:
      `food-nutrient-${nutrientId}`,
    nutrient_id:
      nutrientId,
    amount,
    unit:
      definition.default_unit,
    basis:
      "per_serving",
    data_status:
      "known",
    source:
      "manual",
    is_user_confirmed:
      true,
    original_amount:
      null,
    original_unit:
      null,
    original_text:
      null,
  };
}

function foodFixture(
  sourceKind:
    Food["source_kind"],
  nutrientId = "magnesium",
): Food {
  return {
    id:
      `food-${sourceKind}`,
    name:
      "Density fixture",
    brand:
      null,
    notes:
      null,
    source_type:
      sourceKind,
    source_id:
      sourceKind === "manual"
        ? null
        : `${sourceKind}-source`,
    is_recipe:
      false,
    source_kind:
      sourceKind,
    source_label:
      sourceKind === "manual"
        ? "Manual"
        : sourceKind === "usda"
          ? "USDA"
          : "Nutrition label",
    is_favorite:
      false,
    can_favorite:
      true,
    serving_definitions: [
      {
        id:
          "base",
        label:
          "100 g",
        quantity:
          "100",
        unit:
          "g",
        gram_weight:
          "100",
        is_default:
          true,
        source:
          "manual",
        is_user_confirmed:
          true,
      },
    ],
    nutrients: [
      populatedNutrient(
        nutrientId,
      ),
    ],
  };
}

function nutrientAmountLabels(
  renderer:
    TestRenderer.ReactTestRenderer,
): string[] {
  return renderer.root
    .findAllByType(
      TextInput,
    )
    .map(
      (node) =>
        node.props.accessibilityLabel,
    )
    .filter(
      (
        label,
      ): label is string =>
        typeof label === "string"
        && label.endsWith(
          " amount",
        ),
    );
}

beforeEach(() => {
  mockNutrients =
    nutrientDefinitions();

  mockCreateFood
    .mockReset()
    .mockResolvedValue({
      id:
        "created-food",
    });

  mockUpdateFood
    .mockReset()
    .mockImplementation(
      async ({
        foodId,
      }: {
        foodId: string;
      }) => ({
        id:
          foodId,
      }),
    );
});

test(
  "conventional New Food helper uses stable canonical IDs and accepted order independent of source order",
  () => {
    expect(
      CONVENTIONAL_NUTRITION_FACTS_NUTRIENT_IDS,
    ).toEqual(
      EXPECTED_IDS,
    );

    const shuffled =
      [
        ...nutrientDefinitions(),
      ].reverse();

    expect(
      conventionalNutritionFactsNutrients(
        shuffled,
      ).map(
        (nutrient) =>
          nutrient.id,
      ),
    ).toEqual(
      EXPECTED_IDS,
    );

    expect(
      conventionalNutritionFactsNutrients(
        shuffled,
      ).map(
        (nutrient) =>
          nutrient.display_name,
      ),
    ).toEqual(
      EXPECTED_LABELS,
    );
  },
);

test(
  "New Food renders exactly the fifteen conventional fields after serving information",
  async () => {
    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(
      async () => {
        renderer =
          TestRenderer.create(
            React.createElement(
              FoodFormScreen,
              {
                onCancel:
                  jest.fn(),
                onSaved:
                  jest.fn(),
              },
            ),
          );
      },
    );

    expect(
      nutrientAmountLabels(
        renderer,
      ),
    ).toEqual(
      EXPECTED_LABELS.map(
        (label) =>
          `${label} amount`,
      ),
    );

    expect(
      renderer.root.findAllByProps({
        accessibilityLabel:
          "Magnesium amount",
      }),
    ).toHaveLength(
      0,
    );

    const visibleText =
      renderer.root
        .findAllByType(
          Text,
        )
        .map(
          textContent,
        );

    expect(
      visibleText.indexOf(
        "Serving sizes",
      ),
    ).toBeGreaterThanOrEqual(
      0,
    );

    expect(
      visibleText.indexOf(
        "Serving sizes",
      ),
    ).toBeLessThan(
      visibleText.indexOf(
        "Nutrients",
      ),
    );

    expect(
      visibleText.join(
        " ",
      ),
    ).not.toContain(
      "More nutrients",
    );

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);

test(
  "hidden extended New Food nutrients remain unknown in the full create payload while explicit zero remains zero",
  async () => {
    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(
      async () => {
        renderer =
          TestRenderer.create(
            React.createElement(
              FoodFormScreen,
              {
                onCancel:
                  jest.fn(),
                onSaved:
                  jest.fn(),
              },
            ),
          );
      },
    );

    await act(
      async () =>
        renderer.root
          .findByProps({
            accessibilityLabel:
              "Food name",
          })
          .props.onChangeText(
            "Test Food",
          ),
    );

    await act(
      async () =>
        renderer.root
          .findByProps({
            accessibilityLabel:
              "Calories amount",
          })
          .props.onChangeText(
            "0",
          ),
    );

    await act(
      async () =>
        renderer.root
          .findAllByType(
            Pressable,
          )
          .find(
            (node) =>
              node.props
                .accessibilityLabel
              === "Save food",
          )
          ?.props.onPress(),
    );

    expect(
      mockCreateFood,
    ).toHaveBeenCalledTimes(
      1,
    );

    const payload =
      mockCreateFood.mock
        .calls[0][0];

    expect(
      payload.nutrients,
    ).toHaveLength(
      mockNutrients.length,
    );

    expect(
      payload.nutrients,
    ).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          nutrient_id:
            "calories",
          amount:
            "0",
          data_status:
            "zero",
        }),
        expect.objectContaining({
          nutrient_id:
            "magnesium",
          amount:
            null,
          data_status:
            "unknown",
        }),
      ]),
    );

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);

test(
  "Edit Food keeps a populated extended nutrient visible and preserves exact stored semantics on save",
  async () => {
    const food =
      foodFixture(
        "manual",
      );

    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(
      async () => {
        renderer =
          TestRenderer.create(
            React.createElement(
              FoodFormScreen,
              {
                food,
                onCancel:
                  jest.fn(),
                onSaved:
                  jest.fn(),
              },
            ),
          );
      },
    );

    expect(
      renderer.root.findByProps({
        accessibilityLabel:
          "Magnesium amount",
      }).props.value,
    ).toBe(
      "12.35",
    );

    await act(
      async () =>
        renderer.root
          .findByProps({
            accessibilityLabel:
              "Save food",
          })
          .props.onPress(),
    );

    expect(
      mockUpdateFood,
    ).toHaveBeenCalledTimes(
      1,
    );

    const call =
      mockUpdateFood.mock
        .calls[0][0];

    expect(
      call.foodId,
    ).toBe(
      food.id,
    );

    expect(
      call.input.nutrients,
    ).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          nutrient_id:
            "magnesium",
          amount:
            "12.345678",
          unit:
            "mg",
          basis:
            "per_serving",
          data_status:
            "known",
        }),
      ]),
    );

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);

test.each([
  "ocr_confirmed",
  "usda",
] as const)(
  "%s Food edit keeps populated extended nutrition visible and unchanged",
  async (
    sourceKind,
  ) => {
    const food =
      foodFixture(
        sourceKind,
      );

    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(
      async () => {
        renderer =
          TestRenderer.create(
            React.createElement(
              FoodFormScreen,
              {
                food,
                onCancel:
                  jest.fn(),
                onSaved:
                  jest.fn(),
              },
            ),
          );
      },
    );

    expect(
      renderer.root.findByProps({
        accessibilityLabel:
          "Magnesium amount",
      }),
    ).toBeDefined();

    await act(
      async () =>
        renderer.root
          .findByProps({
            accessibilityLabel:
              "Save food",
          })
          .props.onPress(),
    );

    const call =
      mockUpdateFood.mock
        .calls[0][0];

    expect(
      call.foodId,
    ).toBe(
      food.id,
    );

    expect(
      call.input.nutrients,
    ).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          nutrient_id:
            "magnesium",
          amount:
            "12.345678",
          unit:
            "mg",
          basis:
            "per_serving",
          data_status:
            "known",
        }),
      ]),
    );

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);
