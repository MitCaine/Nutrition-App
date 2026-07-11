import { ApiError, apiRequest } from "../src/shared/api/client";
import { deleteFood } from "../src/features/foods/api/foodApi";
import {
  apiErrorMessage,
  formatAffectedRecipeNames,
  formatFoodDeleteSuccess,
  parseFoodDeleteDependency,
} from "../src/features/foods/utils/foodDelete";

function dependencyError(detail: unknown): ApiError {
  return new ApiError({
    status: 409,
    message: "Food is used by active recipes",
    body: { detail },
  });
}

const validDependency = {
  food_id: "food-1",
  active_recipe_count: 2,
  total_ingredient_rows_affected: 3,
  affected_recipes: [
    {
      recipe_id: "recipe-1",
      recipe_name: "Chili",
      ingredient_occurrence_count: 2,
      is_published: true,
      needs_republish: false,
    },
    {
      recipe_id: "recipe-2",
      recipe_name: "Soup",
      ingredient_occurrence_count: 1,
      is_published: false,
      needs_republish: false,
    },
  ],
};

function expectRejectedDependency(detail: unknown): void {
  const error = dependencyError(detail);
  expect(parseFoodDeleteDependency(error)).toBeNull();
  expect(apiErrorMessage(error, "Could not delete food")).toBe("Food is used by active recipes");
}

test("food delete API sends explicit force flag only when requested", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      food_id: "food-1",
      deleted: true,
      removed_ingredient_count: 0,
      affected_recipes: [],
    }),
  });

  await deleteFood({ foodId: "food-1" });
  await deleteFood({ foodId: "food-1", removeFromRecipes: true });

  expect(global.fetch).toHaveBeenNthCalledWith(
    1,
    "http://localhost:8000/api/v1/foods/food-1",
    expect.objectContaining({ method: "DELETE" }),
  );
  expect(global.fetch).toHaveBeenNthCalledWith(
    2,
    "http://localhost:8000/api/v1/foods/food-1?remove_from_recipes=true",
    expect.objectContaining({ method: "DELETE" }),
  );
});

test("valid structured 409 dependency conflict is parsed into confirmation state data", () => {
  const dependency = parseFoodDeleteDependency(dependencyError(validDependency));

  expect(dependency?.active_recipe_count).toBe(2);
  expect(dependency?.affected_recipes[0].recipe_name).toBe("Chili");
  expect(dependency?.total_ingredient_rows_affected).toBe(3);
});

test("dependency parser rejects mismatched active recipe counts", () => {
  expectRejectedDependency({
    ...validDependency,
    active_recipe_count: 1,
  });
});

test("dependency parser rejects mismatched total ingredient row counts", () => {
  expectRejectedDependency({
    ...validDependency,
    total_ingredient_rows_affected: 4,
  });
});

test("dependency parser rejects an empty affected recipe array", () => {
  expectRejectedDependency({
      food_id: "food-1",
      active_recipe_count: 0,
      total_ingredient_rows_affected: 0,
      affected_recipes: [],
  });
});

test.each([
  ["zero active recipe count", { active_recipe_count: 0 }],
  ["negative active recipe count", { active_recipe_count: -1 }],
  ["fractional active recipe count", { active_recipe_count: 1.5 }],
  ["NaN active recipe count", { active_recipe_count: Number.NaN }],
  ["Infinity active recipe count", { active_recipe_count: Infinity }],
  ["zero total rows", { total_ingredient_rows_affected: 0 }],
  ["negative total rows", { total_ingredient_rows_affected: -1 }],
  ["fractional total rows", { total_ingredient_rows_affected: 2.5 }],
  ["NaN total rows", { total_ingredient_rows_affected: Number.NaN }],
  ["Infinity total rows", { total_ingredient_rows_affected: Infinity }],
  [
    "zero recipe occurrence count",
    {
      total_ingredient_rows_affected: 1,
      affected_recipes: [
        { ...validDependency.affected_recipes[0], ingredient_occurrence_count: 0 },
        validDependency.affected_recipes[1],
      ],
    },
  ],
  [
    "negative recipe occurrence count",
    {
      total_ingredient_rows_affected: 0,
      affected_recipes: [
        { ...validDependency.affected_recipes[0], ingredient_occurrence_count: -1 },
        validDependency.affected_recipes[1],
      ],
    },
  ],
  [
    "fractional recipe occurrence count",
    {
      total_ingredient_rows_affected: 2.5,
      affected_recipes: [
        { ...validDependency.affected_recipes[0], ingredient_occurrence_count: 1.5 },
        validDependency.affected_recipes[1],
      ],
    },
  ],
  [
    "NaN recipe occurrence count",
    {
      affected_recipes: [
        { ...validDependency.affected_recipes[0], ingredient_occurrence_count: Number.NaN },
        validDependency.affected_recipes[1],
      ],
    },
  ],
  [
    "Infinity recipe occurrence count",
    {
      affected_recipes: [
        { ...validDependency.affected_recipes[0], ingredient_occurrence_count: Infinity },
        validDependency.affected_recipes[1],
      ],
    },
  ],
])("dependency parser rejects %s", (_name, patch) => {
  expectRejectedDependency({ ...validDependency, ...patch });
});

test.each([
  ["empty food_id", { food_id: "" }],
  ["whitespace food_id", { food_id: "   " }],
  [
    "empty recipe_id",
    {
      affected_recipes: [
        { ...validDependency.affected_recipes[0], recipe_id: "" },
        validDependency.affected_recipes[1],
      ],
    },
  ],
  [
    "whitespace recipe_id",
    {
      affected_recipes: [
        { ...validDependency.affected_recipes[0], recipe_id: "   " },
        validDependency.affected_recipes[1],
      ],
    },
  ],
  [
    "empty recipe_name",
    {
      affected_recipes: [
        { ...validDependency.affected_recipes[0], recipe_name: "" },
        validDependency.affected_recipes[1],
      ],
    },
  ],
  [
    "whitespace recipe_name",
    {
      affected_recipes: [
        { ...validDependency.affected_recipes[0], recipe_name: "   " },
        validDependency.affected_recipes[1],
      ],
    },
  ],
])("dependency parser rejects %s", (_name, patch) => {
  expectRejectedDependency({ ...validDependency, ...patch });
});

test("dependency parser rejects recipe entries with missing required fields", () => {
  expectRejectedDependency({
    ...validDependency,
    total_ingredient_rows_affected: 2,
    affected_recipes: [
      {
        recipe_id: "recipe-1",
        recipe_name: "Chili",
        ingredient_occurrence_count: 1,
        is_published: true,
      },
      validDependency.affected_recipes[1],
    ],
  });
});

test("dependency parser rejects recipe entries with incorrect field types", () => {
  expectRejectedDependency({
    ...validDependency,
    total_ingredient_rows_affected: 2,
    affected_recipes: [
      {
        recipe_id: "recipe-1",
        recipe_name: "Chili",
        ingredient_occurrence_count: "1",
        is_published: true,
        needs_republish: false,
      },
      validDependency.affected_recipes[1],
    ],
  });
});

test("dependency parser rejects mixed valid and malformed recipe entries", () => {
  expectRejectedDependency({
    ...validDependency,
    affected_recipes: [
      validDependency.affected_recipes[0],
      {
        recipe_id: "recipe-2",
        recipe_name: "Soup",
        ingredient_occurrence_count: 1,
        is_published: false,
        needs_republish: "false",
      },
    ],
  });
});

test("malformed dependency payload falls back to normal API error handling", () => {
  expectRejectedDependency({
    ...validDependency,
    total_ingredient_rows_affected: 2,
    affected_recipes: [
      {
        recipe_id: "recipe-1",
        recipe_name: "Chili",
        ingredient_occurrence_count: 1,
        is_published: true,
      },
      validDependency.affected_recipes[1],
    ],
  });
});

test("dependency parser ignores non-409 API failures and malformed errors", () => {
  expect(
    parseFoodDeleteDependency(
      new ApiError({
        status: 404,
        message: "Food not found",
        body: {
          detail: {
            food_id: "food-1",
            active_recipe_count: 1,
            total_ingredient_rows_affected: 1,
            affected_recipes: [],
          },
        },
      }),
    ),
  ).toBeNull();
  expect(
    parseFoodDeleteDependency(
      new ApiError({
        status: 409,
        message: "Conflict",
        body: { detail: "Food is used by active recipes" },
      }),
    ),
  ).toBeNull();
  expect(parseFoodDeleteDependency(new Error("{not json"))).toBeNull();
});

test("affected recipe names use readable singular and list wording", () => {
  expect(formatAffectedRecipeNames([{ recipe_name: "Chili" }])).toBe("Chili");
  expect(formatAffectedRecipeNames([{ recipe_name: "Chili" }, { recipe_name: "Tomato Soup" }])).toBe(
    "Chili and Tomato Soup",
  );
  expect(
    formatAffectedRecipeNames([
      { recipe_name: "Chili" },
      { recipe_name: "Tomato Soup" },
      { recipe_name: "Stew" },
    ]),
  ).toBe("Chili, Tomato Soup, and Stew");
});

test("success message summarizes removals and republish warning", () => {
  expect(
    formatFoodDeleteSuccess({
      food_id: "food-1",
      deleted: true,
      removed_ingredient_count: 0,
      affected_recipes: [],
    }),
  ).toBe("Food deleted");

  expect(
    formatFoodDeleteSuccess({
      food_id: "food-1",
      deleted: true,
      removed_ingredient_count: 2,
      affected_recipes: [
        {
          recipe_id: "recipe-1",
          recipe_name: "Chili",
          removed_ingredient_count: 1,
          needs_republish: true,
        },
        {
          recipe_id: "recipe-2",
          recipe_name: "Tomato Soup",
          removed_ingredient_count: 1,
          needs_republish: false,
        },
      ],
    }),
  ).toBe(
    "Food deleted. Removed from Chili and Tomato Soup. Chili needs to be republished before published nutrition is current.",
  );
});

test("API error message extracts concise backend detail and falls back", () => {
  expect(apiErrorMessage(new ApiError({ status: 404, body: { detail: "Food not found" }, message: "Food not found" }), "Could not delete food")).toBe(
    "Food not found",
  );
  expect(
    apiErrorMessage(
      new ApiError({
        status: 422,
        body: { detail: [{ msg: "Value error, ingredient amount_quantity must be greater than zero" }] },
        message: "Value error, ingredient amount_quantity must be greater than zero",
      }),
      "Could not delete food",
    ),
  ).toBe("Value error, ingredient amount_quantity must be greater than zero");
  expect(apiErrorMessage(new Error("{bad json"), "Could not delete food")).toBe("Could not delete food");
});

test("shared API client exposes status and parsed body on failures", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    status: 409,
    text: async () =>
      JSON.stringify({
        detail: {
          food_id: "food-1",
          active_recipe_count: 1,
          total_ingredient_rows_affected: 1,
          affected_recipes: [],
        },
      }),
  });

  await expect(apiRequest("/foods/food-1", { method: "DELETE" })).rejects.toMatchObject({
    status: 409,
    body: {
      detail: {
        food_id: "food-1",
        active_recipe_count: 1,
      },
    },
  });
});

test("shared API client preserves useful fallback messages for malformed or missing JSON", async () => {
  global.fetch = jest
    .fn()
    .mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: async () => "server unavailable",
    })
    .mockResolvedValueOnce({
      ok: false,
      status: 503,
      text: async () => "",
    });

  await expect(apiRequest("/foods/food-1")).rejects.toMatchObject({
    status: 500,
    body: "server unavailable",
    message: "server unavailable",
  });
  await expect(apiRequest("/foods/food-1")).rejects.toMatchObject({
    status: 503,
    body: null,
    message: "Request failed with status 503",
  });
});
