import { logEditErrorMessage } from "../src/features/logging/utils/logEditErrors";
import { ApiError } from "../src/shared/api/client";

test("structured deleted-source conflict returns the backend message", () => {
  const error = new ApiError({
    status: 409,
    body: {
      detail: {
        code: "source_food_deleted",
        message: "This historical entry cannot be edited because its source food was deleted.",
      },
    },
    message: "Request failed with status 409",
  });

  expect(logEditErrorMessage(error)).toBe(
    "This historical entry cannot be edited because its source food was deleted.",
  );
});

test("log edit errors use useful API messages and safe fallbacks", () => {
  expect(logEditErrorMessage(new ApiError({ status: 500, body: null, message: "Server unavailable" }))).toBe(
    "Server unavailable",
  );
  expect(logEditErrorMessage(new Error("network"))).toBe("Could not save changes.");
});

test.each([
  "recipe_log_revision_missing",
  "recipe_log_amount_definition_missing",
  "recipe_log_serving_not_in_revision",
  "recipe_log_conversion_unsupported",
  "recipe_log_nutrient_basis_ambiguous",
  "recipe_log_nutrition_invalid",
])("structured %s validation returns the backend message", (code) => {
  const error = new ApiError({
    status: 400,
    body: { detail: { code, message: `Actionable ${code}` } },
    message: "Request failed with status 400",
  });

  expect(logEditErrorMessage(error)).toBe(`Actionable ${code}`);
});
