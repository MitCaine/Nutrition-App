import {
  deleteLog,
  getDailySummary,
  getLogEditContext,
  getLogMutationStatus,
  listLogs,
  markDayComplete,
  updateLog,
} from "../src/features/logging/api/logApi";

function dailyLogResponse() {
  return {
    id: "00000000-0000-4000-8000-000000000101",
    food_item_id: "00000000-0000-4000-8000-000000000102",
    food_name_snapshot: "Food",
    is_editable: true,
    source_food_available: true,
    edit_block_reason: null,
    logged_date: "2026-07-08",
    meal_type: null,
    amount_quantity: "2.000000",
    amount_unit: "g",
    serving_definition_id: null,
    gram_amount: "2.000000",
    package_fraction: null,
    notes: null,
    created_at: "2026-07-08T09:00:00Z",
    updated_at: "2026-07-08T09:00:00Z",
    snapshots: [{
      id: "00000000-0000-4000-8000-000000000103",
      nutrient_id: "protein",
      amount: "1.230000",
      unit: "g",
      data_status: "known",
      source_food_item_id: "00000000-0000-4000-8000-000000000102",
      source_food_nutrient_id: "00000000-0000-4000-8000-000000000104",
      serving_definition_id: null,
      consumed_amount_quantity: "2.000000",
      consumed_amount_unit: "g",
      consumed_gram_amount: "2.000000",
      consumed_package_fraction: null,
    }],
  };
}

function dailySummaryResponse() {
  return {
    logged_date: "2026-07-08",
    is_complete: false,
    totals: [{
      nutrient_id: "protein",
      amount_known: "00010.5000",
      amount_estimated: "2.000000",
      unit: "g" as const,
      has_unknown_contributors: true,
      unknown_contributor_count: 1,
    }],
  };
}

function mockSuccessfulJson(value: unknown): void {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => value,
  });
}

test("daily summary API mapping converts snake case totals to mobile shape", async () => {
  mockSuccessfulJson(dailySummaryResponse());

  await expect(getDailySummary("2026-07-08")).resolves.toEqual({
    logged_date: "2026-07-08",
    is_complete: false,
    totals: [
      {
        nutrientId: "protein",
        amountKnown: "00010.5000",
        amountEstimated: "2.000000",
        unit: "g",
        hasUnknownContributors: true,
        unknownContributorCount: 1,
      },
    ],
  });
});

const malformedDailySummaryCases: Array<[
  string,
  (value: ReturnType<typeof dailySummaryResponse>) => unknown,
]> = [
  ["missing required top-level field", ({ is_complete: _complete, ...value }) => value],
  ["wrong top-level primitive", () => []],
  ["malformed nested array item", (value) => ({ ...value, totals: [null] })],
  ["decimal supplied as a JSON number", (value) => ({
    ...value,
    totals: [{ ...value.totals[0], amount_estimated: 2 }],
  })],
  ["invalid decimal text", (value) => ({
    ...value,
    totals: [{ ...value.totals[0], amount_known: "Infinity" }],
  })],
  ["wrong finite nutrient unit", (value) => ({
    ...value,
    totals: [{ ...value.totals[0], unit: "oz" }],
  })],
  ["null date mismatch", (value) => ({ ...value, logged_date: null })],
  ["non-integer contributor count", (value) => ({
    ...value,
    totals: [{ ...value.totals[0], unknown_contributor_count: 1.5 }],
  })],
  ["unexpected field", (value) => ({ ...value, unexpected: true })],
];

test.each(malformedDailySummaryCases)("Daily Summary rejects %s", async (_label, mutate) => {
  mockSuccessfulJson(mutate(dailySummaryResponse()));
  await expect(getDailySummary("2026-07-08")).rejects.toThrow();
});

test("log update API sends PATCH payload", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => dailyLogResponse(),
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

test("Daily Log list validates the strict wrapper and nested logs", async () => {
  mockSuccessfulJson({ logs: [dailyLogResponse()] });
  await expect(listLogs("2026-07-08")).resolves.toEqual([dailyLogResponse()]);
});

test("Daily Log list rejects unexpected wrapper fields", async () => {
  mockSuccessfulJson({ logs: [dailyLogResponse()], unexpected: true });
  await expect(listLogs("2026-07-08")).rejects.toThrow();
});

test("ordinary Daily Log validation preserves exact strings and readable legacy meals", async () => {
  mockSuccessfulJson({
    ...dailyLogResponse(),
    meal_type: "legacy_supper",
    amount_quantity: "0002.5000",
  });

  await expect(updateLog("log-1", {
    logged_date: "2026-07-08",
    amount_quantity: "2",
    amount_unit: "g",
  })).resolves.toMatchObject({
    meal_type: "legacy_supper",
    amount_quantity: "0002.5000",
  });
});

const malformedDailyLogCases: Array<[
  string,
  (value: ReturnType<typeof dailyLogResponse>) => unknown,
]> = [
  ["missing required top-level field", ({ id: _id, ...value }) => value],
  ["wrong top-level primitive", () => 42],
  ["malformed nested object", (value) => ({ ...value, snapshots: [null] })],
  ["malformed nested array item", (value) => ({ ...value, snapshots: ["bad"] })],
  ["decimal supplied as a JSON number", (value) => ({ ...value, amount_quantity: 2 })],
  ["invalid decimal text", (value) => ({ ...value, gram_amount: "NaN" })],
  ["overlong decimal text", (value) => ({ ...value, gram_amount: "1".repeat(129) })],
  ["wrong finite amount unit", (value) => ({ ...value, amount_unit: "oz" })],
  ["wrong finite nutrient unit", (value) => ({
    ...value,
    snapshots: [{ ...value.snapshots[0], unit: "oz" }],
  })],
  ["null UUID mismatch", (value) => ({ ...value, id: null })],
  ["invalid nested UUID", (value) => ({
    ...value,
    snapshots: [{ ...value.snapshots[0], id: "snapshot-1" }],
  })],
  ["invalid date-only text", (value) => ({ ...value, logged_date: "2026-02-30" })],
  ["unexpected top-level field", (value) => ({ ...value, unexpected: true })],
  ["unexpected nested field", (value) => ({
    ...value,
    snapshots: [{ ...value.snapshots[0], unexpected: true }],
  })],
];

test.each(malformedDailyLogCases)("ordinary Daily Log rejects %s", async (_label, mutate) => {
  mockSuccessfulJson(mutate(dailyLogResponse()));

  await expect(updateLog("log-1", {
    logged_date: "2026-07-08",
    amount_quantity: "2",
    amount_unit: "g",
  })).rejects.toThrow();
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

const malformedCompleteCases: Array<[
  string,
  (value: { logged_date: string; completed_at: string }) => unknown,
]> = [
  ["missing required top-level field", ({ logged_date: _date, ...value }) => value],
  ["wrong top-level primitive", () => false],
  ["invalid date-only text", (value) => ({ ...value, logged_date: "2026-02-30" })],
  ["wrong timestamp primitive", (value) => ({ ...value, completed_at: 123 })],
  ["timestamp without an offset", (value) => ({
    ...value,
    completed_at: "2026-08-18T20:00:00",
  })],
  ["null mismatch", (value) => ({ ...value, completed_at: null })],
  ["unexpected field", (value) => ({ ...value, unexpected: true })],
];

test.each(malformedCompleteCases)("Complete response rejects %s", async (_label, mutate) => {
  mockSuccessfulJson(mutate({
    logged_date: "2026-08-18",
    completed_at: "2026-08-18T20:00:00.000000Z",
  }));

  await expect(markDayComplete({
    client_request_id: "22222222-2222-4222-8222-222222222222",
    calendar_revision: 4,
    logged_date: "2026-08-18",
  })).rejects.toThrow();
});

test("mutation status rejects a malformed nested Complete result", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      operation: "complete",
      client_request_id: "00000000-0000-4000-8000-000000000201",
      status: "confirmed_success",
      log_id: null,
      source_logged_date: null,
      destination_logged_date: "2026-08-18",
      result: null,
      completion: {
        logged_date: "2026-08-18",
        completed_at: false,
      },
    }),
  });

  await expect(getLogMutationStatus(
    "00000000-0000-4000-8000-000000000201",
    "complete",
  )).rejects.toThrow();
});

test("mutation status validates and returns the canonical Complete result", async () => {
  const status = {
    operation: "complete",
    client_request_id: "00000000-0000-4000-8000-000000000201",
    status: "confirmed_success",
    log_id: null,
    source_logged_date: null,
    destination_logged_date: "2026-08-18",
    result: null,
    completion: {
      logged_date: "2026-08-18",
      completed_at: "2026-08-18T20:00:00.000000Z",
    },
  };
  mockSuccessfulJson(status);

  await expect(getLogMutationStatus(
    "00000000-0000-4000-8000-000000000201",
    "complete",
  )).resolves.toEqual(status);
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
