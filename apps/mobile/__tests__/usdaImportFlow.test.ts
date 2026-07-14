import { QueryClient } from "@tanstack/react-query";

import type { Food } from "../src/features/foods/api/types";
import { applyUsdaImportToFoodCache } from "../src/features/usda/hooks/useUsda";
import { importUsdaFood } from "../src/features/usda/api/usdaApi";
import { buildLogInput, initialServingId } from "../src/features/logging/utils/logFoodForm";
import { createLog, getDailySummary } from "../src/features/logging/api/logApi";
import { invalidateLogDateCaches } from "../src/features/logging/hooks/useLogs";

const importedFood: Food = {
  id: "food-usda",
  name: "Example Protein Bar",
  brand: "Example Foods",
  source_type: "usda",
  source_id: "555000",
  is_recipe: false,
  serving_definitions: [
    {
      id: "serving-100g",
      label: "100 g",
      quantity: "100",
      unit: "g",
      gram_weight: "100.000000",
      is_default: false,
      source: "usda_fdc",
      is_user_confirmed: false,
    },
    {
      id: "serving-bar",
      label: "1 bar",
      quantity: "50",
      unit: "g",
      gram_weight: "50.000000",
      is_default: true,
      source: "usda_fdc",
      is_user_confirmed: false,
    },
  ],
  nutrients: [
    {
      id: "nutrient-calories",
      nutrient_id: "calories",
      amount: "300.000000",
      unit: "kcal",
      basis: "per_100g",
      data_status: "known",
      source: "usda_fdc",
      is_user_confirmed: false,
    },
    {
      id: "nutrient-cholesterol",
      nutrient_id: "cholesterol",
      amount: "0.000000",
      unit: "mg",
      basis: "per_100g",
      data_status: "zero",
      source: "usda_fdc",
      is_user_confirmed: false,
    },
    {
      id: "nutrient-vitamin-d",
      nutrient_id: "vitamin_d",
      amount: null,
      unit: "mcg",
      basis: "per_100g",
      data_status: "unknown",
      source: "usda_fdc",
      is_user_confirmed: false,
    },
  ],
};

test("USDA import seeds food detail cache for immediate post-import navigation", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 201,
    json: async () => importedFood,
  });
  const queryClient = new QueryClient();

  const food = await importUsdaFood(555000);
  applyUsdaImportToFoodCache(queryClient, food);

  expect(global.fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/usda/foods/555000/import",
    expect.objectContaining({ method: "POST" }),
  );
  expect(queryClient.getQueryData(["foods", "food-usda"])).toEqual(importedFood);
  queryClient.clear();
});

test("duplicate USDA import response reuses existing food in the same cache path", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => importedFood,
  });
  const queryClient = new QueryClient();

  const food = await importUsdaFood(555000);
  applyUsdaImportToFoodCache(queryClient, food);

  expect(food.id).toBe("food-usda");
  expect(queryClient.getQueryData(["foods", "food-usda"])).toEqual(importedFood);
  queryClient.clear();
});

test("USDA import failure rejects without seeding food detail cache", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    status: 503,
    text: async () => "USDA search is unavailable",
  });
  const queryClient = new QueryClient();

  await expect(importUsdaFood(555000)).rejects.toThrow("USDA search is unavailable");

  expect(queryClient.getQueryData(["foods", "food-usda"])).toBeUndefined();
  queryClient.clear();
});

test("imported USDA food can be logged with default serving and refreshes daily totals", async () => {
  global.fetch = jest
    .fn()
    .mockResolvedValueOnce({
      ok: true,
      status: 201,
      json: async () => ({
        id: "log-1",
        food_item_id: "food-usda",
        logged_date: "2026-07-08",
        amount_quantity: "1",
        amount_unit: "serving",
        serving_definition_id: "serving-bar",
      }),
    })
    .mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        logged_date: "2026-07-08",
        totals: [
          {
            nutrient_id: "calories",
            amount_known: "150.000000",
            amount_estimated: "0",
            unit: "kcal",
            has_unknown_contributors: false,
            unknown_contributor_count: 0,
          },
          {
            nutrient_id: "vitamin_d",
            amount_known: "0",
            amount_estimated: "0",
            unit: "mcg",
            has_unknown_contributors: true,
            unknown_contributor_count: 1,
          },
        ],
      }),
    });
  const queryClient = new QueryClient();
  queryClient.setQueryData(["logs", "2026-07-08"], []);
  queryClient.setQueryData(["daily-summary", "2026-07-08"], { logged_date: "2026-07-08", totals: [] });

  const input = buildLogInput({
    foodId: importedFood.id,
    date: "2026-07-08",
    amount: "1",
    unit: "serving",
    selectedServingId: initialServingId(importedFood),
  });
  await createLog({
    ...input,
    client_request_id: "00000000-0000-4000-8000-000000000001",
  });
  invalidateLogDateCaches(queryClient, "2026-07-08");
  const summary = await getDailySummary("2026-07-08");

  expect(JSON.parse((global.fetch as jest.Mock).mock.calls[0][1].body)).toEqual({
    client_request_id: "00000000-0000-4000-8000-000000000001",
    food_item_id: "food-usda",
    logged_date: "2026-07-08",
    amount_quantity: "1",
    amount_unit: "serving",
    serving_definition_id: "serving-bar",
  });
  expect(queryClient.getQueryState(["logs", "2026-07-08"])?.isInvalidated).toBe(true);
  expect(queryClient.getQueryState(["daily-summary", "2026-07-08"])?.isInvalidated).toBe(true);
  expect(summary.totals).toEqual([
    {
      nutrientId: "calories",
      amountKnown: "150.000000",
      amountEstimated: "0",
      unit: "kcal",
      hasUnknownContributors: false,
      unknownContributorCount: 0,
    },
    {
      nutrientId: "vitamin_d",
      amountKnown: "0",
      amountEstimated: "0",
      unit: "mcg",
      hasUnknownContributors: true,
      unknownContributorCount: 1,
    },
  ]);
  queryClient.clear();
});
