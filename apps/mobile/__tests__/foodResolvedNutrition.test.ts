import { getFoodResolvedNutrition } from "../src/features/foods/api/foodApi";

test("Food Detail resolved nutrition API preserves count-only and nutrient status data", async () => {
  const response = {
    amounts: [
      {
        amount_definition_id: "serving-1",
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
