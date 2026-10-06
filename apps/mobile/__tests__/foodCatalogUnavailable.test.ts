import * as Crypto from "expo-crypto";
import React from "react";
import { Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import type {
  Food,
  FoodCreateInput,
  FoodMutationInput,
  NutrientDefinition,
} from "../src/features/foods/api/types";
import {
  createLocalFoodsRuntime,
  ensureLocalNutrientCatalog,
} from "../src/runtime/local";
import {
  LocalSQLiteTestDatabase,
  seedLocalOwner,
} from "./localSQLiteTestSupport";

type NutrientQueryState = {
  data?: NutrientDefinition[];
  isLoading: boolean;
  isError: boolean;
  refetch: jest.Mock;
};

let mockNutrientQuery: NutrientQueryState;
const mockCreateFood = jest.fn();
const mockUpdateFood = jest.fn();
const activeRenderers = new Set<TestRenderer.ReactTestRenderer>();
const openDatabases = new Set<LocalSQLiteTestDatabase>();

jest.mock("../src/features/foods/hooks/useFoods", () => ({
  useNutrients: () => mockNutrientQuery,
  useFoodMutations: () => ({
    createFood: { mutateAsync: mockCreateFood, isPending: false },
    updateFood: { mutateAsync: mockUpdateFood, isPending: false },
  }),
}));

import { FoodFormScreen } from "../src/features/foods/screens/FoodFormScreen";

const OWNER = "00000000-0000-4000-8000-000000000001";
const OTHER_OWNER = "00000000-0000-4000-8000-000000000002";

function definition(
  id: string,
  displayName: string,
  defaultUnit: "kcal" | "g" | "mg",
  displayOrder: number,
): NutrientDefinition {
  return {
    id,
    display_name: displayName,
    default_unit: defaultUnit,
    nutrient_kind: id === "calories" ? "energy" : "macro",
    parent_nutrient_id: null,
    display_order: displayOrder,
    fda_daily_value: null,
    dri_reference_kinds: [],
  };
}

const loadedDefinitions: NutrientDefinition[] = [
  definition("calories", "Calories", "kcal", 1),
  definition("protein", "Protein", "g", 2),
  definition("calcium", "Calcium", "mg", 3),
  definition("sodium", "Sodium", "mg", 4),
];

const persistedFoodInput: FoodCreateInput = {
  name: "Oats",
  brand: "Pantry Co",
  notes: "plain",
  serving_definitions: [
    { label: "100 g", quantity: "100", unit: "g", gram_weight: "100", is_default: false },
    { label: "1 scoop", quantity: "1", unit: "scoop", gram_weight: "30", is_default: true },
  ],
  nutrients: [
    { nutrient_id: "calories", amount: "123.456789", unit: "kcal", basis: "per_serving", data_status: "known" },
    { nutrient_id: "protein", amount: "28.349523", unit: "g", basis: "per_100g", data_status: "estimated" },
    { nutrient_id: "calcium", amount: "0", unit: "mg", basis: "per_serving", data_status: "zero" },
    { nutrient_id: "sodium", amount: "9.125001", unit: "mg", basis: "per_serving", data_status: "known" },
    { nutrient_id: "chloride", amount: "12.375001", unit: "mg", basis: "per_serving", data_status: "known" },
    { nutrient_id: "vitamin_d", amount: null, unit: "mcg", basis: "per_serving", data_status: "unknown" },
  ],
};

const sameBasisPersistedFoodInput: FoodCreateInput = {
  ...persistedFoodInput,
  nutrients: [
    ...persistedFoodInput.nutrients.filter((nutrient) => nutrient.nutrient_id !== "protein"),
    { nutrient_id: "protein", amount: "1.234567", unit: "g", basis: "per_serving", data_status: "known" },
    { nutrient_id: "protein", amount: "1.234568", unit: "g", basis: "per_100g", data_status: "known" },
  ],
};

function noCatalogState(kind: "loading" | "error"): NutrientQueryState {
  return {
    data: undefined,
    isLoading: kind === "loading",
    isError: kind === "error",
    refetch: jest.fn(),
  };
}

function loadedCatalogState(): NutrientQueryState {
  return {
    data: loadedDefinitions,
    isLoading: false,
    isError: false,
    refetch: jest.fn(),
  };
}

function textContent(node: TestRenderer.ReactTestInstance | string): string {
  return typeof node === "string"
    ? node
    : node.children.map((child) => textContent(child as TestRenderer.ReactTestInstance | string)).join("");
}

function nutrientTuples(food: Pick<Food, "nutrients"> | FoodMutationInput) {
  return food.nutrients
    .map(({ nutrient_id, amount, unit, basis, data_status }) => ({
      nutrient_id,
      amount: amount ?? null,
      unit,
      basis,
      data_status,
    }))
    .sort((left, right) => (
      left.nutrient_id.localeCompare(right.nutrient_id)
      || left.basis.localeCompare(right.basis)
    ));
}

const distinctProteinTuples = [
  { nutrient_id: "protein", amount: "1.234568", unit: "g", basis: "per_100g", data_status: "known" },
  { nutrient_id: "protein", amount: "1.234567", unit: "g", basis: "per_serving", data_status: "known" },
];

async function createPersistedFood(input: FoodCreateInput = persistedFoodInput) {
  const database = new LocalSQLiteTestDatabase();
  openDatabases.add(database);
  await database.initialize();
  await ensureLocalNutrientCatalog(database.asExpoDatabase());
  await seedLocalOwner(database, OWNER);
  const runtime = createLocalFoodsRuntime(database.asExpoDatabase(), OWNER);
  const food = await runtime.create({
    ...input,
    client_request_id: "00000000-0000-4000-8000-000000000268",
  });
  return { database, runtime, food };
}

function renderFood(
  food: Food,
  options: {
    servingManagementOnly?: boolean;
    onSavedFood?: (saved: Food) => void;
    onSaved?: (foodId: string) => void;
  } = {},
): TestRenderer.ReactTestRenderer {
  let renderer!: TestRenderer.ReactTestRenderer;
  act(() => {
    renderer = TestRenderer.create(
      React.createElement(FoodFormScreen, {
        food,
        onCancel: jest.fn(),
        onSaved: options.onSaved ?? jest.fn(),
        onSavedFood: options.onSavedFood,
        servingManagementOnly: options.servingManagementOnly,
      }),
    );
  });
  activeRenderers.add(renderer);
  return renderer;
}

async function changeServing(renderer: TestRenderer.ReactTestRenderer): Promise<void> {
  await act(async () => {
    renderer.root.findByProps({ accessibilityLabel: "Edit 1 scoop" }).props.onPress();
  });
  await act(async () => {
    renderer.root.findByProps({ accessibilityLabel: "Serving quantity" }).props.onChangeText("2");
  });
}

async function save(renderer: TestRenderer.ReactTestRenderer, label: string): Promise<void> {
  await act(async () => {
    await renderer.root.findByProps({ accessibilityLabel: label }).props.onPress();
  });
}

beforeEach(() => {
  let sequence = 2680;
  (Crypto.randomUUID as jest.Mock).mockImplementation(() => {
    sequence += 1;
    return `00000000-0000-4000-8000-${sequence.toString().padStart(12, "0")}`;
  });
  mockCreateFood.mockReset();
  mockUpdateFood.mockReset();
  mockNutrientQuery = noCatalogState("loading");
});

afterEach(async () => {
  await act(async () => {
    for (const renderer of activeRenderers) {
      try {
        renderer.unmount();
      } catch {
        // The renderer was already unmounted by the test.
      }
    }
  });
  activeRenderers.clear();
  for (const database of openDatabases) database.close();
  openDatabases.clear();
});

test.each([
  { name: "unresolved", query: noCatalogState("loading") },
  { name: "failed", query: noCatalogState("error") },
])(
  "ordinary Edit Food preserves every nutrient through a $name catalog query",
  async ({ query }) => {
    mockNutrientQuery = query;
    const { runtime, food } = await createPersistedFood();
    const payloads: FoodMutationInput[] = [];
    mockUpdateFood.mockImplementation(async ({ foodId, input }: { foodId: string; input: FoodMutationInput }) => {
      payloads.push(input);
      return runtime.update(foodId, input);
    });

    const renderer = renderFood(food);
    expect(textContent(renderer.root.findAllByType(Text).find((node) =>
      textContent(node).includes(query.isLoading ? "Loading nutrient fields" : "Nutrient fields are unavailable"),
    )!)).toContain(query.isLoading ? "Loading nutrient fields" : "Nutrient fields are unavailable");
    await changeServing(renderer);
    await save(renderer, "Save food");

    expect(payloads).toHaveLength(1);
    expect(nutrientTuples(payloads[0]!)).toEqual(nutrientTuples(food));
    const reloaded = await runtime.get(food.id);
    expect(nutrientTuples(reloaded)).toEqual(nutrientTuples(food));
    expect(reloaded.serving_definitions.find((serving) => serving.unit === "scoop"))
      .toEqual(expect.objectContaining({ quantity: "2.000000", gram_weight: "30.000000" }));
  },
);

test.each([
  { name: "unresolved", query: noCatalogState("loading") },
  { name: "failed", query: noCatalogState("error") },
])(
  "ordinary Edit Food retains same-ID nutrients at distinct bases through a $name catalog query",
  async ({ query }) => {
    mockNutrientQuery = query;
    const { runtime, food } = await createPersistedFood(sameBasisPersistedFoodInput);
    const payloads: FoodMutationInput[] = [];
    mockUpdateFood.mockImplementation(async ({ foodId, input }: { foodId: string; input: FoodMutationInput }) => {
      payloads.push(input);
      return runtime.update(foodId, input);
    });

    const renderer = renderFood(food);
    await changeServing(renderer);
    await save(renderer, "Save food");

    expect(payloads).toHaveLength(1);
    expect(nutrientTuples(payloads[0]!).filter(({ nutrient_id }) => nutrient_id === "protein"))
      .toEqual(distinctProteinTuples);
    const saved = await runtime.get(food.id);
    expect(nutrientTuples(saved).filter(({ nutrient_id }) => nutrient_id === "protein"))
      .toEqual(distinctProteinTuples);
    expect(saved.serving_definitions.find((serving) => serving.unit === "scoop"))
      .toEqual(expect.objectContaining({ quantity: "2.000000", gram_weight: "30.000000" }));
  },
);

test.each([
  { name: "unresolved", query: noCatalogState("loading") },
  { name: "failed", query: noCatalogState("error") },
])(
  "ordinary Edit Food recovers from a $name catalog query without losing serving or nutrient edits",
  async ({ query }) => {
    mockNutrientQuery = query;
    const { runtime, food } = await createPersistedFood();
    const payloads: FoodMutationInput[] = [];
    mockUpdateFood.mockImplementation(async ({ foodId, input }: { foodId: string; input: FoodMutationInput }) => {
      payloads.push(input);
      return runtime.update(foodId, input);
    });

    const renderer = renderFood(food);
    await changeServing(renderer);

    mockNutrientQuery = loadedCatalogState();
    await act(async () => {
      renderer.update(
        React.createElement(FoodFormScreen, {
          food,
          onCancel: jest.fn(),
          onSaved: jest.fn(),
        }),
      );
    });

    expect(renderer.root.findByProps({ accessibilityLabel: "Calories amount" }).props.value).toBe("123.46");
    expect(renderer.root.findByProps({ accessibilityLabel: "Protein amount" }).props.value).toBe("28.35");
    expect(renderer.root.findByProps({ accessibilityLabel: "Calcium amount" }).props.value).toBe("0");
    await act(async () => {
      renderer.root.findByProps({ accessibilityLabel: "Protein amount" }).props.onChangeText("42.5");
    });
    expect(renderer.root.findByProps({ accessibilityLabel: "Protein amount" }).props.value).toBe("42.5");
    await save(renderer, "Save food");

    expect(payloads).toHaveLength(1);
    const saved = await runtime.get(food.id);
    expect(nutrientTuples(saved)).toEqual([
      { nutrient_id: "calcium", amount: "0.000000", unit: "mg", basis: "per_serving", data_status: "zero" },
      { nutrient_id: "calories", amount: "123.456789", unit: "kcal", basis: "per_serving", data_status: "known" },
      { nutrient_id: "chloride", amount: "12.375001", unit: "mg", basis: "per_serving", data_status: "known" },
      { nutrient_id: "protein", amount: "42.500000", unit: "g", basis: "per_100g", data_status: "known" },
      { nutrient_id: "sodium", amount: "9.125001", unit: "mg", basis: "per_serving", data_status: "known" },
      { nutrient_id: "vitamin_d", amount: null, unit: "mcg", basis: "per_serving", data_status: "unknown" },
    ]);
    expect(saved.serving_definitions.find((serving) => serving.unit === "scoop"))
      .toEqual(expect.objectContaining({ quantity: "2.000000", gram_weight: "30.000000" }));
  },
);

test.each([
  { name: "unresolved", query: noCatalogState("loading") },
  { name: "failed", query: noCatalogState("error") },
])(
  "Recipe serving management preserves every nutrient through a $name catalog query and returns the saved Food",
  async ({ query }) => {
    mockNutrientQuery = query;
    const { runtime, food } = await createPersistedFood();
    const payloads: FoodMutationInput[] = [];
    const onSavedFood = jest.fn();
    const onSaved = jest.fn();
    mockUpdateFood.mockImplementation(async ({ foodId, input }: { foodId: string; input: FoodMutationInput }) => {
      payloads.push(input);
      return runtime.update(foodId, input);
    });

    const renderer = renderFood(food, { servingManagementOnly: true, onSavedFood, onSaved });
    expect(renderer.root.findByProps({ accessibilityLabel: "Save serving sizes" })).toBeDefined();
    await changeServing(renderer);
    await act(async () => {
      await renderer.root.findByProps({ accessibilityLabel: "Save serving sizes" }).props.onPress();
    });

    expect(payloads).toHaveLength(1);
    const saved = await runtime.get(food.id);
    expect(nutrientTuples(payloads[0]!)).toEqual(nutrientTuples(food));
    expect(nutrientTuples(saved)).toEqual(nutrientTuples(food));
    expect(onSavedFood).toHaveBeenCalledWith(saved);
    expect(onSaved).toHaveBeenCalledWith(food.id);
    expect(onSavedFood.mock.calls[0]?.[0]).toEqual(expect.objectContaining({ id: food.id }));
    // FoodFormScreen invokes the Recipe reconciliation callback before navigation.
    expect(onSavedFood.mock.invocationCallOrder[0]).toBeLessThan(
      onSaved.mock.invocationCallOrder[0] ?? Number.POSITIVE_INFINITY,
    );
  },
);

test.each([
  { name: "unresolved", query: noCatalogState("loading") },
  { name: "failed", query: noCatalogState("error") },
])(
  "Recipe serving management retains same-ID nutrients at distinct bases through a $name catalog query",
  async ({ query }) => {
    mockNutrientQuery = query;
    const { runtime, food } = await createPersistedFood(sameBasisPersistedFoodInput);
    const payloads: FoodMutationInput[] = [];
    const onSavedFood = jest.fn();
    const onSaved = jest.fn();
    mockUpdateFood.mockImplementation(async ({ foodId, input }: { foodId: string; input: FoodMutationInput }) => {
      payloads.push(input);
      return runtime.update(foodId, input);
    });

    const renderer = renderFood(food, { servingManagementOnly: true, onSavedFood, onSaved });
    await changeServing(renderer);
    await save(renderer, "Save serving sizes");

    expect(payloads).toHaveLength(1);
    expect(nutrientTuples(payloads[0]!).filter(({ nutrient_id }) => nutrient_id === "protein"))
      .toEqual(distinctProteinTuples);
    const saved = await runtime.get(food.id);
    expect(nutrientTuples(saved).filter(({ nutrient_id }) => nutrient_id === "protein"))
      .toEqual(distinctProteinTuples);
    expect(onSavedFood).toHaveBeenCalledWith(saved);
    expect(onSaved).toHaveBeenCalledWith(food.id);
  },
);

test("loaded catalog ordinary Edit Food keeps exact same-ID bases behind the rounded display", async () => {
  mockNutrientQuery = loadedCatalogState();
  const { runtime, food } = await createPersistedFood(sameBasisPersistedFoodInput);
  const payloads: FoodMutationInput[] = [];
  mockUpdateFood.mockImplementation(async ({ foodId, input }: { foodId: string; input: FoodMutationInput }) => {
    payloads.push(input);
    return runtime.update(foodId, input);
  });

  const renderer = renderFood(food);
  expect(renderer.root.findByProps({ accessibilityLabel: "Protein amount" }).props.value).toBe("1.23");
  await changeServing(renderer);
  await save(renderer, "Save food");

  expect(payloads).toHaveLength(1);
  expect(nutrientTuples(payloads[0]!).filter(({ nutrient_id }) => nutrient_id === "protein"))
    .toEqual(distinctProteinTuples);
  const saved = await runtime.get(food.id);
  expect(nutrientTuples(saved).filter(({ nutrient_id }) => nutrient_id === "protein"))
    .toEqual(distinctProteinTuples);
});

test("recovery starts with a loaded catalog, then a failed reload preserves edits", async () => {
  mockNutrientQuery = loadedCatalogState();
  const { runtime, food } = await createPersistedFood();
  const payloads: FoodMutationInput[] = [];
  mockUpdateFood.mockImplementation(async ({ foodId, input }: { foodId: string; input: FoodMutationInput }) => {
    payloads.push(input);
    return runtime.update(foodId, input);
  });

  const renderer = renderFood(food);
  await act(async () => {
    renderer.root.findByProps({ accessibilityLabel: "Calories amount" }).props.onChangeText("456.75");
  });
  await act(async () => {
    renderer.root.findByProps({ accessibilityLabel: "Protein amount" }).props.onChangeText("42.5");
  });
  await act(async () => {
    renderer.root.findByProps({ accessibilityLabel: "Calcium amount" }).props.onChangeText("0.0");
  });
  await act(async () => {
    renderer.root.findByProps({ accessibilityLabel: "Omit Sodium" }).props.onPress();
  });
  expect(renderer.root.findByProps({ accessibilityLabel: "Protein amount" }).props.value).toBe("42.5");
  expect(renderer.root.findByProps({ accessibilityLabel: "Calcium amount" }).props.value).toBe("0.0");

  mockNutrientQuery = noCatalogState("error");
  await act(async () => {
    renderer.update(
      React.createElement(FoodFormScreen, {
        food,
        onCancel: jest.fn(),
        onSaved: jest.fn(),
      }),
    );
  });
  expect(renderer.root.findAllByProps({ accessibilityLabel: "Protein amount" })).toHaveLength(0);
  await changeServing(renderer);
  await save(renderer, "Save food");

  const saved = await runtime.get(food.id);
  expect(payloads).toHaveLength(1);
  expect(nutrientTuples(saved)).toEqual([
    { nutrient_id: "calcium", amount: "0.000000", unit: "mg", basis: "per_serving", data_status: "zero" },
    { nutrient_id: "calories", amount: "456.750000", unit: "kcal", basis: "per_serving", data_status: "known" },
    { nutrient_id: "chloride", amount: "12.375001", unit: "mg", basis: "per_serving", data_status: "known" },
    { nutrient_id: "protein", amount: "42.500000", unit: "g", basis: "per_100g", data_status: "known" },
    { nutrient_id: "sodium", amount: null, unit: "mg", basis: "per_serving", data_status: "unknown" },
    { nutrient_id: "vitamin_d", amount: null, unit: "mcg", basis: "per_serving", data_status: "unknown" },
  ]);
  expect(nutrientTuples(payloads[0]!)).toEqual(expect.arrayContaining([
    { nutrient_id: "chloride", amount: "12.375001", unit: "mg", basis: "per_serving", data_status: "known" },
    { nutrient_id: "protein", amount: "42.5", unit: "g", basis: "per_100g", data_status: "known" },
    { nutrient_id: "sodium", amount: null, unit: "mg", basis: "per_serving", data_status: "unknown" },
  ]));
});

test("loaded catalog Recipe serving management keeps the full Food replacement payload", async () => {
  mockNutrientQuery = loadedCatalogState();
  const { runtime, food } = await createPersistedFood();
  const payloads: FoodMutationInput[] = [];
  const onSavedFood = jest.fn();
  const onSaved = jest.fn();
  mockUpdateFood.mockImplementation(async ({ foodId, input }: { foodId: string; input: FoodMutationInput }) => {
    payloads.push(input);
    return runtime.update(foodId, input);
  });

  const renderer = renderFood(food, { servingManagementOnly: true, onSavedFood, onSaved });
  expect(renderer.root.findAllByProps({ accessibilityLabel: "Calories amount" })).toHaveLength(0);
  await changeServing(renderer);
  await save(renderer, "Save serving sizes");

  expect(payloads).toHaveLength(1);
  const saved = await runtime.get(food.id);
  expect(nutrientTuples(payloads[0]!)).toEqual(nutrientTuples(food));
  expect(nutrientTuples(saved)).toEqual(nutrientTuples(food));
  expect(saved.serving_definitions.find((serving) => serving.unit === "scoop"))
    .toEqual(expect.objectContaining({ quantity: "2.000000", gram_weight: "30.000000" }));
  expect(onSavedFood).toHaveBeenCalledWith(saved);
  expect(onSaved).toHaveBeenCalledWith(food.id);
});

test("an unavailable-catalog payload cannot cross the Food owner boundary", async () => {
  mockNutrientQuery = noCatalogState("error");
  const { runtime, database, food } = await createPersistedFood();
  const payloads: FoodMutationInput[] = [];
  mockUpdateFood.mockImplementation(async ({ foodId, input }: { foodId: string; input: FoodMutationInput }) => {
    payloads.push(input);
    return runtime.update(foodId, input);
  });
  const renderer = renderFood(food);
  await changeServing(renderer);
  await save(renderer, "Save food");
  expect(payloads).toHaveLength(1);
  const ownerFoodBeforeForeignUpdate = await runtime.get(food.id);

  const otherRuntime = createLocalFoodsRuntime(database.asExpoDatabase(), OTHER_OWNER);
  await expect(otherRuntime.update(food.id, payloads[0]!)).rejects.toMatchObject({
    code: "food_not_found",
    mutationOutcome: "confirmed_non_commit",
  });
  await expect(runtime.get(food.id)).resolves.toEqual(ownerFoodBeforeForeignUpdate);
});
