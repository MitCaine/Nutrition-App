import { deleteLog, getDailySummary, getLogEditContext, markDayComplete, updateLog } from "../src/features/logging/api/logApi";

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

test("log delete API sends the replay and calendar context", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 204,
    text: async () => "",
  });

  await deleteLog("log-1", {
    client_request_id: "request-1",
    expected_updated_at: "2026-07-08T09:00:00Z",
    calendar_revision: 4,
  });

  expect(global.fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/logs/log-1",
    expect.objectContaining({
      method: "DELETE",
      body: JSON.stringify({
        client_request_id: "request-1",
        expected_updated_at: "2026-07-08T09:00:00Z",
        calendar_revision: 4,
      }),
    }),
  );
});

test("mark Complete API sends exact deterministic intent", async () => {
  const result = {
    logged_date: "2026-08-18",
    completed_at: "2026-08-18T20:00:00.000000Z",
  };
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => result,
  });
  const input = {
    client_request_id: "22222222-2222-4222-8222-222222222222",
    calendar_revision: 4,
    logged_date: "2026-08-18",
  };

  await expect(markDayComplete(input)).resolves.toEqual(result);
  expect(global.fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/logs/complete",
    expect.objectContaining({ method: "POST", body: JSON.stringify(input) }),
  );
});

test("log edit context API returns immutable revision amount choices", async () => {
  const context = {
    log_id: "log-1",
    source_food_available: false,
    is_revision_backed: true,
    recipe_publication_revision_id: "revision-1",
    selected_amount_definition_id: "amount-1",
    amount_choices: [
      {
        amount_definition_id: "amount-1",
        display_label: "1 serving",
        semantic_mode: "serving",
        display_quantity: "1",
        display_unit: "serving",
        gram_equivalent: "120",
        is_default: true,
        is_selected: true,
      },
    ],
  };
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => context,
  });

  await expect(getLogEditContext("log-1")).resolves.toEqual(context);
  expect(global.fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/v1/logs/log-1/edit-context",
    expect.any(Object),
  );
});
