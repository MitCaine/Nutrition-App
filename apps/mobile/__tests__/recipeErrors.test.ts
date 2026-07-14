import { recipeApiErrorMessage } from "../src/features/recipes/utils/recipeErrors";

test("extracts concise FastAPI validation messages", () => {
  expect(
    recipeApiErrorMessage(
      new Error(JSON.stringify({ detail: [{ msg: "serving ingredients must not include mass display metadata" }] })),
    ),
  ).toBe("Serving ingredients cannot contain mass-unit information.");
  expect(
    recipeApiErrorMessage(
      new Error(JSON.stringify({ detail: [{ msg: "Value error, ingredient amount_quantity must be greater than zero" }] })),
    ),
  ).toBe("Ingredient amount must be greater than zero.");
});

test("falls back for unusable errors", () => {
  expect(recipeApiErrorMessage(new Error("{not json"))).toBe("Could not save recipe.");
  expect(recipeApiErrorMessage("bad")).toBe("Could not save recipe.");
});

test("shows actionable structured Recipe graph conflicts", () => {
  expect(
    recipeApiErrorMessage(
      new Error(
        JSON.stringify({
          detail: {
            code: "recipe_graph_cycle_conflict",
            message:
              "This ingredient change would create a circular Recipe dependency. Remove the circular Recipe ingredient and try again.",
          },
        }),
      ),
    ),
  ).toBe(
    "This ingredient change would create a circular Recipe dependency. Remove the circular Recipe ingredient and try again.",
  );
});
