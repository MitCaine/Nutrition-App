import { getDailySummary, updateLog } from "../src/features/logging/api/logApi";

test("daily summary API mapping converts snake case totals to mobile shape", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      logged_date: "2026-07-08",
      totals: [
        {
          nutrient_id: "protein",
          amount_known: "10",
          amount_estimated: "2",
          unit: "g",
          has_unknown_contributors: true,
          unknown_contributor_count: 1,
        },
      ],
    }),
  });

  await expect(getDailySummary("2026-07-08")).resolves.toEqual({
    logged_date: "2026-07-08",
    totals: [
      {
        nutrientId: "protein",
        amountKnown: "10",
        amountEstimated: "2",
        unit: "g",
        hasUnknownContributors: true,
        unknownContributorCount: 1,
      },
    ],
  });
});

test("log update API sends PATCH payload", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      id: "log-1",
      food_item_id: "food-1",
      logged_date: "2026-07-08",
      amount_quantity: "2",
      amount_unit: "g",
    }),
  });

  await updateLog("log-1", {
    logged_date: "2026-07-08",
    amount_quantity: "2",
    amount_unit: "g",
  });

  expect(global.fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/logs/log-1",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({
        logged_date: "2026-07-08",
        amount_quantity: "2",
        amount_unit: "g",
      }),
    }),
  );
});
