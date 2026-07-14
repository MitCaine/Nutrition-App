import { DARK_THEME, LIGHT_THEME } from "../src/app/theme/AppTheme";
import {
  recipeNutrientValueColor,
  recipeNutritionErrorMessage,
  visibleRecipeNutrition,
} from "../src/features/recipes/utils/recipeNutritionPreview";
import { ApiError } from "../src/shared/api/client";
import type { RecipeNutritionResponse } from "../src/features/recipes/api/types";

const validationError = new ApiError({
  status: 400,
  body: {
    detail: {
      code: "ingredient_serving_missing_gram_weight",
      message: "Cannot calculate nutrition for Bread because the serving '1 slice' has no gram weight.",
      food_name: "Bread",
      serving_label: "1 slice",
    },
  },
  message: "Request failed with status 400",
});

test("preview displays the backend-owned structured validation message", () => {
  expect(recipeNutritionErrorMessage(validationError, "Could not load nutrition preview.")).toBe(
    "Cannot calculate nutrition for Bread because the serving '1 slice' has no gram weight.",
  );
});

test("publish displays the same backend-owned validation message", () => {
  expect(recipeNutritionErrorMessage(validationError, "Could not publish recipe.")).toBe(
    recipeNutritionErrorMessage(validationError, "Could not load nutrition preview."),
  );
});

test.each([
  [
    "recipe_publication_parent_amount_conflict",
    "Update parent Recipe ingredient amounts before republishing.",
  ],
  [
    "recipe_publication_dependencies_unstable",
    "Try again when parent Recipe edits are complete.",
  ],
])("publication conflict %s displays its actionable detail message", (code, message) => {
  const error = new ApiError({
    status: 409,
    body: { detail: { code, message } },
    message,
  });
  expect(recipeNutritionErrorMessage(error, "Could not publish recipe.")).toBe(message);
});

test("unstructured errors retain the caller's generic fallback", () => {
  expect(
    recipeNutritionErrorMessage(
      new ApiError({ status: 500, body: null, message: "Internal Server Error" }),
      "Could not load nutrition preview.",
    ),
  ).toBe("Could not load nutrition preview.");
  expect(recipeNutritionErrorMessage(new Error("network"), "Could not publish recipe.")).toBe(
    "Could not publish recipe.",
  );
});

test("failed refresh hides previously cached nutrition totals", () => {
  const cached: RecipeNutritionResponse = {
    totals: [
      {
        nutrientId: "protein",
        amountKnown: "10",
        amountEstimated: "0",
        unit: "g",
        hasUnknownContributors: false,
        unknownContributorCount: 0,
      },
    ],
    perServing: null,
    per100g: null,
  };

  expect(visibleRecipeNutrition(cached, false)).toBe(cached);
  expect(visibleRecipeNutrition(cached, true)).toBeUndefined();
});

test("nutrient values use each theme's primary foreground color", () => {
  expect(recipeNutrientValueColor(LIGHT_THEME)).toBe(LIGHT_THEME.colors.text);
  expect(recipeNutrientValueColor(DARK_THEME)).toBe(DARK_THEME.colors.text);
  expect(recipeNutrientValueColor(DARK_THEME)).not.toBe("#000000");
});
