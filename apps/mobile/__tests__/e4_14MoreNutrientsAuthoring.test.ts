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
  extendedFoodAuthoringNutrients,
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

function pressableByLabel(
  root:
    TestRenderer.ReactTestInstance,
  label: string,
): TestRenderer.ReactTestInstance {
  const matches =
    root
      .findAllByType(
        Pressable,
      )
      .filter(
        (node) =>
          node.props
            .accessibilityLabel
          === label,
      );

  if (matches.length !== 1) {
    throw new Error(
      `Expected one Pressable labelled "${label}", found ${matches.length}.`,
    );
  }

  return matches[0];
}

function nutrientInput(
  root:
    TestRenderer.ReactTestInstance,
  label: string,
): TestRenderer.ReactTestInstance {
  return root.findByProps({
    accessibilityLabel:
      `${label} amount`,
  });
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
        node.props
          .accessibilityLabel,
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

function nutrient(
  nutrientId: string,
  amount: string,
  dataStatus:
    FoodNutrient["data_status"],
): FoodNutrient {
  const definition =
    NUTRIENT_CATALOG_BY_ID.get(
      nutrientId,
    );

  if (!definition) {
    throw new Error(
      `Missing canonical fixture ${nutrientId}`,
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
      dataStatus,
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

function editFoodFixture(): Food {
  return {
    id:
      "food-e4-14",
    name:
      "Extended nutrient fixture",
    brand:
      null,
    notes:
      null,
    source_type:
      "manual",
    source_id:
      null,
    is_recipe:
      false,
    source_kind:
      "manual",
    source_label:
      "Manual",
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
      nutrient(
        "magnesium",
        "12.345678",
        "known",
      ),
      nutrient(
        "vitamin_a",
        "900.123456",
        "estimated",
      ),
      nutrient(
        "total_omega_3",
        "0",
        "zero",
      ),
    ],
  };
}

async function renderForm(
  food?: Food,
): Promise<TestRenderer.ReactTestRenderer> {
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

  return renderer;
}

async function openMoreNutrients(
  renderer:
    TestRenderer.ReactTestRenderer,
) {
  await act(
    async () => {
      pressableByLabel(
        renderer.root,
        "More nutrients",
      ).props.onPress();
    },
  );
}

async function selectNutrient(
  renderer:
    TestRenderer.ReactTestRenderer,
  displayName: string,
) {
  await act(
    async () => {
      pressableByLabel(
        renderer.root,
        `Add ${displayName}`,
      ).props.onPress();
    },
  );
}

async function setFoodName(
  renderer:
    TestRenderer.ReactTestRenderer,
) {
  await act(
    async () => {
      renderer.root
        .findByProps({
          accessibilityLabel:
            "Food name",
        })
        .props.onChangeText(
          "E4-14 test food",
        );
    },
  );
}

async function saveFood(
  renderer:
    TestRenderer.ReactTestRenderer,
) {
  await act(
    async () => {
      pressableByLabel(
        renderer.root,
        "Save food",
      ).props.onPress();
    },
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
  "authoring helpers deterministically partition conventional and extended canonical nutrients",
  () => {
    const reversed =
      [...mockNutrients]
        .reverse();

    const conventional =
      conventionalNutritionFactsNutrients(
        reversed,
      );

    const extended =
      extendedFoodAuthoringNutrients(
        reversed,
      );

    expect(
      conventional.map(
        (item) => item.id,
      ),
    ).toEqual(
      CONVENTIONAL_NUTRITION_FACTS_NUTRIENT_IDS,
    );

    const conventionalIds =
      new Set(
        conventional.map(
          (item) => item.id,
        ),
      );

    expect(
      extended.every(
        (item) =>
          !conventionalIds.has(
            item.id,
          ),
      ),
    ).toBe(
      true,
    );

    const combinedIds = [
      ...conventional.map(
        (item) => item.id,
      ),
      ...extended.map(
        (item) => item.id,
      ),
    ];

    expect(
      new Set(
        combinedIds,
      ).size,
    ).toBe(
      mockNutrients.length,
    );

    expect(
      [...combinedIds]
        .sort(),
    ).toEqual(
      mockNutrients
        .map(
          (item) => item.id,
        )
        .sort(),
    );
  },
);

test(
  "New Food starts with fifteen fields and grouped collapsed More nutrients without duplicate conventional candidates",
  async () => {
    const renderer =
      await renderForm();

    expect(
      nutrientAmountLabels(
        renderer,
      ),
    ).toHaveLength(
      15,
    );

    const more =
      pressableByLabel(
        renderer.root,
        "More nutrients",
      );

    expect(
      more.props
        .accessibilityState,
    ).toMatchObject({
      expanded:
        false,
    });

    expect(
      renderer.root.findAllByProps({
        testID:
          "more-nutrients-picker",
      }),
    ).toHaveLength(
      0,
    );

    await openMoreNutrients(
      renderer,
    );

    const picker =
      renderer.root.findByProps({
        testID:
          "more-nutrients-picker",
      });

    const text =
      picker
        .findAllByType(
          Text,
        )
        .map(
          textContent,
        );

    const vitamins =
      text.indexOf(
        "Vitamins",
      );

    const minerals =
      text.indexOf(
        "Minerals",
      );

    const fattyAcids =
      text.indexOf(
        "Fatty Acids",
      );

    const other =
      text.indexOf(
        "Other",
      );

    expect(
      vitamins,
    ).toBeGreaterThanOrEqual(
      0,
    );

    expect(
      minerals,
    ).toBeGreaterThan(
      vitamins,
    );

    expect(
      fattyAcids,
    ).toBeGreaterThan(
      minerals,
    );

    expect(
      other,
    ).toBeGreaterThan(
      fattyAcids,
    );

    expect(
      picker.findAllByProps({
        accessibilityLabel:
          "Add Vitamin D",
      }),
    ).toHaveLength(
      0,
    );

    expect(
      picker.findAllByProps({
        accessibilityLabel:
          "Add Calcium",
      }),
    ).toHaveLength(
      0,
    );

    expect(
      picker.findByProps({
        accessibilityLabel:
          "Add Vitamin A",
      }),
    ).toBeDefined();

    expect(
      picker.findByProps({
        accessibilityLabel:
          "Add Magnesium",
      }),
    ).toBeDefined();

    expect(
      picker.findByProps({
        accessibilityLabel:
          "Add Omega-3",
      }),
    ).toBeDefined();

    expect(
      picker.findByProps({
        accessibilityLabel:
          "Add Choline",
      }),
    ).toBeDefined();

    const optionLabels =
      picker
        .findAllByType(
          Pressable,
        )
        .map(
          (node) =>
            node.props
              .accessibilityLabel,
        )
        .filter(
          (
            label,
          ): label is string =>
            typeof label === "string"
            && label.startsWith(
              "Add ",
            ),
        );

    expect(
      new Set(
        optionLabels,
      ).size,
    ).toBe(
      optionLabels.length,
    );

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);

test(
  "Cancel, add, omit, and reopen preserve one unknown extended presentation selection without duplicates",
  async () => {
    const renderer =
      await renderForm();

    await openMoreNutrients(
      renderer,
    );

    await act(
      async () => {
        pressableByLabel(
          renderer.root,
          "Cancel more nutrients",
        ).props.onPress();
      },
    );

    expect(
      renderer.root.findAllByProps({
        testID:
          "more-nutrients-picker",
      }),
    ).toHaveLength(
      0,
    );

    expect(
      renderer.root.findAllByProps({
        accessibilityLabel:
          "Vitamin A amount",
      }),
    ).toHaveLength(
      0,
    );

    await openMoreNutrients(
      renderer,
    );

    expect(
      renderer.root.findByProps({
        accessibilityLabel:
          "Add Vitamin A",
      }),
    ).toBeDefined();

    await selectNutrient(
      renderer,
      "Vitamin A",
    );

    expect(
      renderer.root.findAllByProps({
        testID:
          "more-nutrients-picker",
      }),
    ).toHaveLength(
      0,
    );

    expect(
      nutrientInput(
        renderer.root,
        "Vitamin A",
      ).props.value,
    ).toBe(
      "",
    );

    await openMoreNutrients(
      renderer,
    );

    expect(
      renderer.root.findAllByProps({
        accessibilityLabel:
          "Add Vitamin A",
      }),
    ).toHaveLength(
      0,
    );

    await act(
      async () => {
        pressableByLabel(
          renderer.root,
          "Cancel more nutrients",
        ).props.onPress();
      },
    );

    expect(
      nutrientInput(
        renderer.root,
        "Vitamin A",
      ),
    ).toBeDefined();

    await act(
      async () => {
        pressableByLabel(
          renderer.root,
          "Omit Vitamin A",
        ).props.onPress();
      },
    );

    expect(
      renderer.root.findAllByProps({
        accessibilityLabel:
          "Vitamin A amount",
      }),
    ).toHaveLength(
      0,
    );

    await openMoreNutrients(
      renderer,
    );

    expect(
      renderer.root.findByProps({
        accessibilityLabel:
          "Add Vitamin A",
      }),
    ).toBeDefined();

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);

test(
  "newly selected blank extended nutrient remains authoritative unknown on create",
  async () => {
    const renderer =
      await renderForm();

    await openMoreNutrients(
      renderer,
    );

    await selectNutrient(
      renderer,
      "Vitamin A",
    );

    expect(
      nutrientInput(
        renderer.root,
        "Vitamin A",
      ).props.value,
    ).toBe(
      "",
    );

    await setFoodName(
      renderer,
    );

    await saveFood(
      renderer,
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
            "vitamin_a",
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
  "added extended nutrients retain existing explicit-zero and numeric-known entry semantics",
  async () => {
    const renderer =
      await renderForm();

    await openMoreNutrients(
      renderer,
    );

    await selectNutrient(
      renderer,
      "Vitamin A",
    );

    await act(
      async () => {
        nutrientInput(
          renderer.root,
          "Vitamin A",
        ).props.onChangeText(
          "0",
        );
      },
    );

    await openMoreNutrients(
      renderer,
    );

    await selectNutrient(
      renderer,
      "Magnesium",
    );

    await act(
      async () => {
        nutrientInput(
          renderer.root,
          "Magnesium",
        ).props.onChangeText(
          "12.5",
        );
      },
    );

    await setFoodName(
      renderer,
    );

    await saveFood(
      renderer,
    );

    const payload =
      mockCreateFood.mock
        .calls[0][0];

    expect(
      payload.nutrients,
    ).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          nutrient_id:
            "vitamin_a",
          amount:
            "0",
          data_status:
            "zero",
        }),
        expect.objectContaining({
          nutrient_id:
            "magnesium",
          amount:
            "12.5",
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

test(
  "Edit Food uses the same discovery model while populated known estimated and zero extended nutrients stay visible and preserve exact semantics",
  async () => {
    const food =
      editFoodFixture();

    const renderer =
      await renderForm(
        food,
      );

    expect(
      nutrientAmountLabels(
        renderer,
      ).length,
    ).toBe(
      18,
    );

    expect(
      nutrientInput(
        renderer.root,
        "Magnesium",
      ).props.value,
    ).toBe(
      "12.35",
    );

    expect(
      nutrientInput(
        renderer.root,
        "Vitamin A",
      ),
    ).toBeDefined();

    expect(
      nutrientInput(
        renderer.root,
        "Omega-3",
      ).props.value,
    ).toBe(
      "0",
    );

    const more =
      pressableByLabel(
        renderer.root,
        "More nutrients",
      );

    expect(
      more.props
        .accessibilityState,
    ).toMatchObject({
      expanded:
        false,
    });

    await openMoreNutrients(
      renderer,
    );

    expect(
      renderer.root.findAllByProps({
        accessibilityLabel:
          "Add Magnesium",
      }),
    ).toHaveLength(
      0,
    );

    expect(
      renderer.root.findAllByProps({
        accessibilityLabel:
          "Add Vitamin A",
      }),
    ).toHaveLength(
      0,
    );

    expect(
      renderer.root.findAllByProps({
        accessibilityLabel:
          "Add Omega-3",
      }),
    ).toHaveLength(
      0,
    );

    expect(
      renderer.root.findByProps({
        accessibilityLabel:
          "Add Choline",
      }),
    ).toBeDefined();

    await act(
      async () => {
        pressableByLabel(
          renderer.root,
          "Cancel more nutrients",
        ).props.onPress();
      },
    );

    await saveFood(
      renderer,
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
        expect.objectContaining({
          nutrient_id:
            "vitamin_a",
          amount:
            "900.123456",
          basis:
            "per_serving",
          data_status:
            "estimated",
        }),
        expect.objectContaining({
          nutrient_id:
            "total_omega_3",
          amount:
            "0",
          unit:
            "mg",
          basis:
            "per_serving",
          data_status:
            "zero",
        }),
      ]),
    );

    await act(
      async () =>
        renderer.unmount(),
    );
  },
);
