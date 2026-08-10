import { QueryClient } from "@tanstack/react-query";

import type { DailyLog, DailyLogMutationStatus } from "../src/features/logging/api/types";
import {
  createLogMutationRecoveryRecord as createRecoveryRecordWithDisplayContext,
  loadLogMutationRecoveryJournal as loadRecoveryJournalWithAuthority,
  reconcileLogMutationRecoveryRecord as reconcileRecoveryWithDependencies,
  persistRecoveryBeforeTransmission,
  dismissLogMutationRecoveryRecord,
  getRecoveryJournalState,
  hasOverlappingRecovery,
  removeLogMutationRecoveryRecord,
  recoveryActionableState,
  startLogMutationRecovery as startRecoveryWithDependencies,
  upsertLogMutationRecoveryRecord,
  type RecoveryStorage,
} from "../src/features/logging/recovery/logMutationRecovery";
import { remoteNutritionRuntime } from "../src/runtime/remote/remoteNutritionRuntime";
import { localAuthorityIdentity } from "../src/runtime/authorityIdentity";

const TEST_AUTHORITY = remoteNutritionRuntime.authority;
const TEST_RECOVERY_DEPENDENCIES = {
  authority: TEST_AUTHORITY,
  dailyLogs: remoteNutritionRuntime.dailyLogs,
};

type RecoveryRecordInput = Parameters<typeof createRecoveryRecordWithDisplayContext>[0];

function createLogMutationRecoveryRecord(
  input: Omit<RecoveryRecordInput, "authority" | "displayContext"> & Pick<Partial<RecoveryRecordInput>, "displayContext">,
) {
  return createRecoveryRecordWithDisplayContext({
    ...input,
    authority: TEST_AUTHORITY,
    displayContext: input.displayContext ?? {
      item_name: "Test food",
      amount_label: "1 serving",
      meal_label: "Breakfast",
    },
  });
}

function loadLogMutationRecoveryJournal(storage: RecoveryStorage) {
  return loadRecoveryJournalWithAuthority(TEST_AUTHORITY, storage);
}

function reconcileLogMutationRecoveryRecord(
  record: Parameters<typeof reconcileRecoveryWithDependencies>[0],
  queryClient: Parameters<typeof reconcileRecoveryWithDependencies>[1],
  options: Parameters<typeof reconcileRecoveryWithDependencies>[3] = {},
) {
  return reconcileRecoveryWithDependencies(record, queryClient, TEST_RECOVERY_DEPENDENCIES, options);
}

function startLogMutationRecovery(
  queryClient: Parameters<typeof startRecoveryWithDependencies>[0],
  options: Parameters<typeof startRecoveryWithDependencies>[2] = {},
) {
  return startRecoveryWithDependencies(queryClient, TEST_RECOVERY_DEPENDENCIES, options);
}

const queryClients = new Set<QueryClient>();

function trackedQueryClient(): QueryClient {
  const client = new QueryClient();
  queryClients.add(client);
  return client;
}

afterEach(() => {
  for (const client of queryClients) client.clear();
  queryClients.clear();
});

function memoryStorage(initial?: string): RecoveryStorage & { value: string | null } {
  const state = { value: initial ?? null };
  return {
    get value() { return state.value; },
    set value(next: string | null) { state.value = next; },
    getItem: jest.fn(async () => state.value),
    setItem: jest.fn(async (_key: string, value: string) => { state.value = value; }),
    removeItem: jest.fn(async () => { state.value = null; }),
  };
}

function log(id: string, date: string): DailyLog {
  return {
    id,
    food_item_id: "food-1",
    food_name_snapshot: id,
    meal_type: "breakfast",
    source_food_available: true,
    logged_date: date,
    amount_quantity: "1",
    amount_unit: "serving",
    notes: null,
    updated_at: "2026-07-14T08:00:00Z",
  };
}

function status(
  record: ReturnType<typeof createLogMutationRecoveryRecord>,
  overrides: Partial<DailyLogMutationStatus> = {},
): DailyLogMutationStatus {
  return {
    operation: record.mutation_type === "delete" ? "delete" : record.mutation_type === "create" ? "create" : "update",
    client_request_id: record.client_request_id,
    status: "confirmed_success",
    log_id: record.target_id,
    result: null,
    ...overrides,
  };
}

test("journal persists only versioned recovery intent and preserves ordering", async () => {
  const storage = memoryStorage();
  const later = createLogMutationRecoveryRecord({
    clientRequestId: "later",
    mutationType: "edit",
    logId: "log-2",
    sourceDate: "2026-07-14",
    createdAt: "2026-07-14T00:00:02.000Z",
  });
  const earlier = createLogMutationRecoveryRecord({
    clientRequestId: "earlier",
    mutationType: "create",
    sourceDate: "2026-07-14",
    createdAt: "2026-07-14T00:00:01.000Z",
  });

  await upsertLogMutationRecoveryRecord(later, storage);
  await upsertLogMutationRecoveryRecord(earlier, storage);

  const records = await loadLogMutationRecoveryJournal(storage);
  expect(records.map((record) => record.client_request_id)).toEqual(["earlier", "later"]);
  expect(JSON.parse(storage.value as string)).toEqual({
    version: 2,
    records: expect.arrayContaining([
      expect.objectContaining({ client_request_id: "earlier", mutation_type: "create" }),
      expect.objectContaining({ client_request_id: "later", mutation_type: "edit" }),
    ]),
  });

  await removeLogMutationRecoveryRecord(earlier, storage);
  expect((await loadLogMutationRecoveryJournal(storage)).map((record) => record.client_request_id)).toEqual(["later"]);
});

test("new recovery records durably preserve immutable user-facing display context", async () => {
  const storage = memoryStorage();
  const displayContext = {
    item_name: "Oatmeal",
    amount_label: "1 serving",
    meal_label: "Breakfast",
  };
  const record = createLogMutationRecoveryRecord({
    clientRequestId: "display-context-request",
    mutationType: "delete",
    targetId: "0f887573-45e7-4ab0-9e0c-98b87e8e2ee5",
    sourceDate: "2026-07-14",
    displayContext,
  });
  displayContext.item_name = "Changed after review";

  await upsertLogMutationRecoveryRecord(record, storage);
  const stored = (await loadLogMutationRecoveryJournal(storage))[0];

  expect(stored.display_context).toEqual({
    item_name: "Oatmeal",
    amount_label: "1 serving",
    meal_label: "Breakfast",
  });
  expect(stored.payload).toEqual(record.payload);
});

test("older version-2 records load with an identifier-free display fallback", async () => {
  const current = createLogMutationRecoveryRecord({
    clientRequestId: "older-v2-request",
    mutationType: "delete",
    targetId: "opaque-log-id",
    sourceDate: "2026-07-14",
  });
  const { display_context: _displayContext, ...olderV2Record } = current;
  const storage = memoryStorage(JSON.stringify({ version: 2, records: [olderV2Record] }));

  const stored = (await loadLogMutationRecoveryJournal(storage))[0];

  expect(stored.display_context).toEqual({
    item_name: null,
    amount_label: null,
    meal_label: null,
  });
  expect(getRecoveryJournalState().ready).toBe(true);
});

async function loadRecordWithRawDisplayContext(displayContext: unknown) {
  const authoritativeRecord = createLogMutationRecoveryRecord({
    clientRequestId: "raw-display-context-request",
    mutationType: "delete",
    targetId: "opaque-log-id",
    sourceDate: "2026-07-14",
    displayContext: {
      item_name: "Original item",
      amount_label: "1 serving",
      meal_label: "Breakfast",
    },
    payload: {
      operation: "delete",
      log_id: "opaque-log-id",
      input: {
        client_request_id: "raw-display-context-request",
        expected_updated_at: "2026-07-14T08:00:00Z",
      },
    },
  });
  const storage = memoryStorage(JSON.stringify({
    version: 2,
    records: [{ ...authoritativeRecord, display_context: displayContext }],
  }));
  const [record] = await loadLogMutationRecoveryJournal(storage);
  return { authoritativeRecord, record, state: getRecoveryJournalState() };
}

test("partial display context preserves valid fields without invalidating recovery authority", async () => {
  const { authoritativeRecord, record, state } = await loadRecordWithRawDisplayContext({
    item_name: "Oatmeal",
  });

  expect(record.display_context).toEqual({
    item_name: "Oatmeal",
    amount_label: null,
    meal_label: null,
  });
  expect(record.payload).toEqual(authoritativeRecord.payload);
  expect(state).toEqual(expect.objectContaining({ ready: true, malformedRecordCount: 0 }));
});

test("invalid display fields become null while valid fields remain", async () => {
  const { record, state } = await loadRecordWithRawDisplayContext({
    item_name: 42,
    amount_label: "2 servings",
    meal_label: false,
  });

  expect(record.display_context).toEqual({
    item_name: null,
    amount_label: "2 servings",
    meal_label: null,
  });
  expect(state).toEqual(expect.objectContaining({ ready: true, malformedRecordCount: 0 }));
});

test.each(["not-an-object", ["Oatmeal"], 17])(
  "non-object display context %# normalizes to the generic fallback without a safety lock",
  async (displayContext) => {
    const { record, state } = await loadRecordWithRawDisplayContext(displayContext);

    expect(record.display_context).toEqual({
      item_name: null,
      amount_label: null,
      meal_label: null,
    });
    expect(record.target_id).toBe("opaque-log-id");
    expect(state).toEqual(expect.objectContaining({ ready: true, malformedRecordCount: 0 }));
  },
);

test("persisted overlength display context is bounded without changing recovery authority", async () => {
  const { authoritativeRecord, record, state } = await loadRecordWithRawDisplayContext({
    item_name: "x".repeat(200),
    amount_label: "y".repeat(120),
    meal_label: "Snack",
  });

  expect(Array.from(record.display_context.item_name ?? "")).toHaveLength(160);
  expect(Array.from(record.display_context.amount_label ?? "")).toHaveLength(80);
  expect(record.display_context.meal_label).toBe("Snack");
  expect(record.payload).toEqual(authoritativeRecord.payload);
  expect(record.client_request_id).toBe(authoritativeRecord.client_request_id);
  expect(state).toEqual(expect.objectContaining({ ready: true, malformedRecordCount: 0 }));
});

test("malformed authoritative fields still activate the recovery safety lock", async () => {
  const valid = createLogMutationRecoveryRecord({
    clientRequestId: "malformed-authority-request",
    mutationType: "delete",
    targetId: "opaque-log-id",
    sourceDate: "2026-07-14",
  });
  const storage = memoryStorage(JSON.stringify({
    version: 2,
    records: [{ ...valid, client_request_id: 42, display_context: { item_name: "Oatmeal" } }],
  }));

  expect(await loadLogMutationRecoveryJournal(storage)).toEqual([]);
  expect(getRecoveryJournalState()).toEqual(expect.objectContaining({
    ready: false,
    malformedRecordCount: 1,
  }));
  expect(storage.value).toContain('"client_request_id":42');
});

test("recovery display context is normalized and length-bounded at construction", () => {
  const record = createLogMutationRecoveryRecord({
    clientRequestId: "bounded-display-request",
    mutationType: "create",
    sourceDate: "2026-07-14",
    displayContext: {
      item_name: "x".repeat(200),
      amount_label: "  2\nservings  ",
      meal_label: "   ",
    },
  });

  expect(Array.from(record.display_context.item_name ?? "")).toHaveLength(160);
  expect(record.display_context.item_name?.endsWith("…")).toBe(true);
  expect(record.display_context.amount_label).toBe("2 servings");
  expect(record.display_context.meal_label).toBeNull();
});

test("prepared intent crosses a durable write barrier before it can be transmitted", async () => {
  const storage = memoryStorage();
  const record = createLogMutationRecoveryRecord({
    clientRequestId: "barrier-request",
    mutationType: "create",
    sourceDate: "2026-07-14",
    payload: {
      operation: "create",
      input: {
        client_request_id: "barrier-request",
        food_item_id: "food-1",
        logged_date: "2026-07-14",
        amount_quantity: "2",
        amount_unit: "serving",
        serving_definition_id: "serving-1",
        meal_type: "breakfast",
        notes: "exact note",
        calendar_revision: 4,
        source_food_updated_at: "2026-07-13T00:00:00Z",
      },
    },
  });
  const submitted = await persistRecoveryBeforeTransmission(record, storage);
  expect(submitted.state).toBe("submitted");
  const stored = await loadLogMutationRecoveryJournal(storage);
  expect(stored[0]).toEqual(expect.objectContaining({ state: "submitted", payload: record.payload }));
});

test("confirmed non-commit remains an exact retryable record and dismissal does not erase it", async () => {
  const storage = memoryStorage();
  const record = createLogMutationRecoveryRecord({
    clientRequestId: "non-commit-request",
    mutationType: "delete",
    targetId: "log-1",
    sourceDate: "2026-07-14",
    payload: { operation: "delete", log_id: "log-1", input: { client_request_id: "non-commit-request", expected_updated_at: "2026-07-14T08:00:00Z" } },
  });
  await upsertLogMutationRecoveryRecord({ ...record, state: "submitted" }, storage);
  const outcome = await reconcileLogMutationRecoveryRecord(record, null, {
    storage,
    statusReader: async () => status(record, { status: "confirmed_non_commit" }),
  });
  expect(outcome).toBe("retryable");
  expect((await loadLogMutationRecoveryJournal(storage))[0].state).toBe("confirmed_non_commit");
  await dismissLogMutationRecoveryRecord((await loadLogMutationRecoveryJournal(storage))[0], storage);
  expect((await loadLogMutationRecoveryJournal(storage))[0].state).toBe("dismissed");
});

test("dismissed recovery still blocks only overlapping replacements", async () => {
  const record = createLogMutationRecoveryRecord({
    clientRequestId: "dismissed-create",
    mutationType: "create",
    sourceDate: "2026-07-14",
    payload: {
      operation: "create",
      input: {
        client_request_id: "dismissed-create",
        food_item_id: "food-1",
        logged_date: "2026-07-14",
        amount_quantity: "1",
        amount_unit: "serving",
      },
    },
  });
  const dismissed = { ...record, state: "dismissed" as const, dismissed_from_state: "confirmed_non_commit" as const };
  expect(hasOverlappingRecovery([dismissed], {
    mutationType: "create",
    sourceDate: "2026-07-14",
    foodId: "food-1",
  })).toBe(dismissed);
  expect(hasOverlappingRecovery([dismissed], {
    mutationType: "create",
    sourceDate: "2026-07-14",
    foodId: "food-2",
  })).toBeNull();
});

test("prepared records are not queried automatically after restart", async () => {
  const storage = memoryStorage();
  const record = createLogMutationRecoveryRecord({
    clientRequestId: "prepared-request",
    mutationType: "create",
    sourceDate: "2026-07-14",
  });
  await upsertLogMutationRecoveryRecord(record, storage);
  const statusReader = jest.fn();
  const stop = startLogMutationRecovery(trackedQueryClient(), { storage, statusReader, retryDelayMs: 1 });
  await new Promise((resolve) => setTimeout(resolve, 10));
  stop();
  expect(statusReader).not.toHaveBeenCalled();
});

test("dismissed submitted records continue status reconciliation without resurfacing", async () => {
  const storage = memoryStorage();
  const record = createLogMutationRecoveryRecord({
    clientRequestId: "dismissed-submitted",
    mutationType: "edit",
    targetId: "log-1",
    sourceDate: "2026-07-14",
  });
  const dismissed = { ...record, state: "dismissed" as const, dismissed_from_state: "submitted" as const };
  await upsertLogMutationRecoveryRecord(dismissed, storage);
  const statusReader = jest.fn(async () => status(record, { status: "unresolved" }));
  const stop = startLogMutationRecovery(trackedQueryClient(), { storage, statusReader, retryDelayMs: 60_000 });
  await new Promise((resolve) => setTimeout(resolve, 10));
  stop();
  expect(statusReader).toHaveBeenCalledWith("dismissed-submitted", "update");
  const stored = (await loadLogMutationRecoveryJournal(storage))[0];
  expect(stored.state).toBe("dismissed");
  expect(stored.dismissed_from_state).toBe("submitted");
  expect(recoveryActionableState(stored)).toBe("submitted");
});

test("dismissed confirmed non-commit stays hidden and retryable", async () => {
  const storage = memoryStorage();
  const record = createLogMutationRecoveryRecord({
    clientRequestId: "dismissed-non-commit",
    mutationType: "delete",
    targetId: "log-1",
    sourceDate: "2026-07-14",
    payload: { operation: "delete", log_id: "log-1", input: { client_request_id: "dismissed-non-commit" } },
  });
  const dismissed = { ...record, state: "dismissed" as const, dismissed_from_state: "submitted" as const };
  await upsertLogMutationRecoveryRecord(dismissed, storage);
  const outcome = await reconcileLogMutationRecoveryRecord(dismissed, null, {
    storage,
    statusReader: async () => status(record, { status: "confirmed_non_commit" }),
  });
  expect(outcome).toBe("retryable");
  const stored = (await loadLogMutationRecoveryJournal(storage))[0];
  expect(stored.state).toBe("dismissed");
  expect(stored.dismissed_from_state).toBe("confirmed_non_commit");
});

test("dismissed confirmed success projects authority before removing the record", async () => {
  const storage = memoryStorage();
  const record = createLogMutationRecoveryRecord({
    clientRequestId: "dismissed-success",
    mutationType: "create",
    sourceDate: "2026-07-14",
    payload: {
      operation: "create",
      input: {
        client_request_id: "dismissed-success",
        food_item_id: "food-1",
        logged_date: "2026-07-14",
        amount_quantity: "1",
        amount_unit: "serving",
      },
    },
  });
  const dismissed = { ...record, state: "dismissed" as const, dismissed_from_state: "submitted" as const };
  await upsertLogMutationRecoveryRecord(dismissed, storage);
  const queryClient = trackedQueryClient();
  const result = log("log-confirmed", "2026-07-14");
  const outcome = await reconcileLogMutationRecoveryRecord(dismissed, queryClient, {
    storage,
    statusReader: async () => status(record, { result }),
  });
  expect(outcome).toBe("confirmed");
  expect(queryClient.getQueryData(["logs", "2026-07-14"])).toEqual([result]);
  expect(await loadLogMutationRecoveryJournal(storage)).toHaveLength(0);
});

test("malformed current records block mutation recovery without deleting valid or opaque data", async () => {
  const storage = memoryStorage(JSON.stringify({
    version: 2,
    records: [{ malformed: true }],
  }));
  expect(await loadLogMutationRecoveryJournal(storage)).toEqual([]);
  expect(getRecoveryJournalState().ready).toBe(false);
  expect(storage.value).toContain('"malformed":true');
});

test("unknown journal versions are ignored without destructive rewrite", async () => {
  const storage = memoryStorage(JSON.stringify({ version: 99, records: [{ future: true }] }));
  expect(await loadLogMutationRecoveryJournal(storage)).toEqual([]);
  expect(storage.value).toContain('"version":99');
  expect(storage.removeItem).not.toHaveBeenCalled();
});

test.each([
  ["create", "2026-07-14", "2026-07-14"],
  ["edit", "2026-07-14", "2026-07-15"],
  ["move", "2026-07-15", "2026-07-14"],
] as const)("confirmed %s recovery projects the authoritative result", async (mutationType, sourceDate, destinationDate) => {
  const storage = memoryStorage();
  const record = createLogMutationRecoveryRecord({
    clientRequestId: `request-${mutationType}`,
    mutationType,
    logId: mutationType === "create" ? null : "log-1",
    sourceDate,
    destinationDate,
  });
  await upsertLogMutationRecoveryRecord(record, storage);
  const queryClient = trackedQueryClient();
  queryClient.setQueryData(["logs", sourceDate], [log("log-1", sourceDate)]);

  const result = log("log-1", destinationDate);
  const outcome = await reconcileLogMutationRecoveryRecord(record, queryClient, {
    storage,
    statusReader: async () => status(record, { result, source_logged_date: sourceDate, destination_logged_date: destinationDate }),
  });

  expect(outcome).toBe("confirmed");
  expect(queryClient.getQueryData(["logs", destinationDate])).toEqual([result]);
});

test("confirmed delete recovery projects removal and removes the journal record", async () => {
  const storage = memoryStorage();
  const record = createLogMutationRecoveryRecord({
    clientRequestId: "delete-request",
    mutationType: "delete",
    logId: "log-1",
    sourceDate: "2026-07-14",
  });
  await upsertLogMutationRecoveryRecord(record, storage);
  const queryClient = trackedQueryClient();
  queryClient.setQueryData(["logs", "2026-07-14"], [log("log-1", "2026-07-14"), log("log-2", "2026-07-14")]);

  const outcome = await reconcileLogMutationRecoveryRecord(record, queryClient, {
    storage,
    statusReader: async () => status(record, { log_id: "log-1", result: null }),
  });

  expect(outcome).toBe("confirmed");
  expect(queryClient.getQueryData(["logs", "2026-07-14"])).toEqual([log("log-2", "2026-07-14")]);
});

test("unresolved and transport failures retain recovery records for later retry", async () => {
  const storage = memoryStorage();
  const record = createLogMutationRecoveryRecord({
    clientRequestId: "pending-request",
    mutationType: "edit",
    logId: "log-1",
    sourceDate: "2026-07-14",
  });
  await upsertLogMutationRecoveryRecord(record, storage);
  const queryClient = trackedQueryClient();
  const unresolved = await reconcileLogMutationRecoveryRecord(record, queryClient, {
    storage,
    statusReader: async () => status(record, { status: "unresolved" }),
  });
  expect(unresolved).toBe("pending");
  expect(await loadLogMutationRecoveryJournal(storage)).toHaveLength(1);

  const transport = await reconcileLogMutationRecoveryRecord(record, queryClient, {
    storage,
    statusReader: async () => { throw new Error("offline"); },
  });
  expect(transport).toBe("pending");
  expect(await loadLogMutationRecoveryJournal(storage)).toHaveLength(1);
});

test("reconciliation never crosses local and remote authority identities", async () => {
  const localAuthority = localAuthorityIdentity("00000000-0000-4000-8000-000000000001");
  const remoteRecord = createLogMutationRecoveryRecord({
    clientRequestId: "remote-request",
    mutationType: "edit",
    targetId: "log-remote",
    sourceDate: "2026-07-14",
  });
  const localRecord = createRecoveryRecordWithDisplayContext({
    authority: localAuthority,
    clientRequestId: "local-request",
    mutationType: "edit",
    targetId: "log-local",
    sourceDate: "2026-07-14",
    displayContext: { item_name: null, amount_label: null, meal_label: null },
  });
  const localStatus = jest.fn();
  const remoteStatus = jest.fn();

  await expect(reconcileRecoveryWithDependencies(remoteRecord, null, {
    authority: localAuthority,
    dailyLogs: { ...remoteNutritionRuntime.dailyLogs, getMutationStatus: localStatus },
  })).resolves.toBe("pending");
  await expect(reconcileRecoveryWithDependencies(localRecord, null, {
    authority: TEST_AUTHORITY,
    dailyLogs: { ...remoteNutritionRuntime.dailyLogs, getMutationStatus: remoteStatus },
  })).resolves.toBe("pending");
  expect(localStatus).not.toHaveBeenCalled();
  expect(remoteStatus).not.toHaveBeenCalled();
});

test("conflicting authoritative state refreshes affected dates and discards obsolete intent", async () => {
  const storage = memoryStorage();
  const record = createLogMutationRecoveryRecord({
    clientRequestId: "conflict-request",
    mutationType: "move",
    logId: "log-1",
    sourceDate: "2026-07-15",
    destinationDate: "2026-07-14",
  });
  await upsertLogMutationRecoveryRecord(record, storage);
  const queryClient = trackedQueryClient();
  queryClient.setQueryData(["logs", "2026-07-15"], []);
  queryClient.setQueryData(["logs", "2026-07-14"], []);

  const outcome = await reconcileLogMutationRecoveryRecord(record, queryClient, {
    storage,
    statusReader: async () => status(record, { status: "conflict" }),
  });

  expect(outcome).toBe("discarded");
  expect(await loadLogMutationRecoveryJournal(storage)).toHaveLength(0);
  expect(queryClient.getQueryState(["logs", "2026-07-15"])?.isInvalidated).toBe(true);
  expect(queryClient.getQueryState(["logs", "2026-07-14"])?.isInvalidated).toBe(true);
});

test("startup reconciliation handles multiple records in stable order and cleans them up", async () => {
  const storage = memoryStorage();
  const first = createLogMutationRecoveryRecord({
    clientRequestId: "first",
    mutationType: "create",
    sourceDate: "2026-07-14",
    createdAt: "2026-07-14T00:00:01.000Z",
  });
  const second = createLogMutationRecoveryRecord({
    clientRequestId: "second",
    mutationType: "delete",
    logId: "log-2",
    sourceDate: "2026-07-14",
    createdAt: "2026-07-14T00:00:02.000Z",
  });
  await upsertLogMutationRecoveryRecord({ ...second, state: "submitted" }, storage);
  await upsertLogMutationRecoveryRecord({ ...first, state: "submitted" }, storage);
  const calls: string[] = [];
  const queryClient = trackedQueryClient();
  const stop = startLogMutationRecovery(queryClient, {
    storage,
    retryDelayMs: 60_000,
    statusReader: async (requestId) => {
      calls.push(requestId);
      return status(requestId === "first" ? first : second);
    },
  });
  await new Promise((resolve) => setTimeout(resolve, 10));
  stop();

  expect(calls).toEqual(["first", "second"]);
  expect(await loadLogMutationRecoveryJournal(storage)).toEqual([]);
});
