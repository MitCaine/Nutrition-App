import {
  deleteLog,
  getDailySummary,
  getLogEditContext,
  getLogMutationStatus,
  listLogs,
  listRecentEntries,
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

function recentEntryResponse() {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    food_item_id: "22222222-2222-4222-8222-222222222222",
    food_name_snapshot: "Historical Food",
    logged_date: "2026-07-08",
    meal_type: "legacy_supper",
    amount_quantity: "0001.5000",
    amount_unit: "serving" as const,
    serving_definition_id:
      "33333333-3333-4333-8333-333333333333",
    recipe_publication_revision_id: null,
    recipe_publication_amount_definition_id: null,
    historical_serving_label: "1 serving",
    notes: null,
    note_present: false,
    note_reference: null,
    note_copy_allowed: false,
    created_at: "2026-07-08T09:00:00Z",
    source_food_updated_at:
      "2026-07-08T08:00:00Z",
    source_recipe_publication_revision_id: null,
    current_source_loggable: true,
    current_amount_unit: "serving" as const,
    current_amount_definition_id:
      "33333333-3333-4333-8333-333333333333",
    current_amount_label: "1 serving",
    reuse_status: "exact" as const,
  };
}

function editAmountResponse() {
  return {
    amount_definition_id:
      "44444444-4444-4444-8444-444444444444",
    display_label: "1 serving",
    semantic_mode: "serving" as const,
    display_quantity: "1.000000",
    display_unit: "serving",
    gram_equivalent: "120.000000",
    is_default: true,
    is_selected: true,
  };
}

function editContextResponse() {
  return {
    log_id:
      "55555555-5555-4555-8555-555555555555",
    source_food_available: false,
    is_revision_backed: true,
    recipe_publication_revision_id:
      "66666666-6666-4666-8666-666666666666",
    selected_amount_definition_id:
      "44444444-4444-4444-8444-444444444444",
    amount_choices: [
      editAmountResponse(),
    ],
  };
}

test(
  "Recent Entries validates complete canonical historical intent",
  async () => {
    const entry = recentEntryResponse();

    mockSuccessfulJson({
      entries: [entry],
    });

    await expect(
      listRecentEntries(),
    ).resolves.toEqual([entry]);
  },
);

const malformedRecentEntryCases: Array<[
  string,
  () => unknown,
]> = [
  [
    "missing backend field",
    () => {
      const value =
        recentEntryResponse() as
        Record<string, unknown>;

      delete value.source_food_updated_at;

      return {
        entries: [value],
      };
    },
  ],
  [
    "invalid Food UUID",
    () => ({
      entries: [
        {
          ...recentEntryResponse(),
          food_item_id: "food-1",
        },
      ],
    }),
  ],
  [
    "numeric exact decimal",
    () => ({
      entries: [
        {
          ...recentEntryResponse(),
          amount_quantity: 1.5,
        },
      ],
    }),
  ],
  [
    "invalid amount unit",
    () => ({
      entries: [
        {
          ...recentEntryResponse(),
          amount_unit: "oz",
        },
      ],
    }),
  ],
  [
    "invalid timestamp",
    () => ({
      entries: [
        {
          ...recentEntryResponse(),
          created_at: "2026-07-08T09:00:00",
        },
      ],
    }),
  ],
  [
    "unexpected nested field",
    () => ({
      entries: [
        {
          ...recentEntryResponse(),
          unexpected: true,
        },
      ],
    }),
  ],
];

test.each(
  malformedRecentEntryCases,
)(
  "Recent Entries rejects %s",
  async (_name, buildResponse) => {
    mockSuccessfulJson(
      buildResponse(),
    );

    await expect(
      listRecentEntries(),
    ).rejects.toThrow();
  },
);

test(
  "log edit context accepts the deliberate five-field omission form",
  async () => {
    const context =
      editContextResponse();

    mockSuccessfulJson(context);

    await expect(
      getLogEditContext("log-1"),
    ).resolves.toEqual(context);

    expect(global.fetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/logs/log-1/edit-context",
      expect.any(Object),
    );
  },
);

test(
  "log edit context accepts all five current authority fields when present",
  async () => {
    const currentAmount =
      editAmountResponse();

    const context = {
      ...editContextResponse(),
      current_source_food_updated_at:
        "2026-07-08T10:00:00Z",
      current_recipe_publication_revision_id:
        "77777777-7777-4777-8777-777777777777",
      current_source_loggable: true,
      current_selected_amount_definition_id:
        currentAmount.amount_definition_id,
      current_amount_choices: [
        currentAmount,
      ],
    };

    mockSuccessfulJson(context);

    await expect(
      getLogEditContext("log-1"),
    ).resolves.toEqual(context);
  },
);

const malformedEditContextCases: Array<[
  string,
  () => unknown,
]> = [
  [
    "missing required base field",
    () => {
      const value =
        editContextResponse() as
        Record<string, unknown>;

      delete value.amount_choices;

      return value;
    },
  ],
  [
    "invalid log UUID",
    () => ({
      ...editContextResponse(),
      log_id: "log-1",
    }),
  ],
  [
    "numeric display decimal",
    () => ({
      ...editContextResponse(),
      amount_choices: [
        {
          ...editAmountResponse(),
          display_quantity: 1,
        },
      ],
    }),
  ],
  [
    "present null current timestamp",
    () => ({
      ...editContextResponse(),
      current_source_food_updated_at:
        null,
    }),
  ],
  [
    "present null current loggable flag",
    () => ({
      ...editContextResponse(),
      current_source_loggable:
        null,
    }),
  ],
  [
    "unexpected field",
    () => ({
      ...editContextResponse(),
      unexpected: true,
    }),
  ],
];

test.each(
  malformedEditContextCases,
)(
  "Log edit context rejects %s",
  async (_name, buildResponse) => {
    mockSuccessfulJson(
      buildResponse(),
    );

    await expect(
      getLogEditContext("log-1"),
    ).rejects.toThrow();
  },
);
