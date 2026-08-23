import {
  createRecipe,
  duplicateRecipe,
  getRecipe,
  getRecipeNutrition,
  listRecipes,
  publishRecipe,
  updateRecipe,
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

function ordinaryRecipeResponse() {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    user_id: "22222222-2222-4222-8222-222222222222",
    published_food_item_id: null,
    name: "Soup",
    notes: null,
    serving_count_yield: "6.000000",
    final_cooked_weight_grams: null,
    final_cooked_weight_display_quantity: null,
    final_cooked_weight_display_unit: null,
    needs_republish: true,
    created_at: "2026-07-10T00:00:00Z",
    updated_at: "2026-07-10T00:00:00+00:00",
    ingredients: [
      {
        id: "33333333-3333-4333-8333-333333333333",
        recipe_id: "11111111-1111-4111-8111-111111111111",
        food_item_id: "44444444-4444-4444-8444-444444444444",
        position: 0,
        amount_quantity: "50.000000",
        amount_unit: "g" as const,
        serving_definition_id: null,
        resolved_gram_amount: "50.000000",
        preparation_note: null,
        amount_display_quantity: "1.763698",
        amount_display_unit: "oz",
      },
    ],
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
    json: async () =>
      ordinaryRecipeResponse(),
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
    json: async () => ({
      ...ordinaryRecipeResponse(),
      id: "55555555-5555-4555-8555-555555555555",
      name: "Soup Copy",
      ingredients: ordinaryRecipeResponse().ingredients.map((ingredient) => ({
        ...ingredient,
        id: "66666666-6666-4666-8666-666666666666",
        recipe_id: "55555555-5555-4555-8555-555555555555",
      })),
    }),
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


test(
  "general Recipe list validates the complete ordinary Recipe wire shape",
  async () => {
    const recipe =
      ordinaryRecipeResponse();

    mockSuccessfulJson({
      recipes: [recipe],
    });

    await expect(
      listRecipes(),
    ).resolves.toEqual([recipe]);

    expect(
      (await listRecipes())[0]
        .published_food_item_id,
    ).toBeNull();

    expect(
      (await listRecipes())[0]
        .needs_republish,
    ).toBe(true);
  },
);

test(
  "general Recipe get validates nullable publication identity and ordinary republish state",
  async () => {
    const recipe =
      ordinaryRecipeResponse();

    mockSuccessfulJson(recipe);

    await expect(
      getRecipe(
        "11111111-1111-4111-8111-111111111111",
      ),
    ).resolves.toEqual(recipe);
  },
);

test(
  "general Recipe update validates the complete successful response",
  async () => {
    const recipe = {
      ...ordinaryRecipeResponse(),
      needs_republish: false,
      updated_at:
        "2026-07-11T00:00:00Z",
    };

    mockSuccessfulJson(recipe);

    await expect(
      updateRecipe(
        "11111111-1111-4111-8111-111111111111",
        {
          name: "Soup",
          notes: null,
          serving_count_yield: "6",
          final_cooked_weight_grams: null,
          ingredients: [],
        },
      ),
    ).resolves.toEqual(recipe);
  },
);

const malformedOrdinaryRecipeCases: Array<[
  string,
  () => unknown,
]> = [
  [
    "missing backend-emitted field",
    () => {
      const value =
        ordinaryRecipeResponse() as
        Record<string, unknown>;

      delete value.published_food_item_id;

      return value;
    },
  ],
  [
    "invalid Recipe UUID",
    () => ({
      ...ordinaryRecipeResponse(),
      id: "recipe-1",
    }),
  ],
  [
    "invalid ingredient UUID",
    () => ({
      ...ordinaryRecipeResponse(),
      ingredients: [
        {
          ...ordinaryRecipeResponse()
            .ingredients[0],
          food_item_id: "food-1",
        },
      ],
    }),
  ],
  [
    "negative ingredient position",
    () => ({
      ...ordinaryRecipeResponse(),
      ingredients: [
        {
          ...ordinaryRecipeResponse()
            .ingredients[0],
          position: -1,
        },
      ],
    }),
  ],
  [
    "numeric exact decimal",
    () => ({
      ...ordinaryRecipeResponse(),
      serving_count_yield: 6,
    }),
  ],
  [
    "signed exact decimal",
    () => ({
      ...ordinaryRecipeResponse(),
      serving_count_yield: "-6",
    }),
  ],
  [
    "exponent exact decimal",
    () => ({
      ...ordinaryRecipeResponse(),
      ingredients: [
        {
          ...ordinaryRecipeResponse()
            .ingredients[0],
          amount_quantity: "5e1",
        },
      ],
    }),
  ],
  [
    "invalid amount unit",
    () => ({
      ...ordinaryRecipeResponse(),
      ingredients: [
        {
          ...ordinaryRecipeResponse()
            .ingredients[0],
          amount_unit: "oz",
        },
      ],
    }),
  ],
  [
    "timestamp without offset",
    () => ({
      ...ordinaryRecipeResponse(),
      updated_at:
        "2026-07-10T00:00:00",
    }),
  ],
  [
    "unexpected nested field",
    () => ({
      ...ordinaryRecipeResponse(),
      ingredients: [
        {
          ...ordinaryRecipeResponse()
            .ingredients[0],
          unexpected: true,
        },
      ],
    }),
  ],
  [
    "unexpected top-level field",
    () => ({
      ...ordinaryRecipeResponse(),
      unexpected: true,
    }),
  ],
];

test.each(
  malformedOrdinaryRecipeCases,
)(
  "general Recipe get rejects %s",
  async (_name, buildResponse) => {
    mockSuccessfulJson(
      buildResponse(),
    );

    await expect(
      getRecipe(
        "11111111-1111-4111-8111-111111111111",
      ),
    ).rejects.toThrow();
  },
);

test(
  "general Recipe list rejects malformed wrapper and nested Recipe",
  async () => {
    mockSuccessfulJson({
      recipes: [
        {
          ...ordinaryRecipeResponse(),
          id: "recipe-1",
        },
      ],
    });

    await expect(
      listRecipes(),
    ).rejects.toThrow();

    mockSuccessfulJson({
      recipes: [
        ordinaryRecipeResponse(),
      ],
      unexpected: true,
    });

    await expect(
      listRecipes(),
    ).rejects.toThrow();
  },
);

test(
  "Recipe nutrition rejects malformed exact decimals, units, counts, and extra fields",
  async () => {
    mockSuccessfulJson({
      totals: [
        {
          nutrient_id: "protein",
          amount_known: 10,
          amount_estimated: "0",
          unit: "g",
          has_unknown_contributors:
            false,
          unknown_contributor_count: 0,
        },
      ],
      per_serving: null,
      per_100g: null,
    });

    await expect(
      getRecipeNutrition(
        "11111111-1111-4111-8111-111111111111",
      ),
    ).rejects.toThrow();

    mockSuccessfulJson({
      totals: [
        {
          nutrient_id: "protein",
          amount_known: "10",
          amount_estimated: "0",
          unit: "oz",
          has_unknown_contributors:
            false,
          unknown_contributor_count: 0,
        },
      ],
      per_serving: null,
      per_100g: null,
    });

    await expect(
      getRecipeNutrition(
        "11111111-1111-4111-8111-111111111111",
      ),
    ).rejects.toThrow();

    mockSuccessfulJson({
      totals: [
        {
          nutrient_id: "protein",
          amount_known: "10",
          amount_estimated: "0",
          unit: "g",
          has_unknown_contributors:
            true,
          unknown_contributor_count: -1,
        },
      ],
      per_serving: null,
      per_100g: null,
    });

    await expect(
      getRecipeNutrition(
        "11111111-1111-4111-8111-111111111111",
      ),
    ).rejects.toThrow();

    mockSuccessfulJson({
      totals: [],
      per_serving: null,
      per_100g: null,
      unexpected: true,
    });

    await expect(
      getRecipeNutrition(
        "11111111-1111-4111-8111-111111111111",
      ),
    ).rejects.toThrow();
  },
);

test(
  "publication remains stricter than the general Recipe parser",
  async () => {
    const nullablePublication =
      recipePublishResponse();

    nullablePublication.recipe
      .published_food_item_id =
        null as unknown as string;

    mockSuccessfulJson(
      nullablePublication,
    );

    await expect(
      publishRecipe({
        recipeId:
          "00000000-0000-4000-8000-000000000301",
        clientRequestId:
          "00000000-0000-4000-8000-000000000302",
      }),
    ).rejects.toThrow();

    const dirtyPublication =
      recipePublishResponse();

    dirtyPublication.recipe
      .needs_republish =
        true as false;

    mockSuccessfulJson(
      dirtyPublication,
    );

    await expect(
      publishRecipe({
        recipeId:
          "00000000-0000-4000-8000-000000000301",
        clientRequestId:
          "00000000-0000-4000-8000-000000000302",
      }),
    ).rejects.toThrow();
  },
);
