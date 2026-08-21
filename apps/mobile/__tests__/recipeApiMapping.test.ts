import {
  createRecipe,
  duplicateRecipe,
  getRecipeNutrition,
  listRecipes,
  publishRecipe,
} from "../src/features/recipes/api/recipeApi";

function recipePublishResponse() {
  return {
    recipe: {
      id: "00000000-0000-4000-8000-000000000301",
      user_id: "00000000-0000-4000-8000-000000000001",
      published_food_item_id: "00000000-0000-4000-8000-000000000401",
      name: "Soup",
      notes: null,
      serving_count_yield: "0002.5000",
      final_cooked_weight_grams: null,
      final_cooked_weight_display_quantity: null,
      final_cooked_weight_display_unit: null,
      needs_republish: false,
      created_at: "2026-07-10T00:00:00Z",
      updated_at: "2026-07-10T00:00:00+00:00",
      ingredients: [{
        id: "00000000-0000-4000-8000-000000000501",
        recipe_id: "00000000-0000-4000-8000-000000000301",
        food_item_id: "00000000-0000-4000-8000-000000000402",
        position: 0,
        amount_quantity: "1.250000",
        amount_unit: "g",
        serving_definition_id: null,
        resolved_gram_amount: "1.250000",
        preparation_note: null,
        amount_display_quantity: "0.044092",
        amount_display_unit: "oz",
      }],
    },
    food: {
      id: "00000000-0000-4000-8000-000000000401",
      name: "Soup",
      brand: null,
      notes: null,
      source_type: "recipe",
      source_id: "00000000-0000-4000-8000-000000000301",
      is_recipe: true,
      source_kind: "recipe" as const,
      source_label: "Recipe",
      is_favorite: false,
      can_favorite: false,
      created_at: "2026-07-10T00:00:00Z",
      updated_at: "2026-07-10T00:00:00Z",
      serving_definitions: [{
        id: "00000000-0000-4000-8000-000000000601",
        label: "1 serving",
        quantity: "1.000000",
        unit: "serving",
        gram_weight: "125.000000",
        reference_quantity: null,
        reference_unit: null,
        reference_gram_weight: null,
        is_default: true,
        source: "recipe",
        is_user_confirmed: true,
      }],
      nutrients: [{
        id: "00000000-0000-4000-8000-000000000701",
        nutrient_id: "protein",
        amount: "10.500000",
        unit: "g" as const,
        basis: "per_serving" as const,
        data_status: "known" as const,
        source: "recipe",
        is_user_confirmed: true,
        original_amount: null,
        original_unit: null,
        original_text: null,
      }],
    },
  };
}

function mockSuccessfulJson(value: unknown): void {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => value,
  });
}

test("recipe list uses the full list for an empty query and filters non-empty queries", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ recipes: [] }),
  });

  await listRecipes("");
  expect(global.fetch).toHaveBeenLastCalledWith(
    "http://localhost:8000/api/v1/recipes",
    expect.any(Object),
  );

  await listRecipes("soup");
  expect(global.fetch).toHaveBeenLastCalledWith(
    "http://localhost:8000/api/v1/recipes?q=soup",
    expect.any(Object),
  );
});

test("recipe create API sends ingredient payload", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 201,
    json: async () => ({
      id: "recipe-1",
      user_id: "user-1",
      name: "Soup",
      ingredients: [],
      created_at: "2026-07-10T00:00:00Z",
      updated_at: "2026-07-10T00:00:00Z",
    }),
  });

  await createRecipe({
    client_request_id: "recipe-request-1",
    name: "Soup",
    notes: null,
    serving_count_yield: "6",
    final_cooked_weight_grams: null,
    ingredients: [
      {
        food_item_id: "food-1",
        position: 0,
        amount_quantity: "50",
        amount_unit: "g",
        serving_definition_id: null,
      },
    ],
  });

  expect(global.fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/recipes",
    expect.objectContaining({
      method: "POST",
      body: expect.stringContaining('"amount_unit":"g"'),
    }),
  );
  expect(JSON.parse((global.fetch as jest.Mock).mock.calls[0][1].body)).toMatchObject({
    client_request_id: "recipe-request-1",
  });
});

test("recipe nutrition API maps snake case totals to mobile shape", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      totals: [
        {
          nutrient_id: "protein",
          amount_known: "10",
          amount_estimated: "0",
          unit: "g",
          has_unknown_contributors: true,
          unknown_contributor_count: 1,
        },
      ],
      per_serving: null,
      per_100g: [
        {
          nutrient_id: "protein",
          amount_known: "2",
          amount_estimated: "0",
          unit: "g",
          has_unknown_contributors: false,
          unknown_contributor_count: 0,
        },
      ],
    }),
  });

  await expect(getRecipeNutrition("recipe-1")).resolves.toEqual({
    totals: [
      {
        nutrientId: "protein",
        amountKnown: "10",
        amountEstimated: "0",
        unit: "g",
        hasUnknownContributors: true,
        unknownContributorCount: 1,
      },
    ],
    perServing: null,
    per100g: [
      {
        nutrientId: "protein",
        amountKnown: "2",
        amountEstimated: "0",
        unit: "g",
        hasUnknownContributors: false,
        unknownContributorCount: 0,
      },
    ],
  });
});

test("recipe publish posts to publish endpoint", async () => {
  mockSuccessfulJson(recipePublishResponse());

  const result = await publishRecipe({
    recipeId: "00000000-0000-4000-8000-000000000301",
    clientRequestId: "00000000-0000-4000-8000-000000000302",
  });

  expect(result.recipe.serving_count_yield).toBe("0002.5000");
  expect(result.food.nutrients[0]?.amount).toBe("10.500000");

  expect(global.fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/recipes/00000000-0000-4000-8000-000000000301/publish",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        client_request_id: "00000000-0000-4000-8000-000000000302",
      }),
    }),
  );
});

const malformedPublicationCases: Array<[
  string,
  (value: ReturnType<typeof recipePublishResponse>) => unknown,
]> = [
  ["missing required top-level field", ({ food: _food, ...value }) => value],
  ["wrong top-level primitive", () => "not-an-object"],
  ["malformed nested Recipe", (value) => ({ ...value, recipe: null })],
  ["malformed ingredient array item", (value) => ({
    ...value,
    recipe: { ...value.recipe, ingredients: [null] },
  })],
  ["decimal supplied as a JSON number", (value) => ({
    ...value,
    recipe: { ...value.recipe, serving_count_yield: 2.5 },
  })],
  ["invalid decimal text", (value) => ({
    ...value,
    food: {
      ...value.food,
      serving_definitions: [{ ...value.food.serving_definitions[0], quantity: "1e3" }],
    },
  })],
  ["overlong decimal text", (value) => ({
    ...value,
    recipe: { ...value.recipe, serving_count_yield: "1".repeat(129) },
  })],
  ["wrong finite nutrient unit", (value) => ({
    ...value,
    food: {
      ...value.food,
      nutrients: [{ ...value.food.nutrients[0], unit: "oz" }],
    },
  })],
  ["wrong managed Food source kind", (value) => ({
    ...value,
    food: { ...value.food, source_kind: "manual" },
  })],
  ["mismatched managed Food identity", (value) => ({
    ...value,
    food: {
      ...value.food,
      id: "00000000-0000-4000-8000-000000000499",
    },
  })],
  ["null where a UUID is required", (value) => ({
    ...value,
    recipe: { ...value.recipe, id: null },
  })],
  ["invalid nested UUID", (value) => ({
    ...value,
    food: {
      ...value.food,
      serving_definitions: [{ ...value.food.serving_definitions[0], id: "serving-1" }],
    },
  })],
  ["unexpected top-level field", (value) => ({ ...value, unexpected: true })],
  ["unexpected nested Food field", (value) => ({
    ...value,
    food: { ...value.food, unexpected: true },
  })],
];

test.each(malformedPublicationCases)(
  "Recipe publication rejects %s",
  async (_label, mutate) => {
    mockSuccessfulJson(mutate(recipePublishResponse()));

    await expect(publishRecipe({
      recipeId: "00000000-0000-4000-8000-000000000301",
      clientRequestId: "00000000-0000-4000-8000-000000000302",
    })).rejects.toThrow();
  },
);

test("recipe duplicate posts only the client request id to the duplicate endpoint", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 201,
    json: async () => ({ id: "recipe-copy", name: "Soup Copy", ingredients: [] }),
  });

  await duplicateRecipe({ recipeId: "recipe-1", clientRequestId: "request-2" });

  expect(global.fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/recipes/recipe-1/duplicate",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ client_request_id: "request-2" }),
    }),
  );
});
