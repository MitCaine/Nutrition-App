import { createRecipe, getRecipeNutrition, listRecipes, publishRecipe } from "../src/features/recipes/api/recipeApi";

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
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      recipe: { id: "recipe-1", name: "Soup", ingredients: [] },
      food: { id: "food-1", name: "Soup", is_recipe: true, serving_definitions: [], nutrients: [] },
    }),
  });

  await publishRecipe("recipe-1");

  expect(global.fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/recipes/recipe-1/publish",
    expect.objectContaining({ method: "POST" }),
  );
});
