import { getFoodResolvedNutrition } from "../src/features/foods/api/foodApi";

test("Food Detail resolved nutrition API preserves count-only and nutrient status data", async () => {
  const response = {
    nutrition_authority: "food_item" as const,
    recipe_id: null,
    recipe_publication_revision_id: null,
    amounts: [
      {
        amount_definition_id: "22222222-2222-4222-8222-222222222222",
        display_label: "1 serving",
        is_default: true,
        entered_quantity: "1.000000",
        semantic_amount_mode: "serving" as const,
        resolved_grams: null,
        valid_for_logging: true,
        nutrients: [
          {
            nutrient_id: "calories",
            amount: "120.000000",
            unit: "kcal" as const,
            data_status: "estimated" as const,
            source_basis: "per_serving" as const,
          },
          {
            nutrient_id: "vitamin_d",
            amount: null,
            unit: "mcg" as const,
            data_status: "unknown" as const,
            source_basis: "per_serving" as const,
          },
        ],
      },
    ],
  };
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => response,
  });

  await expect(getFoodResolvedNutrition("food-1")).resolves.toEqual(response);
  expect(global.fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/foods/food-1/resolved-nutrition",
    expect.objectContaining({ headers: expect.objectContaining({ "Content-Type": "application/json" }) }),
  );
});

test("Food Detail maps revision-backed published nutrition and immutable amounts", async () => {
  const response = {
    nutrition_authority: "recipe_publication_revision" as const,
    recipe_id: "44444444-4444-4444-8444-444444444444",
    recipe_publication_revision_id: "55555555-5555-4555-8555-555555555555",
    amounts: [
      {
        amount_definition_id: "66666666-6666-4666-8666-666666666666",
        display_label: "1 serving",
        is_default: true,
        entered_quantity: "1.000000",
        semantic_amount_mode: "serving" as const,
        resolved_grams: "125.000000",
        valid_for_logging: true,
        nutrients: [
          {
            nutrient_id: "protein",
            amount: "8.500000",
            unit: "g" as const,
            data_status: "known" as const,
            source_basis: "per_serving" as const,
          },
        ],
      },
    ],
  };
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => response,
  });

  await expect(getFoodResolvedNutrition("recipe-food")).resolves.toEqual(response);
});
