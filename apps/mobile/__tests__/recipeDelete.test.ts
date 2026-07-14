import { deleteRecipe } from "../src/features/recipes/api/recipeApi";
import {
  parseRecipeDeleteDependency,
  publishedParentWarning,
  recipeDeleteErrorMessage,
} from "../src/features/recipes/utils/recipeDelete";
import { ApiError } from "../src/shared/api/client";

const dependency = {
  code: "recipe_delete_dependencies_exist" as const,
  message: "This Recipe is used by other Recipes.",
  recipe_id: "child-recipe",
  projection_food_item_id: "child-food",
  active_dependent_recipe_count: 2,
  affected_recipes: [
    {
      recipe_id: "parent-1",
      recipe_name: "Published Chili",
      ingredient_occurrence_count: 2,
      is_published: true,
      will_require_republish: true,
    },
    {
      recipe_id: "parent-2",
      recipe_name: "Soup Draft",
      ingredient_occurrence_count: 1,
      is_published: false,
      will_require_republish: false,
    },
  ],
  total_ingredient_rows_affected: 3,
};

function dependencyError(detail: unknown): ApiError {
  return new ApiError({
    status: 409,
    body: { detail },
    message: "Request failed with status 409",
  });
}

test("Recipe dependency conflict maps confirmation names, counts, and publication warning", () => {
  const parsed = parseRecipeDeleteDependency(dependencyError(dependency));

  expect(parsed).toEqual(dependency);
  expect(parsed?.affected_recipes.map((recipe) => [
    recipe.recipe_name,
    recipe.ingredient_occurrence_count,
  ])).toEqual([
    ["Published Chili", 2],
    ["Soup Draft", 1],
  ]);
  expect(publishedParentWarning(dependency)).toBe(
    "Published Chili will need to be republished.",
  );
});

test("unpublished dependencies do not produce a republish warning", () => {
  expect(publishedParentWarning({
    ...dependency,
    active_dependent_recipe_count: 1,
    affected_recipes: [dependency.affected_recipes[1]],
    total_ingredient_rows_affected: 1,
  })).toBeNull();
});

test.each([
  ["wrong code", { ...dependency, code: "wrong" }],
  ["missing projection", { ...dependency, projection_food_item_id: "" }],
  ["bad parent count", { ...dependency, active_dependent_recipe_count: 1 }],
  ["bad row total", { ...dependency, total_ingredient_rows_affected: 2 }],
  ["empty parents", { ...dependency, active_dependent_recipe_count: 0, affected_recipes: [] }],
  ["malformed parent", { ...dependency, affected_recipes: [{ recipe_id: "broken" }] }],
  [
    "ambiguous legacy republication field",
    {
      ...dependency,
      affected_recipes: dependency.affected_recipes.map((recipe) => {
        const { will_require_republish: _removed, ...legacy } = recipe;
        return { ...legacy, needs_republish: recipe.will_require_republish };
      }),
    },
  ],
])("malformed Recipe dependency response fails safely: %s", (_name, detail) => {
  expect(parseRecipeDeleteDependency(dependencyError(detail))).toBeNull();
});

test("non-dependency backend failures remain actionable during confirmation", () => {
  const error = new ApiError({
    status: 409,
    body: {
      detail: {
        code: "recipe_projection_integrity_invalid",
        message: "Republish or repair the generated food before deleting this Recipe.",
      },
    },
    message: "Request failed with status 409",
  });

  expect(parseRecipeDeleteDependency(error)).toBeNull();
  expect(recipeDeleteErrorMessage(error)).toBe(
    "Republish or repair the generated food before deleting this Recipe.",
  );
  expect(recipeDeleteErrorMessage(new Error("offline"))).toBe("Could not delete Recipe.");
});

test("Recipe delete API distinguishes initial and explicitly confirmed requests", async () => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 204 });

  await deleteRecipe({ recipeId: "child-recipe" });
  await deleteRecipe({ recipeId: "child-recipe", removeFromRecipes: true });

  expect(global.fetch).toHaveBeenNthCalledWith(
    1,
    "http://localhost:8000/api/v1/recipes/child-recipe",
    expect.objectContaining({ method: "DELETE" }),
  );
  expect(global.fetch).toHaveBeenNthCalledWith(
    2,
    "http://localhost:8000/api/v1/recipes/child-recipe?remove_from_recipes=true",
    expect.objectContaining({ method: "DELETE" }),
  );
});
