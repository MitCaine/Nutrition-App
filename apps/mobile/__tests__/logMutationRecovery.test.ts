import { QueryClient } from "@tanstack/react-query";

declare const require: (moduleName: string) => {
  readFileSync(path: string, encoding: "utf8"): string;
};
const { readFileSync } = require("fs");

import type {
  DailyLog,
  DailyLogCreateInput,
  DailyLogDeleteInput,
  DailyLogMutationStatus,
  DailyLogUpdateInput,
} from "../src/features/logging/api/types";
import { parseDailyLogMutationStatus } from "../src/features/logging/api/logResponseSchemas";
import {
  createLogMutationRecoveryRecord as createRecoveryRecordWithDisplayContext,
  loadLogMutationRecoveryJournal as loadRecoveryJournalWithAuthority,
  reconcileLogMutationRecoveryRecord as reconcileRecoveryWithDependencies,
  persistRecoveryBeforeTransmission,
  dismissLogMutationRecoveryRecord,
  getRecoveryJournalState,
  hasOverlappingRecovery,
  LOG_MUTATION_RECOVERY_VERSION,
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

type LogMutationOperation = "create" | "update" | "delete";

type ActualPostgresStatusTrace = {
  schema_version: 1;
  operation: LogMutationOperation | "complete";
  client_request_id: string;
  owner_id: string;
  settlement: "committed" | "rolled_back";
  source_date: string;
  destination_date: string | null;
  request_payload: Record<string, unknown>;
  writer_backend_pid: number;
  reader_backend_pids: number[];
  returned_before_release: boolean[];
  status_responses: Array<{ status_code: number; body: string }>;
};

function loadActualPostgresStatusSequence(
  operation: LogMutationOperation,
): { trace: ActualPostgresStatusTrace; statuses: DailyLogMutationStatus[] } {
  const tracePath = process.env.GH278_STATUS_TRACE_PATH;
  if (!tracePath) throw new Error("GH278_STATUS_TRACE_PATH is required for coupled recovery checks");
  const lines = readFileSync(tracePath, "utf8").split(/\r?\n/).filter(Boolean);
  const traces = lines.map((line) => JSON.parse(line) as ActualPostgresStatusTrace);
  const matching = traces.filter(
    (trace) => trace.operation === operation && trace.settlement === "committed",
  );
  if (matching.length !== 1) {
    throw new Error(`expected one committed PostgreSQL trace for ${operation}; found ${matching.length}`);
  }
  const [trace] = matching;
  if (trace.schema_version !== 1 || trace.status_responses.length !== 3) {
    throw new Error(`malformed PostgreSQL status trace for ${operation}`);
  }
  if (trace.returned_before_release.join(",") !== "true,true,false") {
    throw new Error(`${operation} trace does not prove two reads returned before writer release`);
  }
  if (trace.reader_backend_pids.slice(0, 2).some((pid) => pid === trace.writer_backend_pid)) {
    throw new Error(`${operation} trace does not identify independent reader sessions`);
  }
  const statuses = trace.status_responses.map(({ status_code, body }) => {
    if (status_code !== 200 || typeof body !== "string") {
      throw new Error(`malformed serialized ${operation} status response`);
    }
    return parseDailyLogMutationStatus(JSON.parse(body));
  });
  if (statuses.map((item) => item.status).join(",") !== "unresolved,unresolved,confirmed_success") {
    throw new Error(`unexpected serialized PostgreSQL status sequence for ${operation}`);
  }
  if (statuses.some(
    (item) => item.operation !== operation || item.client_request_id !== trace.client_request_id,
  )) {
    throw new Error(`serialized PostgreSQL status identity mismatch for ${operation}`);
  }
  return { trace, statuses };
}

function recoveryRecordFromActualPostgresTrace(
  trace: ActualPostgresStatusTrace,
): ReturnType<typeof createLogMutationRecoveryRecord> {
  const { log_id: targetId, ...requestInput } = trace.request_payload;
  if (requestInput.client_request_id !== trace.client_request_id) {
    throw new Error(`submitted payload identity mismatch for ${trace.operation}`);
  }
  if (trace.operation === "create") {
    if (typeof requestInput.logged_date !== "string") {
      throw new Error("create trace is missing its submitted date");
    }
    return createLogMutationRecoveryRecord({
      clientRequestId: trace.client_request_id,
      mutationType: "create",
      sourceDate: requestInput.logged_date,
      payload: {
        operation: "create",
        input: requestInput as unknown as DailyLogCreateInput,
      },
    });
  }
  if (typeof targetId !== "string") throw new Error(`${trace.operation} trace is missing its log ID`);
  if (trace.operation === "update") {
    return createLogMutationRecoveryRecord({
      clientRequestId: trace.client_request_id,
      mutationType: "move",
      targetId,
      sourceDate: trace.source_date,
      destinationDate: trace.destination_date,
      payload: {
        operation: "update",
        log_id: targetId,
        input: requestInput as unknown as DailyLogUpdateInput,
      },
    });
  }
  return createLogMutationRecoveryRecord({
    clientRequestId: trace.client_request_id,
    mutationType: "delete",
    targetId,
    sourceDate: trace.source_date,
    payload: {
      operation: "delete",
      log_id: targetId,
      input: requestInput as unknown as DailyLogDeleteInput,
    },
  });
}

async function flushRecoveryManagerMicrotasks(): Promise<void> {
  for (let index = 0; index < 40; index += 1) await Promise.resolve();
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
    version: LOG_MUTATION_RECOVERY_VERSION,
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
  const { display_context: _displayContext, ...olderV2Fields } = current;
  const olderV2Record = { ...olderV2Fields, version: 2 };
  const storage = memoryStorage(JSON.stringify({ version: 2, records: [olderV2Record] }));

  const stored = (await loadLogMutationRecoveryJournal(storage))[0];

  expect(stored.display_context).toEqual({
    item_name: null,
    amount_label: null,
    meal_label: null,
  });
  expect(stored.version).toBe(LOG_MUTATION_RECOVERY_VERSION);
  expect(getRecoveryJournalState(TEST_AUTHORITY).ready).toBe(true);
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
    records: [{ ...authoritativeRecord, version: 2, display_context: displayContext }],
  }));
  const [record] = await loadLogMutationRecoveryJournal(storage);
  return { authoritativeRecord, record, state: getRecoveryJournalState(TEST_AUTHORITY) };
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
    records: [{ ...valid, version: 2, client_request_id: 42, display_context: { item_name: "Oatmeal" } }],
  }));

  expect(await loadLogMutationRecoveryJournal(storage)).toEqual([]);
  expect(getRecoveryJournalState(TEST_AUTHORITY)).toEqual(expect.objectContaining({
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
  expect(getRecoveryJournalState(TEST_AUTHORITY).ready).toBe(false);
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

const actualPostgresCoupledTest = process.env.GH278_REQUIRE_STATUS_TRACE === "1" ? test : test.skip;

for (const operation of ["create", "update", "delete"] as const) {
  actualPostgresCoupledTest(
    `automatic ${operation} recovery consumes the actual PostgreSQL status trace after reload`,
    async () => {
      const { trace, statuses } = loadActualPostgresStatusSequence(operation);
      const record = recoveryRecordFromActualPostgresTrace(trace);
      const persistedStorage = memoryStorage();
      await upsertLogMutationRecoveryRecord({ ...record, state: "submitted" }, persistedStorage);
      if (!persistedStorage.value) throw new Error("submitted recovery record was not persisted");
      const storage = memoryStorage(persistedStorage.value);
      const queryClient = trackedQueryClient();
      const sourceDate = trace.source_date;
      const destinationDate = trace.destination_date;
      const targetId = trace.request_payload.log_id;

      if (operation === "create") {
        queryClient.setQueryData(["logs", sourceDate], []);
      } else {
        if (typeof targetId !== "string") throw new Error(`${operation} trace is missing its target ID`);
        queryClient.setQueryData(["logs", sourceDate], [log(targetId, sourceDate)]);
      }
      if (operation === "update") {
        if (!destinationDate) throw new Error("update trace is missing its destination date");
        queryClient.setQueryData(["logs", destinationDate], []);
      }
      for (const date of new Set([sourceDate, destinationDate].filter((item): item is string => Boolean(item)))) {
        queryClient.setQueryData(["daily-summary", date], { date });
        queryClient.setQueryData(["target-comparison", date], { date });
        queryClient.setQueryData(["future-logs", date], []);
      }
      queryClient.setQueryData(["foods", "recent"], []);
      queryClient.setQueryData(["logs", "recent-entries"], []);

      const writeCalls = {
        create: jest.fn(remoteNutritionRuntime.dailyLogs.create),
        update: jest.fn(remoteNutritionRuntime.dailyLogs.update),
        delete: jest.fn(remoteNutritionRuntime.dailyLogs.delete),
        markDayComplete: jest.fn(remoteNutritionRuntime.dailyLogs.markDayComplete),
      };
      const dependencies = {
        authority: TEST_AUTHORITY,
        dailyLogs: { ...remoteNutritionRuntime.dailyLogs, ...writeCalls },
      };
      let statusRead = 0;
      const statusReader = jest.fn(async (requestId: string, requestedOperation: DailyLogMutationStatus["operation"]) => {
        statusRead += 1;
        expect(requestId).toBe(trace.client_request_id);
        expect(requestedOperation).toBe(operation);
        if (statusRead === 1) throw new Error("simulated transport loss before status read");
        const actualStatus = statuses[statusRead - 2];
        if (!actualStatus) throw new Error("automatic poll requested more than the serialized trace provides");
        return actualStatus;
      });

      let stop: (() => void) | undefined;
      jest.useFakeTimers();
      try {
        stop = startRecoveryWithDependencies(queryClient, dependencies, {
          storage,
          statusReader,
          retryDelayMs: 5,
        });
        await flushRecoveryManagerMicrotasks();
        expect(statusReader).toHaveBeenCalledTimes(1);
        expect((await loadLogMutationRecoveryJournal(storage))[0]).toEqual(
          expect.objectContaining({ client_request_id: trace.client_request_id, state: "submitted" }),
        );

        await jest.advanceTimersByTimeAsync(5);
        await flushRecoveryManagerMicrotasks();
        expect(statusReader).toHaveBeenCalledTimes(2);
        expect((await loadLogMutationRecoveryJournal(storage))[0]).toEqual(
          expect.objectContaining({ client_request_id: trace.client_request_id, state: "submitted" }),
        );

        await jest.advanceTimersByTimeAsync(10);
        await flushRecoveryManagerMicrotasks();
        expect(statusReader).toHaveBeenCalledTimes(3);
        expect((await loadLogMutationRecoveryJournal(storage))[0]).toEqual(
          expect.objectContaining({ client_request_id: trace.client_request_id, state: "submitted" }),
        );

        await jest.advanceTimersByTimeAsync(20);
        await flushRecoveryManagerMicrotasks();
        expect(statusReader).toHaveBeenCalledTimes(4);
        expect(await loadLogMutationRecoveryJournal(storage)).toEqual([]);
        expect(statusReader.mock.calls.map((call) => call[1])).toEqual([
          operation,
          operation,
          operation,
          operation,
        ]);

        const confirmed = statuses[2];
        if (operation === "create") {
          if (!confirmed.result) throw new Error("create status trace has no retained result");
          expect(queryClient.getQueryData(["logs", sourceDate])).toEqual([confirmed.result]);
        } else if (operation === "update") {
          if (!confirmed.result || !destinationDate) throw new Error("update trace is incomplete");
          expect(queryClient.getQueryData(["logs", sourceDate])).toEqual([]);
          expect(queryClient.getQueryData(["logs", destinationDate])).toEqual([confirmed.result]);
        } else {
          if (typeof targetId !== "string") throw new Error("delete trace is missing its target ID");
          expect(queryClient.getQueryData(["logs", sourceDate])).toEqual([]);
        }
        for (const date of new Set([sourceDate, destinationDate].filter((item): item is string => Boolean(item)))) {
          expect(queryClient.getQueryState(["logs", date])?.isInvalidated).toBe(true);
          expect(queryClient.getQueryState(["daily-summary", date])?.isInvalidated).toBe(true);
          expect(queryClient.getQueryState(["target-comparison", date])?.isInvalidated).toBe(true);
          expect(queryClient.getQueryState(["future-logs", date])?.isInvalidated).toBe(true);
        }
        expect(queryClient.getQueryState(["foods", "recent"])?.isInvalidated).toBe(true);
        expect(queryClient.getQueryState(["logs", "recent-entries"])?.isInvalidated).toBe(true);
        expect(writeCalls.create).not.toHaveBeenCalled();
        expect(writeCalls.update).not.toHaveBeenCalled();
        expect(writeCalls.delete).not.toHaveBeenCalled();
        expect(writeCalls.markDayComplete).not.toHaveBeenCalled();
      } finally {
        stop?.();
        jest.useRealTimers();
      }
    },
  );
}
